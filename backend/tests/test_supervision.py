"""What the human supervisor sees: the 'what changed' strip, plan reasons in Spanish, and that a crisis declared
from the wizard (no pack) still moves, gets served and can call for reinforcements."""

from datetime import timedelta

from sqlalchemy import select

from valte.core import actions, plan, signals, views, world
from valte.db import session_scope
from valte.engine import loop
from valte.models import Action, Crisis, Entity, Signal


def _sig(db, c, sid, *, source, channel, zone, sev, precision="zone"):
    return signals.ingest_perception(db, c, {
        "id": sid, "source": source, "channel": channel, "zone": zone, "precision": precision, "is_noise": "false",
        "claims": '[{"hazard_type":"flood","severity_hint":%d}]' % sev, "summary": "test", "content": f"aviso {sid}"})


def test_recent_changes_tell_the_story_in_spanish_and_respect_a_jurisdiction(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "c1", source="chj-gauges", channel="sensor", zone="chiva", sev=5, precision="exact")
        plan.replace_plan(db, c, {"incidents": [], "plan": {"summary": "Vigilar Chiva"}})
        _sig(db, c, "c2", source="112", channel="call", zone="paiporta", sev=8, precision="street")
        plan.check_plan_validity(db, c)
        res = actions.propose_action(db, c, {"actor": "cecopi", "verb": "request_ume", "evidence": ["c2"]})
        actions.reject_action(db, c, db.get(Action, (crisis_id, res["id"])), by="delegacion-gobierno", reason="aún no")

        lines = views.recent_changes(db, c, limit=10)
        text = " | ".join(x["text"] for x in lines)
        assert "Delegación del Gobierno rechaza" in text
        assert "Plan v1 invalidado: paiporta pasa de severidad baja a alta" in text
        assert "112 Comunitat Valenciana · Paiporta · severidad 8" in text
        assert [x["seq"] for x in lines] == sorted((x["seq"] for x in lines), reverse=True)  # newest first
        assert all(x["time"] and x["tone"] and x["glyph"] for x in lines)

        only_chiva = views.recent_changes(db, c, limit=10, zone_ids=["chiva"])
        assert not any("Paiporta · severidad" in x["text"] for x in only_chiva)
        assert views.overview(db, c, role="coordination")["changes"]


def test_plan_reasons_are_translated_for_the_supervisor():
    assert views.reasons_es("zone torrent severity band mid -> high; entity unreachable: samu; two more actions failed") == \
        "torrent pasa de severidad media a alta; samu no contesta; dos acciones más han fallado"
    assert views.reasons_es(None) == ""


def test_a_wizard_crisis_without_a_pack_moves_on_its_own_and_gets_served():
    with session_scope() as db:
        c = world.create_crisis(db, {"name": "Apagón de prueba", "hazard_type": "blackout", "region": "Horta Nord", "zones": [
            {"name": "Burjassot", "population": 38000, "is_origin": True, "to": ["Godella · 12 min"]},
            {"name": "Godella", "population": 13000}]})
        world.start_crisis(db, c)
        cid = c.id
    for _ in range(30):  # fast-forward the scenario: 3 scenario minutes per tick
        with session_scope() as db:
            c = db.get(Crisis, cid)
            c.anchor_scenario += timedelta(minutes=3)
            c.wake = {k: v for k, v in (c.wake or {}).items() if k not in ("coord_last", "cmd_last")}
        loop.tick(cid)
    with session_scope() as db:
        c = db.get(Crisis, cid)
        sigs = list(db.scalars(select(Signal).where(Signal.crisis_id == cid)))
        assert len(sigs) >= 10 and any(s.is_noise for s in sigs)
        assert {s.zone_id for s in sigs if s.zone_id} == {"burjassot", "godella"}
        assert c.severity >= 7 and c.emergency_level >= 1
        served = list(db.scalars(select(Action).where(Action.crisis_id == cid, Action.verb == "rescue")))
        assert served, "a severe, street-level call must get units"


def test_reinforcements_exist_for_any_crisis_and_arrive_after_their_delay():
    with session_scope() as db:
        c = world.create_crisis(db, {"name": "Incendio de prueba", "hazard_type": "fire", "zones": [{"name": "Serra", "is_origin": True}]})
        world.start_crisis(db, c)
        ume = db.get(Entity, (c.id, "ume"))
        assert ume is not None and ume.units_available == 0 and ume.activation["cost"] == "high"
        _sig(db, c, "u1", source="112", channel="call", zone="serra", sev=8, precision="street")
        res = actions.propose_action(db, c, {"actor": "cecopi", "verb": "request_ume", "evidence": ["u1"]})
        act = db.get(Action, (c.id, res["id"]))
        assert act.status == "pending_approval"  # costly: a human signs first
        actions.approve_action(db, c, act, by="delegacion-gobierno")
        assert ume.status == "busy" and "arrives_t" in ume.extra
        c.anchor_scenario += timedelta(minutes=181)
        actions.tick_world(db, c, 1)
        assert ume.status == "available" and ume.units_available == ume.units_total
