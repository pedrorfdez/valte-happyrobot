"""One or several signals make an incident: what the supervisor sees, what the brains prioritise and what the
reflexes serve. Reposts are not witnesses, a second call about the same place is not a second job."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from valte.core import actions, incidents, needs, signals, world
from valte.db import session_scope
from valte.engine import loop
from valte.models import Action, Crisis, Entity, Incident, Signal


@pytest.fixture(scope="module")
def client():
    from valte.main import app

    with TestClient(app) as c:
        yield c


def _report(db, c, sid, zone, sev, text, where="", source="112", channel="call", precision=None):
    signals.ingest_perception(db, c, {
        "id": sid, "source": source, "channel": channel, "zone": zone, "content": text, "location_text": where,
        "precision": precision or ("street" if where else "zone"), "is_noise": "false",
        "claims": '[{"hazard_type":"flood","severity_hint":%d}]' % sev})
    return db.get(Signal, (c.id, sid))


def _open(db, cid, kind=None):
    rows = [i for i in db.scalars(select(Incident).where(Incident.crisis_id == cid, Incident.origin == "kernel").order_by(Incident.seq))]
    return [i for i in rows if kind is None or i.kind == kind]


def test_calls_about_the_same_place_are_one_incident_served_once(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        a = _report(db, c, "c1", "paiporta", 9, "Hay ancianos atrapados en la residencia, el agua sube", "Residencia Virgen del Carmen, calle Mayor 12")
        b = _report(db, c, "c2", "paiporta", 8, "Mi madre está en la residencia de la calle Mayor y no pueden salir", "residencia de la calle Mayor")
        _report(db, c, "c3", "paiporta", 9, "50 personas en la residencia Virgen del Carmen sin poder salir", "Residencia Virgen del Carmen")
        [inc] = _open(db, crisis_id, "people")
        assert a.incident_id == b.incident_id == inc.id and inc.signal_ids == ["c1", "c2", "c3"]
        assert inc.state == "attended" and inc.priority == "P0" and inc.confidence == "high" and len(inc.origins) == 3
        assert inc.people == 50 and inc.title.startswith("Personas en peligro · Residencia Virgen del Carmen")
        # three calls, one job: the standing reflex went once, and nothing waits
        rescues = list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "rescue")))
        assert [r.evidence for r in rescues] == [["c1"]] and rescues[0].incident_id == inc.id
        assert needs.open_needs(db, c) == []

        _report(db, c, "c4", "paiporta", 9, "Una familia subida al tejado", "camino de la Pascualeta 3")  # another place: another job
        assert len(_open(db, crisis_id, "people")) == 2
        assert len(list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "rescue")))) == 2


def test_reposts_are_not_witnesses(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        for i in range(5):
            _report(db, c, f"t{i}", "picanya", 9, "Dicen que hay gente atrapada en el puente viejo!!", "puente viejo",
                    source="social-media", channel="social")
        [inc] = _open(db, crisis_id, "people")
        assert inc.signal_ids == [f"t{i}" for i in range(5)] and inc.origins == ["social"]
        assert inc.state == "candidate" and inc.confidence == "low" and inc.priority == "P1"  # no top slot for one unverified voice
        assert db.get(Signal, (crisis_id, "t4")).confidence_inputs["independent_origins"] == 0
        [need] = needs.open_needs(db, c)
        assert need["incident_id"] == inc.id and need["suggested_verb"] == "wellness_check" and need["sources"] == 1

        _report(db, c, "t9", "picanya", 8, "Veo desde casa a dos personas atrapadas junto al puente viejo", "puente viejo")
        assert inc.state in ("active", "attended") and inc.confidence in ("medium", "high") and len(inc.origins) == 2


def test_an_incident_follows_whoever_is_on_it(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "w1", "massanassa", 7, "Agua entrando en los bajos de toda la calle", precision="zone")
        [inc] = _open(db, crisis_id)
        assert inc.kind == "hazard" and inc.state == "active" and inc.title == "Inundación · Massanassa"
        res = actions.propose_action(db, c, {"actor": "bomberos-vlc", "verb": "pump_water", "target_zones": ["massanassa"],
                                             "params": {"units": 1}, "evidence": [inc.id], "reasoning": "achique"}, origin="coordinator")
        act = db.get(Action, (crisis_id, res["id"]))
        assert act.incident_id == inc.id and inc.state == "attended"  # an incident id is evidence too
        act.status, iid = "failed", inc.id
    loop.tick(crisis_id)
    with session_scope() as db:
        assert db.get(Incident, (crisis_id, iid)).state == "active"  # whoever was on it failed: it is nobody's again


def test_dashboard_reads_incidents_not_signals(client):
    cid = client.post("/crises", json={"pack": "riada-paiporta", "start": True}).json()["id"]
    with session_scope() as db:
        c = db.get(Crisis, cid)
        _report(db, c, "d1", "paiporta", 9, "Personas atrapadas en el garaje del Mercadona", "garaje del Mercadona")
        _report(db, c, "d2", "paiporta", 8, "Gente atrapada en el parking del Mercadona de Paiporta", "parking Mercadona")
        _report(db, c, "d3", "chiva", 7, "Bulo: dicen que ha reventado la presa", "", source="social-media", channel="social")
        signals.ingest_perception(db, c, {"id": "d4", "source": "social-media", "channel": "social", "is_noise": "true", "content": "qué tarde más fea"})
    body = client.get(f"/crises/{cid}/incidents").json()
    assert body["counts"]["open"] == 2 and body["counts"]["candidate"] == 1 and body["counts"]["noise"] == 1
    assert body["incidents"][0]["state"] == "candidate"  # what nobody is on goes first
    first = next(i for i in body["incidents"] if i["kind"] == "people")
    assert first["kindLabel"] == "Personas en peligro" and first["evidenceLabel"] == "2 avisos · 2 fuentes" and first["attendedBy"]
    assert [s["signal"]["id"] for s in body["noise"]] == ["d4"]
    detail = client.get(f"/crises/{cid}/incidents/{first['id']}").json()
    assert [s["signal"]["id"] for s in detail["signal_list"]] == ["d1", "d2"] and detail["action_list"][0]["action"]["verb"] == "rescue"

    overview = client.get(f"/crises/{cid}/overview").json()
    assert {i["id"] for i in overview["incidents"]} == {i["id"] for i in body["incidents"]}
    assert overview["kpis"]["incidents"]["open"] == 2

    rumour = next(i for i in body["incidents"] if i["state"] == "candidate")
    gone = client.post(f"/crises/{cid}/incidents/{rumour['id']}/dismiss", json={"by": "cecopi", "reason": "la CHJ confirma que la presa está bien"}).json()
    assert gone["state"] == "dismissed" and "presa" in gone["closed_reason"]
    assert client.post(f"/crises/{cid}/incidents/{rumour['id']}/dismiss", json={}).status_code == 409
    assert client.get(f"/crises/{cid}/incidents?state=open").json()["counts"]["open"] == 1

    state = client.get(f"/state?crisis_id={cid}", headers={"Authorization": "Bearer test-secret"}).json()
    [seen] = [i for i in state["situation"]["incidents"] if i["kind"] == "people"]
    assert seen["incident_id"] == first["id"] and seen["signal_ids"] == ["d1", "d2"] and seen["attended_by"]


def test_the_strategist_prioritises_and_merges_but_does_not_own_them(crisis_id):
    from valte.core import plan

    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "m1", "cheste", 7, "El puente de la CV-50 está hundido", "puente CV-50")
        _report(db, c, "m2", "cheste", 7, "No se puede pasar por la carretera de Chiva, se ha caído un trozo", "carretera de Chiva")
        one, two = _open(db, crisis_id, "road")
        plan.replace_plan(db, c, {"merge": [[one.id, two.id]], "incidents": [
            {"incident_id": one.id, "priority": "P0", "summary": "Corta el único acceso de los bomberos a Cheste"}],
            "plan": {"summary": "x", "objectives": []}})
        assert two.state == "merged" and two.canonical_id == one.id and one.signal_ids == ["m1", "m2"]
        assert one.priority == "P0" and one.note.startswith("Corta el único acceso") and one.state == "active"
        plan.replace_plan(db, c, {"incidents": [], "plan": {"summary": "y", "objectives": []}})
        assert one.state == "active"  # leaving it out of a plan does not make it go away


def test_unrelated_reports_without_a_spot_do_not_hide_inside_each_other(crisis_id):
    """A crashed helicopter typed in from the outside-world app ended up as the third signal of a care-home incident:
    same zone, same kind, no spot on either. With no spot to compare, reports must share a distinctive word."""
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)

        def call(sid, sev, text, where="paiporta", label="medical"):
            signals.ingest_perception(db, c, {"id": sid, "source": "112", "channel": "call", "zone": "paiporta", "content": text,
                                              "location_text": where, "precision": "zone", "is_noise": "false",
                                              "claims": '[{"hazard_type":"%s","severity_hint":%d}]' % (label, sev)})
            return db.get(Signal, (crisis_id, sid))

        home = call("h1", 8, "Estamos en la residencia de mayores de Paiporta, el agua ha cortado la salida. Somos 50 personas.",
                    "la residencia de mayores de Paiporta")
        heli = call("h2", 6, "Se ha caido un helicoptero en paiporta")
        assert heli.incident_id != home.incident_id
        inc = db.get(Incident, (crisis_id, heli.incident_id))
        assert inc.kind == "accident" and inc.state == "active" and inc.title == "Accidente · Paiporta: Se ha caido un helicoptero en paiporta"
        assert any(n["incident_id"] == inc.id for n in needs.open_needs(db, c))  # nobody is on it: the brains are told
        again = call("h3", 6, "Un helicóptero se ha estampado cerca del polideportivo de Paiporta")
        assert again.incident_id == inc.id and len(inc.origins) == 2  # same thing, another witness
        more = call("h4", 8, "En la residencia de mayores siguen sin poder salir, el agua sube", "residencia de mayores")
        assert more.incident_id == home.incident_id


def test_going_to_look_is_not_dealing_with_it(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "k1", "picanya", 7, "Un camión cisterna volcado pierde combustible junto al colegio", precision="zone")
        inc = db.scalars(select(Incident).where(Incident.crisis_id == crisis_id, Incident.origin == "kernel")).one()
        res = actions.propose_action(db, c, {"actor": "policia-local-paiporta" if db.get(Entity, (crisis_id, "policia-local-picanya")) is None else "policia-local-picanya",
                                             "verb": "wellness_check", "target_zones": ["picanya"], "params": {"units": 1},
                                             "evidence": ["k1"], "reasoning": "comprobar"}, origin="human")
        if res.get("error"):  # no local police with jurisdiction there in this pack: any responder that can check
            who = next(e for e in world.entities_of(db, crisis_id) if "wellness_check" in (e.capabilities or []) and (not e.jurisdiction or "picanya" in e.jurisdiction))
            res = actions.propose_action(db, c, {"actor": who.id, "verb": "wellness_check", "target_zones": ["picanya"], "params": {"units": 1},
                                                 "evidence": ["k1"], "reasoning": "comprobar"}, origin="human")
        act = db.get(Action, (crisis_id, res["id"]))
        incidents.sync(db, c)
        assert inc.state == "attended"  # somebody is on the way to look
        act.reserved = {**(act.reserved or {}), "released": True}
        incidents.sync(db, c)
        assert world.action_state(act) == "done" and inc.state == "active"  # looked at, confirmed, still nobody's
        [need] = [n for n in needs.open_needs(db, c) if n["incident_id"] == inc.id]
        assert need["verified"] and need["suggested_verb"] == "rescue"


def test_what_looser_rules_lumped_together_is_untangled_once(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "g1", "paiporta", 6, "Se ha estampado un helicoptero en paiporta", precision="zone")
        heli = db.get(Incident, (crisis_id, db.get(Signal, (crisis_id, "g1")).incident_id))
        _report(db, c, "g2", "paiporta", 8, "Estamos en la residencia de mayores, el agua ha cortado la salida, somos 50 personas", precision="zone")
        _report(db, c, "g3", "paiporta", 6, "Se ha caido un helicoptero en paiporta", precision="zone")
        g2 = db.get(Signal, (crisis_id, "g2"))
        lumped = db.get(Incident, (crisis_id, g2.incident_id))
        # what the first rules did: everything in one "people in danger in Paiporta", closed by a finished check
        heli.kind, heli.signal_ids, heli.state, heli.closed_reason = "people", ["g1", "g2", "g3"], "resolved", "act-x completada(s)"
        g2.incident_id = heli.id
        db.delete(lumped)
        db.flush()

        changed = incidents.regroup(db, c)
        assert heli.kind == "accident" and heli.signal_ids == ["g1", "g3"] and heli.state == "active" and "helicoptero" in heli.title
        home = db.get(Incident, (crisis_id, g2.incident_id))
        assert home.id != heli.id and home.kind == "people" and home.people == 50 and {heli.id, home.id} <= {i.id for i in changed}
        assert incidents.regroup(db, c) == []  # nothing left to untangle
