"""Decisions and resources follow the data: needs open when a report asks for help, reflexes dispatch the
life-threatening ones at once, scarce units go to the worst first and come back to whoever is still waiting."""

from datetime import timedelta

from sqlalchemy import select

from valte.core import actions, needs, signals, world
from valte.db import session_scope
from valte.engine import local_brain
from valte.models import Action, Crisis, Entity, Event, Resource, Tripwire, Zone


def _call(db, c, sid, zone, sev, precision="street", source="112", channel="call"):
    return signals.ingest_perception(db, c, {"id": sid, "source": source, "channel": channel, "zone": zone,
                                             "precision": precision, "is_noise": "false", "summary": f"report {sid}",
                                             "claims": '[{"hazard_type":"flood","severity_hint":%d}]' % sev})


def _acts(db, cid, **where):
    q = select(Action).where(Action.crisis_id == cid)
    for k, v in where.items():
        q = q.where(getattr(Action, k) == v)
    return list(db.scalars(q.order_by(Action.seq)))


def test_every_crisis_starts_with_a_standing_triage_reflex(crisis_id):
    with session_scope() as db:
        tw = db.get(Tripwire, (crisis_id, "tw-triaje-rescate"))
        assert tw.active and tw.repeat and tw.then[0]["actor"] == "auto"


def test_life_threatening_report_gets_units_the_moment_it_arrives(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "n1", "paiporta", 8)
        [rescue] = _acts(db, crisis_id, verb="rescue")
        assert rescue.origin == "tripwire" and rescue.evidence == ["n1"] and rescue.target_zones == ["paiporta"]
        actor = db.get(Entity, (crisis_id, rescue.actor))
        assert "paiporta" in actor.jurisdiction and actor.deployed == {"paiporta": 2}
        assert db.get(Tripwire, (crisis_id, "tw-triaje-rescate")).active  # standing: still armed
        assert needs.open_needs(db, c) == []  # covered by the reflex

        _call(db, c, "n2", "paiporta", 9)  # a second incident in the same zone is a second job, not a duplicate
        assert [a.evidence for a in _acts(db, crisis_id, verb="rescue")] == [["n1"], ["n2"]]


def test_reflex_ignores_vague_unverified_or_sensor_reports(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "v1", "picanya", 9, precision="zone")                                  # no street: nowhere to send a crew
        _call(db, c, "v2", "massanassa", 9, source="social-media", channel="social")          # low trust, uncorroborated
        _call(db, c, "v3", "chiva", 9, precision="exact", source="chj-gauges", channel="sensor")  # a gauge is not a person
        assert _acts(db, crisis_id, verb="rescue") == []
        # ...but the ones about people stay on the list for the brain to weigh
        assert {n["signal_id"] for n in needs.open_needs(db, c)} == {"v1", "v2"}


def test_open_needs_are_ordered_worst_first_and_close_when_someone_is_assigned(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "o1", "cheste", 6)
        _call(db, c, "o2", "torrent", 7)
        assert [n["signal_id"] for n in needs.open_needs(db, c)] == ["o2", "o1"]
        state = world.build_state(db, c)
        assert [n["signal_id"] for n in state["open_needs"]] == ["o2", "o1"]
        assert any(r["entity"] == "bomberos-vlc" and r["free"] == 40 for r in state["resource_board"])

        res = actions.propose_action(db, c, {"actor": "guardia-civil-torrent", "verb": "rescue", "target_zones": ["torrent"],
                                             "params": {"units": 2}, "evidence": ["o2"], "reasoning": "x"})
        assert res["status"] == "executed"
        assert [n["signal_id"] for n in needs.open_needs(db, c)] == ["o1"]
        # the same need cannot be served twice by someone else: reinforcement must say so
        dup = actions.propose_action(db, c, {"actor": "bomberos-vlc", "verb": "rescue", "target_zones": ["torrent"],
                                             "params": {"units": 2}, "evidence": ["o2"], "reasoning": "x"})
        assert "already on" in dup["error"]
        more = actions.propose_action(db, c, {"actor": "bomberos-vlc", "verb": "rescue", "target_zones": ["torrent"],
                                              "params": {"units": 3}, "evidence": ["o2", res["id"]], "reasoning": "refuerzo"})
        assert more["status"] == "executed"


def test_nearest_responder_with_units_goes_first_and_scarcity_wakes_the_brain(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        assert needs.pick_responder(db, c, "rescue", "chiva", 2).id == "bomberos-vlc"  # 0 min activation beats 10
        for e in db.scalars(select(Entity).where(Entity.crisis_id == crisis_id, Entity.kind == "responder")):
            e.units_available = 0
        assert needs.pick_responder(db, c, "rescue", "chiva", 2) is None
        _call(db, c, "s1", "chiva", 9)
        assert _acts(db, crisis_id, verb="rescue") == []
        digests = [e.digest for e in db.scalars(select(Event).where(Event.crisis_id == crisis_id, Event.material.is_(True)))]
        assert any("NO FREE UNITS" in (d or "") for d in digests)  # the brain is told, with the evidence
        assert [n["signal_id"] for n in needs.open_needs(db, c)] == ["s1"]


def test_material_goes_out_with_the_crew_and_comes_back(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        db.get(Zone, (crisis_id, "paiporta")).severity_est = 8
        _call(db, c, "m1", "picanya", 6)
        boats = next(r for r in db.scalars(select(Resource).where(Resource.crisis_id == crisis_id)) if r.id.startswith("embarcaciones"))
        pumps = next(r for r in db.scalars(select(Resource).where(Resource.crisis_id == crisis_id)) if r.id.startswith("bombas-achique"))
        owner = pumps.owner_entity_id
        before = (boats.available, pumps.available)
        actions.propose_action(db, c, {"actor": owner, "verb": "pump_water", "target_zones": ["picanya"], "params": {"units": 3},
                                       "evidence": ["m1"], "reasoning": "x"})
        assert pumps.available == before[1] - 3
        c.anchor_scenario += timedelta(minutes=50)
        assert actions.release_due_units(db, c) == 3 and pumps.available == before[1]


def test_local_brain_allocates_every_open_need_it_can(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "b1", "cheste", 7)
        _call(db, c, "b2", "massanassa", 6)
        local_brain.decide(db, c)
        served = {e for a in _acts(db, crisis_id) if a.verb in ("rescue", "wellness_check") for e in a.evidence}
        assert {"b1", "b2"} <= served and needs.open_needs(db, c) == []
