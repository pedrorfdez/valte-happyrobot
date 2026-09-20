"""Declaring a crisis from one free-text description: what the local reader understands, what it admits it
assumed, and that the draft goes straight into POST /crises."""

import pytest
from fastapi.testclient import TestClient

from valte.core.declare import normalize, parse_local

FIRE = ("Incendio forestal en la Sierra Calderona. Empezó en Serra (3.300 habitantes) y el viento lo empuja hacia el sur: "
        "de Serra a Náquera en 40 minutos y de Náquera a Bétera en 1 hora. Náquera tiene 7.500 habitantes y Bétera 26 mil "
        "habitantes. Tenemos 8 autobombas, 3 helicópteros y 300 mantas. Fuentes: AEMET, el 112 y redes sociales.")


@pytest.fixture(scope="module")
def client():
    from valte.main import app

    with TestClient(app) as c:
        yield c


def test_local_reader_gets_zones_graph_stock_and_sources():
    d = normalize(parse_local(FIRE), FIRE)
    spec = d["spec"]
    assert spec["hazard_type"] == "fire" and spec["name"] == "Incendio forestal en la Sierra Calderona"
    zones = {z["name"]: z for z in spec["zones"]}
    assert {n: z["population"] for n, z in zones.items()} == {"Serra": 3300, "Náquera": 7500, "Bétera": 26000}
    assert zones["Serra"]["is_origin"] and not zones["Bétera"]["is_origin"]
    assert zones["Serra"]["to"] == [{"name": "Náquera", "delay_min": 40}]
    assert zones["Náquera"]["to"] == [{"name": "Bétera", "delay_min": 60}]
    assert {(r["name"], r["qty"]) for r in spec["resources"]} == {("Autobombas", 8), ("Helicópteros", 3), ("Mantas", 300)}
    assert {s["name"]: s["trust"] for s in spec["sources"]} == {"AEMET": "high", "112": "high", "Redes sociales": "low"}
    assert not d["blocking"] and not d["missing"]


def test_local_reader_copes_with_the_way_dictation_writes():
    """Whisper writes some numbers as words, drops the brackets and starts sentences with "De"."""
    text = ("Incendio forestal en la Sierra Calderona. Empezó en Serra, que tiene tres mil trescientos habitantes, y el viento lo "
            "empuja hacia el sur. De Serra a Náquera tardará 40 minutos y de Náquera a Bétera una hora. Náquera tiene 7.500 "
            "habitantes y Bétera 26.000. Tenemos ocho autobombas, tres helicópteros y 300 mantas. Hay un hospital cerca.")
    spec = normalize(parse_local(text), text)["spec"]
    assert [(z["name"], z["population"]) for z in spec["zones"]] == [("Serra", 3300), ("Náquera", 7500), ("Bétera", 26000)]
    assert spec["zones"][1]["to"] == [{"name": "Bétera", "delay_min": 60}]
    assert {(r["name"], r["qty"]) for r in spec["resources"]} == {("Autobombas", 8), ("Helicópteros", 3), ("Mantas", 300)}  # "un hospital" is not stock


def test_what_nobody_said_is_assumed_out_loud_or_asked_for():
    text = "apagón general, afecta a Ruzafa, Benimaclet y Campanar"
    d = normalize(parse_local(text), text)
    zones = d["spec"]["zones"]
    assert [z["name"] for z in zones] == ["Ruzafa", "Benimaclet", "Campanar"] and d["spec"]["hazard_type"] == "blackout"
    assert zones[0]["is_origin"] and zones[0]["to"] == [{"name": "Benimaclet", "delay_min": 30}]
    assert len(d["assumptions"]) == 3  # the order, the origin, the usual sources
    assert any("habitantes" in m for m in d["missing"]) and any("recursos" in m for m in d["missing"])

    nowhere = normalize(parse_local("se ha ido la luz y no sabemos nada más"), "")
    assert nowhere["blocking"] and "zonas" in nowhere["missing"][0]


def test_an_official_plan_is_recognised_and_used_whole():
    text = "Riada: el barranco del Poyo baja desbordado desde Chiva hacia Paiporta y Massanassa"
    d = normalize(parse_local(text), text)
    assert d["spec"]["pack"] == "riada-paiporta" and len(d["spec"]["zones"]) == 6
    assert "plan oficial" in d["assumptions"][0]


def test_a_reader_that_names_a_destination_only_still_gets_a_zone():
    d = normalize({"name": "Fuga de gas", "hazard_type": "infra", "zones": [
        {"name": "Polígono Fuente del Jarro", "population": "1.200", "is_origin": True, "to": [{"name": "Paterna", "delay_min": 15}]}]}, "")
    assert [z["name"] for z in d["spec"]["zones"]] == ["Polígono Fuente del Jarro", "Paterna"]
    assert d["spec"]["zones"][0]["population"] == 1200


def test_draft_then_create_over_http(client):
    assert client.post("/crises/draft", json={"text": "hola"}).status_code == 422
    r = client.post("/crises/draft", json={"text": FIRE})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["parsed_by"] == "local" and not d["blocking"]
    spec = d["spec"]
    r = client.post("/crises", json={"name": spec["name"], "region": spec["region"], "scenario": spec["hazard_type"], "pack": spec["pack"],
                                     "zones": spec["zones"], "sources": spec["sources"], "resources": spec["resources"],
                                     "transcript": FIRE, "source": "text", "start": False})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    zones = {z["id"]: z for z in client.get(f"/crises/{cid}/zones").json()["zones"]}
    assert set(zones) == {"serra", "naquera", "betera"}
    state = client.get(f"/state?crisis_id={cid}", headers={"Authorization": "Bearer test-secret"}).json()
    assert state["crisis"]["declared_by_human_as"].startswith("Incendio forestal")
    assert [e["to"] for z in state["zones"] if z["id"] == "serra" for e in z["downstream"]] == ["naquera"]


def test_dictation_says_whether_it_is_installed(client):
    r = client.get("/stt")
    assert r.status_code == 200 and set(r.json()) >= {"available", "ready", "model"}
    assert client.post("/stt", content=b"").status_code in (422, 501)


def test_the_outside_world_can_be_asked_for_a_flood_or_a_fire_on_any_crisis(client):
    """The feeder app is told a crisis code and a kind of world: the script is of that kind, over that crisis's zones."""
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False, "external_feed": True}).json()["id"]
    own = client.get(f"/crises/{cid}/timeline").json()
    assert client.get(f"/crises/{cid}/timeline?hazard=flood").json() == own and len(own) == 36  # the hand-written flood
    fire = client.get(f"/crises/{cid}/timeline?hazard=fire").json()
    zones = {z["id"] for z in client.get(f"/crises/{cid}/zones").json()["zones"]}
    assert fire != own and "incendio forestal" in str(fire[0]["payload"]).lower()
    assert {i["fallback"]["zone"] for i in fire if (i.get("fallback") or {}).get("zone")} <= zones
    assert {c["hazard_type"] for i in fire for c in (i.get("fallback") or {}).get("claims", [])} == {"wildfire"}
    assert client.get(f"/crises/{cid}/timeline?hazard=fire").json() == fire  # stable for a feeder that re-attaches
    assert client.get(f"/crises/{cid}/timeline?hazard=volcano").status_code == 422
    client.post(f"/crises/{cid}/start")
    r = client.post(f"/crises/{cid}/inputs", json={"channel": "sensor", "source": "sensores", "zone": "chiva", "severity": 6,
                                                  "content": "Columna de humo detectada", "hazard": "wildfire"})
    assert r.status_code == 201
    sig = next(s["signal"] for s in client.get(f"/crises/{cid}/signals").json()["signals"] if s["signal"]["id"] == r.json()["id"])
    assert sig["claims"] == [{"hazard_type": "wildfire", "severity_hint": 6}]


CAMPING = ("Incendio forestal en la Sierra Calderona. Empezó en Serra (3.300 habitantes) y el viento de poniente lo empuja hacia el sur: "
           "de Serra a Náquera en 40 minutos y de Náquera a Bétera en 1 hora. Náquera tiene 7.500 habitantes y Bétera 26.000 habitantes. "
           "Hay 30 personas atrapadas en el camping de Serra. Tenemos 8 autobombas.")


def test_the_description_says_what_is_already_happening_and_the_risk_per_zone_follows():
    d = normalize(parse_local(CAMPING), CAMPING)
    facts = d["spec"]["reports"]
    assert [(f["zone"], f["severity"], f["place"], f["people"]) for f in facts] == [("Serra", 7, "", 0), ("Serra", 9, "camping de Serra", 30)]
    risk = {r["zone"]: r for r in d["risk"]}
    assert risk["Serra"]["label"] == "9/10 ahora" and risk["Serra"]["level"] == "critical"
    assert (risk["Náquera"]["eta_min"], risk["Náquera"]["from"]) == (40, "Serra") and risk["Bétera"]["eta_min"] == 100
    assert risk["Bétera"]["label"] == "llega en ~100 min desde Náquera" and risk["Bétera"]["people_at_stake"] == 26000

    vague = "apagón general, afecta a Ruzafa, Benimaclet y Campanar"  # no word on how bad: a declared crisis still starts somewhere
    d = normalize(parse_local(vague), vague)
    assert [(f["zone"], f["severity"]) for f in d["spec"]["reports"]] == [("Ruzafa", 6)]
    assert [r["eta_min"] for r in d["risk"]] == [0, 30, 60]


def test_a_crisis_opens_with_what_was_declared_and_later_data_corrects_it(client):
    import time

    from sqlalchemy import select

    from valte.core import signals as core_signals
    from valte.db import session_scope
    from valte.engine import loop
    from valte.models import Action, Crisis, Incident, Signal, Zone

    spec = client.post("/crises/draft", json={"text": CAMPING}).json()["spec"]
    cid = client.post("/crises", json={"name": spec["name"], "region": spec["region"], "scenario": spec["hazard_type"], "zones": spec["zones"],
                                       "sources": spec["sources"], "resources": spec["resources"], "reports": spec["reports"],
                                       "transcript": CAMPING, "source": "text", "external_feed": True, "start": True}).json()["id"]
    with session_scope() as db:  # before any call or sensor: the declaration itself is data
        c = db.get(Crisis, cid)
        said = list(db.scalars(select(Signal).where(Signal.crisis_id == cid).order_by(Signal.seq)))
        assert [(s.source, s.channel, s.zone_id, s.severity_hint) for s in said] == [("cecopi", "operator", "serra", 7), ("cecopi", "operator", "serra", 9)]
        zones = {z.id: z for z in db.scalars(select(Zone).where(Zone.crisis_id == cid))}
        assert zones["serra"].severity_est == 9 and zones["naquera"].eta_min == 40 and zones["betera"].eta_min == 100 and c.severity == 9
        kinds = {i.kind: i for i in db.scalars(select(Incident).where(Incident.crisis_id == cid))}
        assert kinds["people"].people == 30 and kinds["people"].place == "camping de Serra" and kinds["people"].state == "attended"
        [rescue] = db.scalars(select(Action).where(Action.crisis_id == cid, Action.verb == "rescue"))  # the reflex did not wait for a brain
        assert rescue.origin == "tripwire" and rescue.incident_id == kinds["people"].id
    time.sleep(2.2)  # the brains wake once the burst of the declaration settles
    loop.tick(cid)
    with session_scope() as db:
        verbs = {a.verb for a in db.scalars(select(Action).where(Action.crisis_id == cid, Action.origin == "local-brain"))}
        assert "send_es_alert" in verbs  # first measures downstream, from the declaration alone
        c = db.get(Crisis, cid)
        core_signals.ingest_perception(db, c, {"id": "tel-1", "source": "sensores", "channel": "sensor", "zone": "naquera", "precision": "zone",
                                               "is_noise": "false", "content": "frente de llamas a 200 m de las primeras casas",
                                               "claims": '[{"hazard_type":"fire","severity_hint":8}]'})
        zones = {z.id: z for z in db.scalars(select(Zone).where(Zone.crisis_id == cid))}
        assert zones["naquera"].severity_est >= 6 and zones["naquera"].eta_min == 0 and zones["betera"].eta_min == 60  # telemetry moved the clock
