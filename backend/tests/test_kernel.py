"""Kernel invariant matrix. Runs against a live kernel on localhost:8100
with the repo .env loaded (real Supabase). Each session creates a fresh run."""

import os
import time
import uuid

import httpx
import pytest

K = "http://localhost:8100"
HEADERS = {"Authorization": f"Bearer {os.environ['WORLD_API_TOKEN']}"}


@pytest.fixture(scope="session")
def client():
    c = httpx.Client(base_url=K, headers=HEADERS, timeout=15)
    r = c.post("/runs", json={"scenario_id": "dana-valencia", "notes": "pytest"})
    assert r.status_code == 200, r.text
    yield c
    c.close()


def sig(client, sid, source, trust, sev, zone="paiporta", t="2024-10-29T18:45:00+01:00"):
    return client.post("/signals", json={
        "id": sid, "t": t, "source": source, "source_trust": trust,
        "modality": "text", "content": f"test {sid}",
        "claims": [{"hazard_type": "flood", "severity_hint": sev}],
        "location": {"zone": zone, "precision": "zone"}})


def act(client, aid, actor, verb, zones=None, params=None, evidence=None, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/actions", headers=headers, json={
        "id": aid, "t": "2024-10-29T18:50:00+01:00", "actor": actor, "verb": verb,
        "target_zones": zones or [], "params": params or {},
        "status": "approved", "evidence": evidence or ["sig-base"],
        "reasoning": "test"})


def test_signal_and_base_action(client):
    assert sig(client, "sig-base", "112-calls", "medium", 8).status_code == 201


def test_unknown_verb_rejected(client):
    r = act(client, "act-t1", "bomberos-torrent", "send_es_alert")
    assert r.status_code == 422 and "capabilities" in r.text


def test_out_of_jurisdiction_rejected(client):
    r = act(client, "act-t2", "mayor-paiporta", "order_evacuation", zones=["torrent"])
    assert r.status_code == 422 and "jurisdiction" in r.text


def test_missing_evidence_ref_rejected(client):
    r = act(client, "act-t3", "bomberos-torrent", "rescue",
            zones=["paiporta"], evidence=["sig-nonexistent"])
    assert r.status_code == 422


def test_units_ledger_and_over_capacity(client):
    r = act(client, "act-t4", "bomberos-torrent", "rescue",
            zones=["paiporta"], params={"units": 2})
    assert r.status_code == 201 and r.json()["units_committed"] == 2
    r2 = act(client, "act-t5", "bomberos-torrent", "rescue",
             zones=["catarroja"], params={"units": 1})
    assert r2.status_code == 409 and "0 unit(s) available" in r2.text
    # release by completing the action, then it works
    p = client.patch("/actions/act-t4", json={"status": "executed",
                                              "real_interaction": {"kind": "voice", "to": "+34600000005"}})
    assert p.status_code == 200
    r3 = act(client, "act-t6", "bomberos-torrent", "rescue",
             zones=["catarroja"], params={"units": 1})
    assert r3.status_code == 201


def test_idempotency_replay(client):
    r1 = act(client, "act-t7", "guardia-civil-trafico", "close_road",
             zones=["alfafar"], key="idem-1")
    assert r1.status_code == 201
    r2 = act(client, "act-t8", "guardia-civil-trafico", "close_road",
             zones=["alfafar"], key="idem-1")
    assert r2.status_code == 201 and r2.json().get("idempotent_replay")
    assert r2.json()["action"]["id"] == "act-t7"


def test_high_cost_requires_approval(client):
    r = act(client, "act-t9", "ume", "rescue", params={"units": 2})
    assert r.status_code == 201
    assert r.json()["action"]["status"] == "pending_approval"
    g = client.post("/actions/act-t9/approve")
    assert g.status_code == 200 and g.json()["action"]["status"] == "approved"


def test_reject_releases_units(client):
    before = client.get("/entities/ume").json()["units"]["available"]
    r = act(client, "act-t10", "ume", "heavy_equipment", params={"units": 1})
    assert r.json()["action"]["status"] == "pending_approval"
    client.post("/actions/act-t10/reject")
    after = client.get("/entities/ume").json()["units"]["available"]
    assert after == before


def test_corroboration_distinct_channels_only(client):
    # times at/after the run's newest signal, or the stale rule kicks in
    z = "chiva"
    r1 = sig(client, "sig-c1", "social-media", "low", 6, zone=z, t="2024-10-29T18:46:00+01:00")
    assert r1.json()["confidence"] == "low"
    r2 = sig(client, "sig-c2", "social-media", "low", 6, zone=z, t="2024-10-29T18:48:00+01:00")
    assert r2.json()["confidence"] == "low"  # same channel: no self-corroboration
    r3 = sig(client, "sig-c3", "112-calls", "medium", 7, zone=z, t="2024-10-29T18:52:00+01:00")
    assert r3.json()["confidence"] == "high"  # distinct channel corroborates


def test_tripwire_fires_synchronously(client):
    r = act(client, "act-t11", "system", "set_tripwire", params={"tripwire": {
        "id": "tw-test", "if": {"source": "chj-gauges", "min_severity": 7},
        "then": [{"actor": "emergency-coordinator", "verb": "activate_emergency_level"}],
        "reason": "test reflex"}})
    assert r.status_code == 201
    t0 = time.monotonic()
    rs = sig(client, "sig-c4", "chj-gauges", "high", 9, zone="chiva",
             t="2024-10-29T17:30:00+01:00")
    dt = time.monotonic() - t0
    assert rs.json()["tripwires_fired"] == ["tw-test"]
    assert dt < 2.0  # synchronous, includes network + several queries


def test_register_entity_restrictions(client):
    r = act(client, "act-t12", "system", "register_entity", params={"entity": {
        "id": "tractores-catarroja", "name": "Voluntarios con tractores",
        "kind": "responder", "weight": 2, "trust": "high",  # trust must be forced low
        "capabilities": ["rescue", "supplies"],  # rescue must be stripped
        "status": "available", "provenance": "plan"}})
    assert r.status_code == 201
    e = client.get("/entities/tractores-catarroja").json()
    assert e["trust"] == "low" and e["provenance"] == "discovered"
    assert e["capabilities"] == ["supplies"]


def test_unreachable_actor_suggests_escalation(client):
    client.post("/world/patches", json={"entity": "mayor-paiporta",
                                        "set": {"status": "unreachable"}})
    r = act(client, "act-t13", "mayor-paiporta", "order_evacuation", zones=["paiporta"])
    assert r.status_code == 409 and "emergency-coordinator" in r.text


def test_duplicate_action_guard(client):
    r1 = act(client, "act-t20", "guardia-civil-trafico", "close_road", zones=["catarroja"])
    assert r1.status_code == 201
    r2 = act(client, "act-t21", "guardia-civil-trafico", "close_road", zones=["catarroja"])
    assert r2.status_code == 409 and "duplicate" in r2.text and "act-t20" in r2.text


def test_executor_stubs_approved_actions(client):
    r = act(client, "act-t22", "cruz-roja", "shelter", zones=[], params={"units": 1})
    assert r.status_code == 201 and r.json()["action"]["status"] == "approved"
    deadline = time.monotonic() + 15
    status = None
    while time.monotonic() < deadline:
        acts = client.get("/actions?limit=50").json()["actions"]
        a = next(x for x in acts if x["id"] == "act-t22")
        status = a["status"]
        if status != "approved":
            break
        time.sleep(2)
    assert status == "in_progress"  # unit verb: executing, units held
    assert a["real_interaction"]["stubbed"] is True


def test_responder_mutual_aid_allowed(client):
    # bomberos-torrent home area excludes chiva; rescue there must be
    # allowed (mutual aid) and tagged out_of_area
    r = act(client, "act-t23", "bomberos-torrent", "rescue",
            zones=["chiva"], params={"units": 1})
    assert r.status_code == 201, r.text
    assert r.json()["action"]["out_of_area"] is True
