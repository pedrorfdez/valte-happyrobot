"""The proactive brain: a round nobody asked for finds what produces no event (an unwarned zone downstream, stock
running out, crews parked where it calmed down) and acts through the same pipeline; logistics verbs move units and stock."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from valte.core import actions, logistics, needs, signals, views, world
from valte.db import session_scope
from valte.engine import loop, patrol
from valte.hr import specs
from valte.models import Action, Crisis, Entity, Event, Resource, Zone, utcnow

AUTH = {"Authorization": "Bearer test-secret"}


def _call(db, c, sid, zone, sev, precision="street", source="112", channel="call"):
    return signals.ingest_perception(db, c, {"id": sid, "source": source, "channel": channel, "zone": zone,
                                             "precision": precision, "is_noise": "false", "summary": f"report {sid}",
                                             "claims": '[{"hazard_type":"flood","severity_hint":%d}]' % sev})


def _system(db, c, verb, **params):
    return actions.propose_action(db, c, {"actor": "system", "verb": verb, "params": params, "evidence": ["pat-test"],
                                          "reasoning": "x"}, origin="proactive")


def _due(c):
    """Make the next tick a patrol round: the cadence is wall time."""
    c.wake = {**(c.wake or {}), "patrol_last": (utcnow() - timedelta(seconds=3600)).isoformat()}


def test_stock_changes_hands_and_the_lender_keeps_a_floor(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        pumps = db.get(Resource, (crisis_id, "bombas-achique"))
        assert "lend at most 9" in _system(db, c, "transfer_resource", resource="bombas-achique", to="ume", qty=10)["error"]
        assert "another entity" in _system(db, c, "transfer_resource", resource="bombas-achique", to=pumps.owner_entity_id, qty=2)["error"]
        res = _system(db, c, "transfer_resource", resource="bombas-achique", to="ume", qty=4)
        assert res["status"] == "executed" and db.get(Action, (crisis_id, res["id"])).origin == "proactive"
        lent = db.get(Resource, (crisis_id, "bombas-achique-ume"))
        assert (pumps.available, pumps.total, lent.available, lent.owner_entity_id) == (8, 8, 4, "ume")
        # a second loan lands in the same inventory instead of opening a third one
        _system(db, c, "transfer_resource", resource="bombas-achique", to="ume", qty=1)
        assert lent.available == 5 and db.get(Resource, (crisis_id, "bombas-achique-ume-ume")) is None


def test_resupply_takes_time_to_arrive_and_is_not_ordered_twice(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        water = db.get(Resource, (crisis_id, "agua"))
        water.available = 200
        assert _system(db, c, "request_resupply", resource="agua", qty=1000, eta_min=5)["status"] == "executed"
        assert "already on their way" in _system(db, c, "request_resupply", resource="agua", qty=500)["error"]
        assert world.build_state(db, c)["incoming_resupply"][0]["eta_min"] == logistics.RESUPPLY_MIN_ETA  # never instant
        assert logistics.deliver_due(db, c, world.scenario_now(c)) == 0 and water.available == 200
        c.anchor_scenario += timedelta(minutes=21)
        assert logistics.deliver_due(db, c, world.scenario_now(c)) == 1 and water.available == 1200
        assert logistics.deliveries(c) == []
        assert any("Llega la reposición" in ch["text"] for ch in views.recent_changes(db, c))


def test_recalled_units_are_free_at_once_and_do_not_come_back_twice(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "r1", "torrent", 7)
        job = actions.propose_action(db, c, {"actor": "guardia-civil-torrent", "verb": "rescue", "target_zones": ["torrent"],
                                             "params": {"units": 4}, "evidence": ["r1"], "reasoning": "x"})
        gc = db.get(Entity, (crisis_id, "guardia-civil-torrent"))
        assert gc.units_available == 10
        assert _system(db, c, "recall_units", action_id=job["id"])["status"] == "executed"
        assert gc.units_available == 14 and gc.deployed == {}
        assert "nothing to recall" in _system(db, c, "recall_units", action_id=job["id"])["error"]
        c.anchor_scenario += timedelta(minutes=60)
        assert actions.release_due_units(db, c) == 0 and gc.units_available == 14


def test_a_round_warns_the_calm_zone_downstream_that_nobody_asked_about(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "p1", "chiva", 8, precision="zone")  # upstream is hit; everything below it now has a countdown
        calm = [z for z in db.scalars(select(Zone).where(Zone.crisis_id == crisis_id))
                if z.eta_min is not None and 0 < z.eta_min <= patrol.WARN_ETA_MIN and not z.warned]
        assert calm, "the pack must have a zone within the warning window of chiva"
        found = patrol.sweep(db, c)
        [alert] = [f["suggested_action"] for f in found if f["id"].startswith("pat-aviso-")]  # one alert, not one per zone
        assert alert["verb"] == "send_es_alert" and set(alert["target_zones"]) >= {z.id for z in calm} and alert["evidence"] == ["p1"]
        assert all(f["id"].startswith("pat-") and f["what"] for f in found)

        patrol.maybe_patrol(db, c)  # first sight: waits one interval, does nothing
        assert not list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.origin == "proactive")))
        _due(c)
    loop.tick(crisis_id)
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        alerts = list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.origin == "proactive",
                                                      Action.verb == "send_es_alert")))
        assert {z for a in alerts for z in a.target_zones} >= {z.id for z in calm}
        assert all(a.evidence and a.reasoning.startswith("Ronda proactiva") for a in alerts)
        assert all(db.get(Zone, (crisis_id, z.id)).warned for z in calm)
        result = db.scalars(select(Event).where(Event.crisis_id == crisis_id, Event.type == "patrol.result")).one()
        assert result.material and "proactive round acted on its own" in result.digest  # the coordinator is told
        assert any("Ronda proactiva" in ch["text"] for ch in views.recent_changes(db, c))

        # the next round sees the same world: nothing new, nothing spent, nothing repeated
        n = len(list(db.scalars(select(Action).where(Action.crisis_id == crisis_id))))
        _due(c)
        patrol.maybe_patrol(db, c)
        assert len(list(db.scalars(select(Action).where(Action.crisis_id == crisis_id)))) == n


def test_a_round_asks_for_more_before_stock_runs_out_and_pulls_crews_from_a_calm_zone(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        db.get(Resource, (crisis_id, "mantas")).available = 100  # of 800, and nobody else holds blankets
        _call(db, c, "q1", "cheste", 6)
        job = actions.propose_action(db, c, {"actor": "guardia-civil-chiva", "verb": "wellness_check", "target_zones": ["cheste"],
                                             "params": {"units": 8}, "evidence": ["q1"], "reasoning": "x"})
        assert job["status"] == "executed"
        cheste = db.get(Zone, (crisis_id, "cheste"))
        cheste.severity_est, cheste.trend = 2, "falling"
        c.anchor_scenario += timedelta(minutes=patrol.RECALL_AFTER_MIN + 1)

        found = {f["id"]: f["suggested_action"] for f in patrol.sweep(db, c)}
        assert found["pat-stock-mantas"]["verb"] == "request_resupply"
        assert found[f"pat-retirada-{job['id']}"]["params"] == {"action_id": job["id"]}  # its owner has no units left

        _due(c)
        patrol.maybe_patrol(db, c)
        assert db.get(Entity, (crisis_id, "guardia-civil-chiva")).units_available == 8
        assert [d["resource"] for d in logistics.deliveries(c)] == ["mantas"]
        assert "pat-stock-mantas" not in {f["id"] for f in patrol.sweep(db, c)}  # already on its way


def test_a_need_that_waited_too_long_gets_someone(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "w1", "massanassa", 7, precision="zone")  # no street: the reflex does not fire
        assert [n["signal_id"] for n in needs.open_needs(db, c)] == ["w1"]
        assert not [f for f in patrol.sweep(db, c) if f["id"] == "pat-espera-w1"]  # the coordinator's job, for now
        c.anchor_scenario += timedelta(minutes=patrol.STALE_NEED_MIN + 1)
        _due(c)
        patrol.maybe_patrol(db, c)
        assert needs.open_needs(db, c) == []


@pytest.fixture(scope="module")
def client():
    from valte.main import app

    with TestClient(app) as c:
        yield c


def test_the_workflow_answers_through_its_own_callback(client, crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _call(db, c, "h1", "chiva", 8, precision="zone")
        c.wake = {**(c.wake or {}), "patrol_inflight": "pat-x", "patrol_since": utcnow().isoformat()}
    assert client.post("/hr/proactive", params={"crisis_id": crisis_id}, json={}).status_code == 401
    body = {"actions": [
        {"actor": "cecopi", "verb": "send_es_alert", "target_zones": ["cheste"], "params": {"message": "Aviso"},
         "evidence": ["h1"], "reasoning": "Cheste está aguas abajo de Chiva."},
        {"actor": "system", "verb": "request_resupply", "params": {"resource": "agua", "qty": 600}, "evidence": ["pat-stock-agua"],
         "reasoning": "Se pide antes de que falte."},
        {"actor": "cecopi", "verb": "send_es_alert", "target_zones": ["cheste"], "evidence": [], "reasoning": "sin evidencia"}],
        "patrol_note": "Aviso a Cheste y agua en camino."}
    r = client.post("/hr/proactive", params={"crisis_id": crisis_id, "dispatch_id": "pat-x", "hr_run_id": "run-1"},
                    headers=AUTH, json=body)
    assert r.status_code == 200 and (r.json()["accepted"], r.json()["rejected"]) == (2, 1), r.text
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        assert "patrol_inflight" not in c.wake and db.get(Zone, (crisis_id, "cheste")).warned
        assert {a.verb for a in db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.origin == "proactive"))} \
            == {"send_es_alert", "request_resupply"}


def test_the_workflow_is_provisioned_with_the_others():
    spec = next(s for s in specs.all_specs() if s.name == "PedroD-proactive")
    assert [n.name for n in spec.nodes] == ["trigger", "extract", "post"]
    ids = {n.name: f"<{n.name}>" for n in spec.nodes}
    post = spec.nodes[2].config(ids, specs.Ctx(secret="s"))
    assert post["url"][0]["children"][-1]["text"].endswith("/hr/proactive") or "/hr/proactive" in str(post["url"])
    assert post["body"]["raw"] == "{{$var:<extract>.response#decisions_json}}"
    assert set(spec.nodes[0].config(ids, specs.Ctx(secret="s"))["params"]) >= {
        "findings_json", "state_json", "callback_base", "environment"}
    coord = next(s for s in specs.all_specs() if s.name == "PedroD-coordinator")
    assert "environment" in coord.nodes[0].config({n.name: n.name for n in coord.nodes}, specs.Ctx(secret="s"))["params"]
