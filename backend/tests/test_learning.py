"""Learning inside a crisis (what its own decisions ran into applies at once) and from one crisis to the next
(what it learned is what the next one starts with). A lesson cites evidence, and what leans on it says so."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from valte.core import actions, incidents, learning, outreach, signals, world
from valte.db import session_scope
from valte.models import Action, Contact, Crisis, Entity, Incident, Lesson, LessonUse, Signal

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.fixture(scope="module")
def client():
    from valte.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_lessons():
    with session_scope() as db:
        for row in [*db.scalars(select(Lesson)), *db.scalars(select(LessonUse))]:
            db.delete(row)


def _report(db, c, sid, zone, sev, text, where="", source="112", channel="call"):
    signals.ingest_perception(db, c, {"id": sid, "source": source, "channel": channel, "zone": zone, "content": text,
                                      "location_text": where, "precision": "street" if where else "zone", "is_noise": "false",
                                      "claims": '[{"hazard_type":"flood","severity_hint":%d}]' % sev})


def _evacuate(db, c, zone, evidence, actor=None, **extra):
    return actions.propose_action(db, c, {"actor": actor or f"alcaldia-{zone}", "verb": "order_evacuation", "target_zones": [zone],
                                          "params": {}, "evidence": evidence, "reasoning": "x", **extra}, origin="coordinator")


def test_whoever_does_not_answer_is_not_asked_again(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        mayor = db.get(Entity, (crisis_id, "alcaldia-paiporta"))
        _report(db, c, "e1", "paiporta", 7, "El agua entra en las casas de la calle Mayor")
        for _ in range(2):  # two approval requests ring out
            k = outreach.queue_contact(db, c, entity=mayor, purpose="approval")
            outreach.set_status(db, c, k, "no_answer", outcome={"note": "no descolgó"})
        [lesson] = learning.learn_now(db, c)
        assert lesson.kind == "entity_response" and lesson.scope == "crisis" and len(lesson.evidence) == 2
        assert lesson.rule == {"type": "route_around", "entity": mayor.id, "to": mayor.escalation_to} and "no ha contestado 2 de 2" in lesson.text
        assert learning.learn_now(db, c) == []  # nothing new: no second lesson, no noise

        res = _evacuate(db, c, "paiporta", ["e1"])
        act = db.get(Action, (crisis_id, res["id"]))
        assert act.approval["approver"] == mayor.escalation_to  # asked whoever does answer, without waiting for the ring to die
        [use] = db.scalars(select(LessonUse).where(LessonUse.crisis_id == crisis_id))
        assert use.by == "kernel" and use.ref == act.id and use.lesson_id == lesson.id
        assert world.build_state(db, c)["lessons"][0]["id"] == f"L-{lesson.id}"


def test_a_rejected_order_needs_new_evidence(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "r1", "picanya", 6, "Empieza a subir el agua por el barranco")
        act = db.get(Action, (crisis_id, _evacuate(db, c, "picanya", ["r1"], actor="ayto-picanya")["id"]))
        actions.reject_action(db, c, act, by=act.approval["approver"], reason="el barranco aún va por debajo del puente")
        [lesson] = learning.learn_now(db, c)
        assert lesson.kind == "rejection" and lesson.evidence == [act.id] and "por debajo del puente" in lesson.text

        again = _evacuate(db, c, "picanya", ["r1"], actor="ayto-picanya")
        assert "lesson L-" in again["error"] and "newer than the rejection" in again["error"]
        assert _evacuate(db, c, "paiporta", ["r1"])["id"]  # another town is another decision

        world.set_clock(db, c, paused=False)
        c.anchor_scenario = c.anchor_scenario.replace(minute=(c.anchor_scenario.minute + 5) % 60)
        _report(db, c, "r2", "picanya", 8, "El agua ya salta el puente y entra en la calle Major")
        assert _evacuate(db, c, "picanya", ["r1", "r2"], actor="ayto-picanya").get("id")  # something new behind it: admitted


def test_a_source_that_cries_wolf_is_believed_less_from_then_on(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        paper = db.get(Entity, (crisis_id, "levante-emv"))
        assert paper.trust == "medium"
        _report(db, c, "w1", "chiva", 7, "Última hora: revienta la presa de Forata", source="levante-emv", channel="news")
        _report(db, c, "w2", "torrent", 7, "Última hora: se hunde el puente del barranco de Torrent", "puente del barranco", source="levante-emv", channel="news")
        for inc in db.scalars(select(Incident).where(Incident.crisis_id == crisis_id, Incident.origin == "kernel")):
            incidents.dismiss(db, c, inc, by="cecopi", reason="la CHJ lo desmiente")
        [lesson] = [l for l in learning.learn_now(db, c) if l.kind == "source_reliability"]
        assert sorted(lesson.evidence) == sorted(i.id for i in db.scalars(select(Incident).where(Incident.crisis_id == crisis_id)))
        assert paper.trust == "low"  # applied now, not in the next crisis
        _report(db, c, "w3", "cheste", 7, "Última hora: desbordado el barranco en Cheste", source="levante-emv", channel="news")
        assert db.get(Signal, (crisis_id, "w3")).source_trust == "low"


def test_brains_cite_the_lessons_they_lean_on_and_only_real_ones_count(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        taught = learning.add_human_lesson(db, c, text="No contéis con el puente de la CV-36: está cerrado por obras desde ayer.", by="cecopi")
        _report(db, c, "b1", "paiporta", 7, "El agua entra en las casas")
        res = _evacuate(db, c, "paiporta", ["b1"], lessons=[f"L-{taught.id}", "L-99999", "whatever"])
        act = db.get(Action, (crisis_id, res["id"]))
        assert act.lessons == [f"L-{taught.id}"] and world.action_dict(act)["lessons"] == [f"L-{taught.id}"]
        screen = learning.lessons_screen(db, c)
        [row] = screen["now"]
        assert row["origin"] == "human" and row["uses"] == [{"by": "el coordinador", "ref": act.id, "note": ""}] and screen["applied"] == 1


def test_what_one_crisis_learns_the_next_one_starts_with(client):
    first = client.post("/crises", json={"pack": "riada-paiporta", "start": True}).json()["id"]
    with session_scope() as db:
        c = db.get(Crisis, first)
        mayor = db.get(Entity, (first, "alcaldia-paiporta"))
        for _ in range(2):
            outreach.set_status(db, c, outreach.queue_contact(db, c, entity=mayor, purpose="approval"), "no_answer")
    assert client.post(f"/crises/{first}/lessons", json={"text": "Las bombas del almacén de Torrent tardan 40 min en llegar a Paiporta.", "by": "cecopi"}).status_code == 201
    closed = client.post(f"/crises/{first}/close").json()
    carried = {l["kind"]: l for l in closed["lessons"]}
    assert {"entity_response", "human"} <= set(carried) and all(l["scope"] == "global" and l["evidence"] for l in closed["lessons"])

    second = client.post("/crises", json={"pack": "riada-paiporta", "start": True}).json()["id"]
    lessons = client.get(f"/crises/{second}/lessons").json()
    assert lessons["now"] == [] and {l["kind"] for l in lessons["before"]} >= {"entity_response", "human"}
    assert any("no contestó en crisis anteriores" in u["note"] for l in lessons["before"] for u in l["uses"])  # priors moved at the start
    state = client.get(f"/state?crisis_id={second}", headers=AUTH).json()
    assert {l["learned"] for l in state["lessons"]} == {"in_1_previous_crisis(es)"} and all(l["id"].startswith("L-") for l in state["lessons"])

    with session_scope() as db:  # the mayor does not answer this time either: the lesson gains weight
        c = db.get(Crisis, second)
        mayor = db.get(Entity, (second, "alcaldia-paiporta"))
        for _ in range(2):
            outreach.set_status(db, c, outreach.queue_contact(db, c, entity=mayor, purpose="approval"), "no_answer")
    client.post(f"/crises/{second}/close")
    third = client.post("/crises", json={"pack": "riada-paiporta", "start": True}).json()["id"]
    with session_scope() as db:
        g = db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.key == "entity_response:alcaldia-paiporta")).one()
        assert g.weight == 2 and len(g.stats["crises"]) == 2
        c = db.get(Crisis, third)  # ...and this time she answers everything: the lesson loses weight
        mayor = db.get(Entity, (third, "alcaldia-paiporta"))
        for _ in range(2):
            outreach.set_status(db, c, outreach.queue_contact(db, c, entity=mayor, purpose="approval"), "delivered")
    client.post(f"/crises/{third}/close")
    with session_scope() as db:
        g = db.scalars(select(Lesson).where(Lesson.scope == "global", Lesson.key == "entity_response:alcaldia-paiporta")).one()
        assert g.weight == 1 and g.status == "active"


def test_the_post_mortem_keeps_only_lessons_with_real_evidence(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        _report(db, c, "p1", "paiporta", 9, "Ancianos atrapados en la residencia", "Residencia Virgen del Carmen")
        inc = db.scalars(select(Incident).where(Incident.crisis_id == crisis_id)).first()
        brief = learning.review_brief(db, c)
        assert brief["incidents"][0]["id"] == inc.id and brief["incidents"][0]["minutes_until_someone_went"] == 0
        kept = learning.store_review(db, c, {"lessons": [
            {"subject": "Residencias", "lesson": "Envía un equipo a las residencias de mayores en cuanto la zona pase a severidad 6, sin esperar a su llamada.", "evidence": [inc.id, "inc-9999"]},
            {"subject": "inventada", "lesson": "Esta lección no cita nada que exista y no debe guardarse nunca.", "evidence": ["act-9999"]},
            {"subject": "corta", "lesson": "No.", "evidence": [inc.id]}]})
        assert [(l.kind, l.origin, l.scope, l.evidence) for l in kept] == [("review", "review", "global", [inc.id])]
