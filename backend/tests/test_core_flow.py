"""The kernel's promises, without HappyRobot: filtering, confidence,
validation, scarcity, approval and escalation, idempotency, re-planning."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from valte.core import actions, commands, learning, plan, signals, tripwires, world
from valte.core.plan import Conflict
from valte.db import session_scope
from valte.models import Action, Contact, Crisis, Entity, Lesson, Signal, Tripwire, Zone


def _sig(db, c, sid, *, source, channel, zone, sev, noise=False, precision="zone"):
    return signals.ingest_perception(db, c, {
        "id": sid, "source": source, "channel": channel, "zone": zone, "precision": precision,
        "is_noise": str(noise).lower(),  # HappyRobot sends strings
        "claims": "[]" if noise else '[{"hazard_type":"flood","severity_hint":%d}]' % sev,
        "summary": "test", "content": "test"})


def test_noise_is_kept_but_never_reaches_the_brain(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        res = _sig(db, c, "n1", source="social-media", channel="social", zone=None, sev=0, noise=True)
        assert res["noise"] and res["confidence"] is None
        state = world.build_state(db, c)
        assert "n1" not in [s["id"] for s in state["recent_signals"]]
        assert state["signal_counts"]["noise_discarded"] == 1


def test_corroboration_across_channels_lifts_a_low_trust_source(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        assert _sig(db, c, "s1", source="social-media", channel="social", zone="cheste", sev=6)["confidence"] == "low"
        _sig(db, c, "s2", source="112", channel="call", zone="cheste", sev=7, precision="street")
        assert db.get(Signal, (crisis_id, "s1")).confidence == "medium"  # the earlier post is re-scored


def test_zone_names_from_an_llm_resolve_and_threat_propagates_downstream(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "g1", source="chj-gauges", channel="sensor", zone="Chiva", sev=8, precision="exact")
        assert db.get(Zone, (crisis_id, "chiva")).severity_est == 8
        paiporta = db.get(Zone, (crisis_id, "paiporta"))
        assert paiporta.severity_est == 0 and paiporta.eta_min == 38  # dry, but on a countdown
        assert paiporta.at_risk_pct > 0


def test_kernel_rejects_what_the_brain_may_not_do(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "e1", source="112", channel="call", zone="paiporta", sev=8, precision="street")
        bad_verb = actions.propose_action(db, c, {"actor": "samu", "verb": "close_road", "target_zones": ["paiporta"], "evidence": ["e1"]})
        assert "cannot" in bad_verb["error"]
        bad_zone = actions.propose_action(db, c, {"actor": "policia-local-paiporta", "verb": "close_road", "target_zones": ["chiva"], "evidence": ["e1"]})
        assert "jurisdiction" in bad_zone["error"]
        no_evidence = actions.propose_action(db, c, {"actor": "cecopi", "verb": "send_es_alert", "target_zones": ["paiporta"], "evidence": ["sig-9999"]})
        assert "evidence" in no_evidence["error"]
        ok = actions.propose_action(db, c, {"actor": "cecopi", "verb": "send_es_alert", "target_zones": ["paiporta"], "evidence": ["e1"]})
        assert ok["status"] == "executed" and db.get(Zone, (crisis_id, "paiporta")).warned
        dup = actions.propose_action(db, c, {"actor": "cecopi", "verb": "send_es_alert", "target_zones": ["paiporta"], "evidence": ["e1"]})
        assert "duplicate" in dup["error"]


def test_scarce_units_are_reserved_and_released(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "r1", source="112", channel="call", zone="paiporta", sev=7, precision="street")  # below the triage reflex
        samu = db.get(Entity, (crisis_id, "samu"))
        assert actions.propose_action(db, c, {"actor": "samu", "verb": "rescue", "target_zones": ["paiporta"], "params": {"units": 6}, "evidence": ["r1"]})["status"] == "executed"
        assert samu.units_available == 2 and samu.deployed == {"paiporta": 6}
        too_many = actions.propose_action(db, c, {"actor": "samu", "verb": "rescue", "target_zones": ["picanya"], "params": {"units": 5}, "evidence": ["r1"]})
        assert "units free" in too_many["error"]
        c.anchor_scenario += timedelta(minutes=50)
        actions.release_due_units(db, c)
        assert samu.units_available == 8


def test_high_impact_actions_wait_for_a_human_then_escalate(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "a1", source="chj-gauges", channel="sensor", zone="chiva", sev=8, precision="exact")
        res = actions.propose_action(db, c, {"actor": "alcaldia-paiporta", "verb": "order_evacuation", "target_zones": ["paiporta"], "evidence": ["a1"]})
        act = db.get(Action, (crisis_id, res["id"]))
        assert act.status == "pending_approval" and act.approval["approver"] == "alcaldia-paiporta"
        assert not db.get(Zone, (crisis_id, "paiporta")).evacuating  # nothing happens until someone signs

        c.anchor_scenario += timedelta(minutes=11)  # nobody answers
        actions.expire_approvals(db, c)
        assert act.approval["approver"] == "delegacion-gobierno" and act.approval["level"] == 2
        contacts = list(db.scalars(select(Contact).where(Contact.crisis_id == crisis_id, Contact.action_id == act.id,
                                                         Contact.purpose == "approval")))
        assert {k.entity_id for k in contacts} == {"alcaldia-paiporta", "delegacion-gobierno"}

        actions.approve_action(db, c, act, by="delegacion-gobierno")
        assert act.status == "executed" and db.get(Zone, (crisis_id, "paiporta")).evacuating
        assert actions.approve_action(db, c, act, by="x").status == "executed"  # deciding twice is a no-op


def test_rejection_is_material_so_the_brain_adapts(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "j1", source="chj-gauges", channel="sensor", zone="chiva", sev=8, precision="exact")
        res = actions.propose_action(db, c, {"actor": "cecopi", "verb": "request_ume", "evidence": ["j1"]})
        act = db.get(Action, (crisis_id, res["id"]))
        actions.reject_action(db, c, act, by="delegacion-gobierno", reason="aún no")
        assert act.status == "rejected"
        digests = [e["digest"] for e in db.info["pending_events"] if e["material"] and e["digest"]]
        assert any("REJECTED" in d for d in digests)


def test_unreachable_actor_fails_and_escalates_along_the_chain(crisis_id, monkeypatch):
    from valte.core import outreach
    from valte.settings import settings

    monkeypatch.setattr(settings, "valte_outreach_mode", "real")
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "u1", source="112", channel="call", zone="torrent", sev=7, precision="street")
        police = db.get(Entity, (crisis_id, "policia-local-torrent"))
        police.extra = {"sim_unreachable": True}  # ground truth the system cannot see
        res = actions.propose_action(db, c, {"actor": "policia-local-torrent", "verb": "close_road", "target_zones": ["torrent"], "evidence": ["u1"]})
        act = db.get(Action, (crisis_id, res["id"]))
        assert act.status == "approved"  # ordered, not yet acknowledged
        k = db.scalars(select(Contact).where(Contact.crisis_id == crisis_id, Contact.action_id == act.id)).one()
        k.ring_deadline_wall -= timedelta(seconds=60)
        monkeypatch.setattr(settings, "valte_outreach_mode", "dry")  # the escalation contact itself stays in-process
        outreach.expire_rings(db, c)
        assert act.status == "failed" and police.status == "unreachable"
        follow_up = db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.escalated_from == act.id)).one()
        assert follow_up.actor == "guardia-civil-torrent" and follow_up.origin == "escalation"


def test_a_person_reads_one_of_six_states(crisis_id, monkeypatch):
    from valte.core import outreach, views
    from valte.settings import settings

    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "x1", source="112", channel="call", zone="paiporta", sev=7, precision="street")
        _sig(db, c, "x2", source="chj-gauges", channel="sensor", zone="chiva", sev=8, precision="exact")
        _sig(db, c, "x3", source="112", channel="call", zone="torrent", sev=7, precision="street")

        def propose(**a):
            return db.get(Action, (crisis_id, actions.propose_action(db, c, a)["id"]))

        alert = propose(actor="cecopi", verb="send_es_alert", target_zones=["paiporta"], evidence=["x1"])
        rescue = propose(actor="samu", verb="rescue", target_zones=["paiporta"], params={"units": 2}, evidence=["x1"])
        evac = propose(actor="alcaldia-paiporta", verb="order_evacuation", target_zones=["paiporta"], evidence=["x2"])
        ume = propose(actor="cecopi", verb="request_ume", evidence=["x2"])
        actions.reject_action(db, c, ume, by="delegacion-gobierno", reason="aún no")
        monkeypatch.setattr(settings, "valte_outreach_mode", "real")
        road = propose(actor="policia-local-torrent", verb="close_road", target_zones=["torrent"], evidence=["x3"])
        monkeypatch.setattr(settings, "valte_outreach_mode", "dry")

        state = world.action_state
        assert [state(a) for a in (alert, rescue, evac, ume, road)] == ["done", "in_progress", "pending_approval", "rejected", "waiting"]
        counts = views.actions_screen(db, c)["counts"]
        assert set(counts) == {"all", *world.ACTION_STATES} and counts["all"] == sum(counts[s] for s in world.ACTION_STATES)
        assert [r["action"]["id"] for r in views.actions_screen(db, c, status="in_progress")["log"]] == [rescue.id]

        c.anchor_scenario += timedelta(minutes=50)  # the units come back; nobody picked up in Torrent
        actions.release_due_units(db, c)
        k = db.scalars(select(Contact).where(Contact.crisis_id == crisis_id, Contact.action_id == road.id)).one()
        k.ring_deadline_wall -= timedelta(seconds=60)
        outreach.expire_rings(db, c)
        assert (state(rescue), state(road)) == ("done", "failed")

        ume = propose(actor="cecopi", verb="request_ume", evidence=["x2"])
        actions.approve_action(db, c, ume, by="delegacion-gobierno")
        assert state(ume) == "in_progress"  # asked for, not on the ground yet
        c.anchor_scenario += timedelta(minutes=(db.get(Entity, (crisis_id, "ume")).activation or {}).get("delay_min", 180) + 1)
        actions.tick_world(db, c, 1)
        assert state(ume) == "done"


def test_tripwires_fire_on_threshold_and_on_silence(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        armed = actions.propose_action(db, c, {"actor": "system", "verb": "set_tripwire", "params": {"tripwire": {
            "id": "tw-chiva-7", "if": {"source": "chj-gauges", "zone": "chiva", "min_severity": 7},
            "then": [{"actor": "cecopi", "verb": "activate_emergency_level", "params": {"level": 2}}], "reason": "test"}}})
        assert armed["status"] == "executed"
        assert "already active" in actions.propose_action(db, c, {"actor": "system", "verb": "set_tripwire", "params": {"tripwire": {"id": "tw-chiva-7", "if": {}}}})["error"]
        _sig(db, c, "t1", source="chj-gauges", channel="sensor", zone="chiva", sev=7, precision="exact")
        assert c.emergency_level == 2 and not db.get(Tripwire, (crisis_id, "tw-chiva-7")).active

        assert tripwires.evaluate_silence(db, c, world.scenario_now(c)) == []
        assert tripwires.evaluate_silence(db, c, world.scenario_now(c) + timedelta(minutes=25)) == ["tw-gauge-silence"]


def test_gateway_commands_are_idempotent_and_plans_use_optimistic_concurrency(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        cmd = {"command_id": "c1", "command_type": "replace_plan", "expected_plan_version": "0",
               "payload_json": '{"incidents":[{"incident_id":"inc-a","priority":"P0","zone_ids":["paiporta"]}],"plan":{"summary":"s","objectives":[]}}'}
        assert commands.apply_command(db, c, cmd)["plan_version"] == 1
        assert commands.apply_command(db, c, cmd)["duplicate"] is True and c.plan_version == 1
        with pytest.raises(Conflict):
            commands.apply_command(db, c, {**cmd, "command_id": "c2"})  # still expects version 0
        with pytest.raises(commands.BadCommand):
            commands.apply_command(db, c, {"command_id": "c3", "command_type": "nope", "payload": {}})


def test_plan_dies_when_the_world_gets_worse_not_when_a_reading_wobbles(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "p1", source="chj-gauges", channel="sensor", zone="chiva", sev=5, precision="exact")
        plan.replace_plan(db, c, {"incidents": [], "plan": {"summary": "v1"}})
        _sig(db, c, "p2", source="chj-gauges", channel="sensor", zone="chiva", sev=6, precision="exact")
        assert plan.check_plan_validity(db, c) == []  # same band
        _sig(db, c, "p3", source="chj-gauges", channel="sensor", zone="chiva", sev=8, precision="exact")
        assert any("chiva" in r for r in plan.check_plan_validity(db, c))


def test_closing_a_crisis_teaches_the_next_one(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        for i in range(5):
            _sig(db, c, f"l{i}", source="local-news", channel="news", zone=None, sev=0, noise=True)
        lessons = learning.close_crisis(db, c)
        assert c.status == "closed" and any(l.kind == "source_reliability" and l.subject == "local-news" for l in lessons)
    with session_scope() as db:
        nxt = world.create_crisis(db, {"pack": "riada-paiporta"})
        applied = learning.apply_lessons(db, nxt)
        assert db.get(Entity, (nxt.id, "local-news")).trust == "low" and applied
        assert db.scalars(select(Lesson).where(Lesson.source_crisis_id == crisis_id)).first() is not None
        assert world.build_state(db, nxt)["lessons"]


def test_one_person_gets_one_call_at_a_time(crisis_id, monkeypatch):
    from valte.core import outreach
    from valte.settings import settings

    monkeypatch.setattr(settings, "valte_outreach_mode", "real")
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _sig(db, c, "v1", source="chj-gauges", channel="sensor", zone="chiva", sev=5, precision="exact")
        first = actions.propose_action(db, c, {"actor": "alcaldia-paiporta", "verb": "order_evacuation", "target_zones": ["paiporta"], "evidence": ["v1"]})
        second = actions.propose_action(db, c, {"actor": "alcaldia-paiporta", "verb": "close_road", "target_zones": ["paiporta"], "evidence": ["v1"]})
        calls = {k.action_id: k for k in db.scalars(select(Contact).where(Contact.crisis_id == crisis_id, Contact.channel == "voice"))}
        assert calls[first["id"]].status == "ringing" and calls[second["id"]].status == "queued"

        outreach.finish_call(db, c, calls[first["id"]], [{"who": "Agente", "text": "¿Lo aprueba?"}, {"who": "Interlocutor", "text": "Sí, adelante."}])
        assert db.get(Action, (crisis_id, first["id"])).status == "executed"
        assert calls[second["id"]].status == "ringing"  # the line is free: the next call goes through

        third = actions.propose_action(db, c, {"actor": "alcaldia-paiporta", "verb": "open_shelter", "target_zones": ["paiporta"], "evidence": ["v1"]})
        waiting = db.scalars(select(Contact).where(Contact.crisis_id == crisis_id, Contact.action_id == third["id"])).one()
        actions.fail_action(db, c, db.get(Action, (crisis_id, third["id"])), "ya no hace falta", escalate=False)
        outreach.finish_call(db, c, calls[second["id"]], [{"who": "Agente", "text": "Corte la carretera."}, {"who": "Interlocutor", "text": "Entendido."}])
        assert waiting.status == "superseded"  # nobody is rung about something already withdrawn
