"""HTTP surface: the wizard's own payload shape, callback auth, the
query-string style HappyRobot uses, and the approval link in emails."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from valte.db import session_scope
from valte.models import Contact

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture(scope="module")
def client():
    from valte.main import app

    with TestClient(app) as c:
        yield c


def test_wizard_payload_as_the_design_sends_it(client):
    r = client.post("/crises", json={
        "name": "Incendio en la Calderona", "region": "Camp de Túria", "scenario": "fire", "start": False,
        "zones": [{"name": "Serra", "hab": "3 300", "origin": "true", "to": ["Náquera · 40 min"]},
                  {"name": "Náquera", "hab": "7 100", "origin": "false", "to": []}],
        "sources": [{"name": "Torre de vigilancia", "desc": "Cámara térmica", "link": "https://example.org", "trust": "high"}],
        "resources": [{"name": "Autobombas", "qty": "12", "unit": "ud."}]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["hazard"] == "fire" and r.json()["code"]

    zones = {z["id"]: z for z in client.get(f"/crises/{cid}/zones").json()["zones"]}
    assert zones["serra"]["population"] == 3300 and zones["serra"]["is_origin"]
    assert zones["serra"]["to"] == [{"zone": "naquera", "name": "Náquera", "d": "+40 min", "delay_min": 40}]
    assert zones["naquera"]["from"][0]["zone"] == "serra"

    ents = {e["id"]: e for e in client.get(f"/crises/{cid}/entities").json()}
    assert ents["torre-de-vigilancia"]["kind"] == "information_source" and ents["torre-de-vigilancia"]["trust"] == "high"
    assert "ayto-serra" in ents and "cecopi" in ents  # a crisis needs someone to notify
    assert client.get(f"/crises/{cid}/resources").json()["supplies"][0]["total"] == 12

    roles = {x["role"] for x in client.get(f"/crises/{cid}").json()["roles"]}
    assert roles == {"coordination", "authority", "responder"}


def test_callbacks_need_the_bearer_and_accept_query_strings(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    assert client.get(f"/state?crisis_id={cid}").status_code == 401
    assert client.post(f"/perceptions?crisis_id={cid}", headers={"Authorization": "Bearer nope"}).status_code == 401

    r = client.post("/perceptions", headers=AUTH, params={
        "crisis_id": cid, "id": "q1", "channel": "call", "source": "112", "zone": "Paiporta", "precision": "street",
        "is_noise": "false", "claims": '[{"hazard_type":"flood","severity_hint":8}]', "summary": "test"})
    assert r.status_code == 200 and r.json() == {"id": "q1", "noise": False, "confidence": "high"}

    # decisions as one JSON document in the raw body, envelope in the query: what PedroD-coordinator sends
    r = client.post(f"/decisions?crisis_id={cid}&dispatch_id=d1", headers=AUTH, json={"decisions_json":
        '{"actions":[{"actor":"bomberos-vlc","verb":"rescue","target_zones":["paiporta"],"params":{"units":2},'
        '"evidence":["q1"],"reasoning":"Personas atrapadas."},{"actor":"policia-local-paiporta","verb":"close_road",'
        '"target_zones":["paiporta"],"evidence":["q1"],"reasoning":"Cerrar el acceso."}],"situation_note":"nota","emergency_level":1}'})
    # the triage reflex already sent a crew to q1 when it arrived: the brain's copy is refused, its new idea is not
    assert (r.json()["accepted"], r.json()["rejected"]) == (1, 1)
    assert client.get(f"/crises/{cid}").json()["situation_note"] == "nota"

    snap = client.get(f"/api/snapshot?run_id={cid}", headers=AUTH).json()
    assert snap["run"]["run_id"] == cid and len(snap["zone_catalog"]) == 6


def test_email_approval_link_shows_a_button_and_only_post_decides(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    client.post("/perceptions", headers=AUTH, params={"crisis_id": cid, "id": "e1", "channel": "sensor", "source": "chj-gauges",
                "zone": "chiva", "precision": "exact", "claims": '[{"hazard_type":"flood","severity_hint":8}]'})
    r = client.post(f"/decisions?crisis_id={cid}", headers=AUTH, json={"actions": [
        {"actor": "cecopi", "verb": "request_ume", "target_zones": [], "evidence": ["e1"], "reasoning": "180 min de activación."}]})
    action_id = r.json()["results"][0]["id"]
    with session_scope() as db:
        token = db.scalars(select(Contact).where(Contact.crisis_id == cid, Contact.action_id == action_id)).one().token

    page = client.get(f"/a/{token}?d=approve")
    assert page.status_code == 200 and "Aprobar" in page.text and "<form" in page.text
    pending = client.get(f"/crises/{cid}/actions?status=pending_approval").json()["pending"]
    assert [a["action"]["id"] for a in pending] == [action_id]  # a prefetching mail scanner decides nothing

    assert "Registrado" in client.post(f"/a/{token}", data={"d": "approve"}).text
    log = client.get(f"/crises/{cid}/actions").json()["log"]
    act = next(a["action"] for a in log if a["action"]["id"] == action_id)
    assert act["status"] == "executed" and act["approval"]["via"] == "email"
    assert "Ya estaba decidido" in client.post(f"/a/{token}", data={"d": "reject"}).text
    assert client.get("/a/nope").status_code == 200 and "no válido" in client.get("/a/nope").text


def test_inventories_belong_to_their_owner_and_only_cecopi_sees_them_all(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    res = lambda who=None: client.get(f"/crises/{cid}/resources", params={"entity_id": who} if who else None).json()
    names = lambda r: {u["id"] for u in r["units"]}

    everything = res("cecopi")
    assert {"bomberos-vlc", "guardia-civil-chiva", "samu"} <= names(everything) and everything["scope"]["all"]
    assert names(res()) == names(everything)  # no viewer = the coordination view

    fire = res("bomberos-vlc")
    assert names(fire) == {"bomberos-vlc"} and fire["totals"] == {"available": 40, "total": 40}
    assert {s["id"] for s in fire["supplies"]} == {"bombas-achique", "embarcaciones"}

    gc = res("guardia-civil-chiva")  # a Guardia Civil post never learns how many firefighters are left
    assert names(gc) == {"guardia-civil-chiva"} and gc["supplies"] == [] and gc["requested"] == []
    assert res("alcaldia-paiporta")["units"] == []  # an authority has no units of its own

    kpi = lambda who: client.get(f"/crises/{cid}", params={"entity_id": who}).json()["kpis"]["units"]
    assert kpi("guardia-civil-chiva") == {"available": 8, "total": 8, "label": "unidades propias libres"}
    assert kpi("cruz-roja")["total"] == 10 and kpi("cecopi")["total"] > 40
    assert kpi("alcaldia-paiporta")["label"] == "sin recursos propios"

    seen = {e["id"]: e for e in client.get(f"/crises/{cid}/entities", params={"entity_id": "guardia-civil-chiva"}).json()}
    assert "units" in seen["guardia-civil-chiva"] and "units" not in seen["bomberos-vlc"]
    assert "units" in {e["id"]: e for e in client.get(f"/crises/{cid}/entities").json()}["bomberos-vlc"]

    panel = client.get(f"/crises/{cid}/overview", params={"role": "responder", "entity_id": "samu"}).json()
    assert [s["id"] for s in panel["supplies"]] == ["medicamentos"] and panel["kpis"]["units"]["total"] == 8


def test_only_the_owner_spends_a_resource_and_a_shelter_belongs_to_whoever_opens_it(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    client.post("/perceptions", headers=AUTH, params={"crisis_id": cid, "id": "o1", "channel": "call", "source": "112",
                "zone": "paiporta", "precision": "street", "claims": '[{"hazard_type":"flood","severity_hint":8}]'})
    decide = lambda *acts: client.post(f"/decisions?crisis_id={cid}", headers=AUTH, json={"actions": list(acts)}).json()["results"]

    not_yours, yours = decide(
        {"actor": "cruz-roja", "verb": "supplies", "target_zones": ["paiporta"], "params": {"resource": "medicamentos", "qty": 50}, "evidence": ["o1"]},
        {"actor": "cruz-roja", "verb": "supplies", "target_zones": ["paiporta"], "params": {"resource": "mantas", "qty": 200}, "evidence": ["o1"]})
    assert "belongs to samu" in not_yours["error"] and yours["status"] == "executed"
    mantas = next(s for s in client.get(f"/crises/{cid}/resources").json()["supplies"] if s["id"] == "mantas")
    assert mantas["available"] == 600 and mantas["owner_name"] == "Cruz Roja"

    client.post(f"/crises/{cid}/actions", json={"actor": "alcaldia-paiporta", "verb": "open_shelter", "target_zones": ["paiporta"],
                                                "params": {"capacity": 300}, "by": "alcaldia-paiporta"})
    mine = client.get(f"/crises/{cid}/resources", params={"entity_id": "alcaldia-paiporta"}).json()["supplies"]
    assert [(s["name"], s["total"]) for s in mine] == [("Plazas de albergue", 300)]
    assert client.get(f"/crises/{cid}/resources", params={"entity_id": "ayto-chiva"}).json()["supplies"] == []
    assert client.get(f"/crises/{cid}", params={"entity_id": "alcaldia-paiporta"}).json()["kpis"]["units"] == \
        {"available": 300, "total": 300, "label": "plazas de albergue"}

    assert decide({"actor": "cruz-roja", "verb": "shelter", "target_zones": ["paiporta"], "params": {"people": 50}, "evidence": ["o1"]})[0]["status"] == "executed"
    assert client.get(f"/crises/{cid}/resources", params={"entity_id": "alcaldia-paiporta"}).json()["supplies"][0]["available"] == 250


def test_contacts_are_entities_and_every_communication_hangs_from_one(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    d = client.get(f"/crises/{cid}/directory").json()
    ids = [e["id"] for e in d["contacts"]]
    assert "alcaldia-paiporta" in ids and "bomberos-vlc" in ids
    assert "cecopi" not in ids and "112" not in ids and "vecinos-paiporta" not in ids  # us, sources, population: no way in
    assert client.get(f"/crises/{cid}").json()["kpis"]["contacts"]["entities"] == len(ids)

    r = client.post(f"/crises/{cid}/entities/cruz-roja/contact", json={"message": "Preparad 200 mantas.", "by": "operador"})
    assert r.status_code == 201 and r.json()["action_id"] is None and r.json()["brief"]["ask"] == "Preparad 200 mantas."
    assert client.post(f"/crises/{cid}/entities/cecopi/contact", json={"message": "x"}).status_code == 409
    assert client.post(f"/crises/{cid}/entities/nope/contact", json={"message": "x"}).status_code == 404

    cruz = next(e for e in client.get(f"/crises/{cid}/directory").json()["contacts"] if e["id"] == "cruz-roja")
    assert cruz["comms"]["total"] == 1 and cruz["communications"][0]["purpose"] == "notify"
    assert cruz["channel"]["kind"] == "email" and cruz["escalates_to_name"] == "Delegación del Gobierno"


def test_a_wizard_crisis_gets_a_script_about_its_own_hazard_and_zones(client):
    cid = client.post("/crises", json={
        "name": "Incendio en la Calderona", "region": "Camp de Túria", "scenario": "fire", "start": False,
        "zones": [{"name": "Serra", "hab": "3 300", "origin": "true", "to": ["Náquera · 40 min"]},
                  {"name": "Náquera", "hab": "7 100", "to": ["Bétera · 25 min"]}, {"name": "Bétera", "hab": "26 000"}],
        "resources": [{"name": "Autobombas", "qty": "12"}]}).json()["id"]
    script = client.get(f"/crises/{cid}/timeline").json()
    assert script == client.get(f"/crises/{cid}/timeline").json()  # stable: a re-attached feeder resends nothing new
    text = " ".join(str(i.get("payload") or i.get("content") or i.get("note")) for i in script).lower()
    assert "fuego" in text or "incendio" in text
    assert "barranco" not in text and "paiporta" not in text  # nothing borrowed from the flood pack
    zones = {i.get("zone") or (i.get("fallback") or {}).get("zone") for i in script} - {None, ""}
    assert zones == {"serra", "naquera", "betera"}
    arrive = {z: min(i["at_min"] for i in script if i.get("channel") == "call" and (i.get("fallback") or {}).get("zone") == z)
              for z in ("naquera", "betera")}
    assert arrive["betera"] - arrive["naquera"] == 25  # the hazard follows the delays the user drew
    assert {i["op"] for i in script if i["kind"] == "world"} >= {"source_silent", "road_cut", "resource_loss"}
    assert any((i.get("fallback") or {}).get("is_noise") for i in script)
    ents = {e["id"] for e in client.get(f"/crises/{cid}/entities").json()}
    assert {"112", "sensores", "social-media"} <= ents  # someone has to be able to tell the crisis things


def test_the_flood_pack_keeps_its_hand_written_script(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    script = client.get(f"/crises/{cid}/timeline").json()
    assert len(script) == 36 and "Mestre Serrano" in str(script)


def test_from_outside_only_callbacks_and_approval_links_are_reachable(client, monkeypatch):
    from valte.settings import settings

    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    outside = {"X-Forwarded-For": "203.0.113.7", "Host": "abc123.lhr.life"}  # what a request through the tunnel looks like

    assert client.get("/crises", headers=outside).status_code == 403
    assert client.get(f"/crises/{cid}", headers=outside).status_code == 403
    assert client.post(f"/crises/{cid}/sim/inject", headers=outside, json={"kind": "road_cut", "zone": "paiporta"}).status_code == 403
    assert client.get("/meta", headers=outside).status_code == 403 and client.get("/docs", headers=outside).status_code == 403

    # HappyRobot still gets through (and still needs its bearer), and so do the links sent by email
    assert client.get(f"/state?crisis_id={cid}", headers=outside).status_code == 401
    assert client.get(f"/state?crisis_id={cid}", headers={**outside, **AUTH}).status_code == 200
    assert client.get("/a/nope", headers=outside).status_code == 200
    assert client.get("/health", headers=outside).status_code == 200

    # a spoofed Host is not enough: the proxy header gives it away
    assert client.get("/crises", headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 403

    monkeypatch.setattr(settings, "valte_dashboard_token", "demo-key")
    assert client.get("/crises", headers=outside).status_code == 403
    assert client.get("/crises?key=demo-key", headers=outside).status_code == 200
    assert client.get("/crises", headers={**outside, "X-Valte-Key": "demo-key"}).status_code == 200
    assert client.get("/crises").status_code == 200  # this machine never needs it


def test_pack_zones_come_with_their_place_on_the_map(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
    zones = {z["id"]: z for z in client.get(f"/crises/{cid}/zones").json()["zones"]}
    assert zones["paiporta"]["centroid"] == {"lat": 39.4278, "lng": -0.4172}
    assert all(z["centroid"] for z in zones.values())
    assert client.post(f"/crises/{cid}/locate").json() == {"locating": []}  # nothing left to find
