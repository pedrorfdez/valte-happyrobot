"""The incident channel also takes what CHANGED: a zone nobody had listed, stock that arrives, somebody who joins
with their own material, and what a person already did on their own. One line of text, one kind, nothing else."""

import pytest
from sqlalchemy import select

from valte.core import incidents, reports
from valte.db import session_scope
from valte.models import Action, Crisis, Entity, Resource, Signal, Zone


def _file(db, c, by, kind, text, **kw):
    return reports.file_report(db, c, by=by, kind=kind, text=text, **kw)


def test_a_town_nobody_had_listed_enters_the_map_with_its_people(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        out = _file(db, c, "alcaldia-paiporta", "zone_new",
                    "El barranco se ha llevado la mota y ahora se inunda Sedaví, 10.500 habitantes, en 25 min")
        z = db.get(Zone, (crisis_id, "sedavi"))
        assert out["zone"] == "sedavi" and z.population == 10500 and not z.is_origin
        assert {"to": "sedavi", "delay_min": 25} in db.get(Zone, (crisis_id, "paiporta")).downstream
        assert any("Aguas abajo de Paiporta" in e for e in out["effects"])
        # a zone you cannot talk to is useless: it gets its town hall, its neighbours and whoever already covers everything
        assert db.get(Entity, (crisis_id, "ayto-sedavi")).capabilities == ["order_evacuation", "open_shelter", "close_road"]
        assert db.get(Entity, (crisis_id, "poblacion-sedavi")).kind == "population"
        assert "sedavi" in db.get(Entity, (crisis_id, "bomberos-vlc")).jurisdiction
        # and it is an incident like any other: severity, countdown and somebody to send
        sig = db.get(Signal, (crisis_id, out["signal_id"]))
        assert sig.zone_id == "sedavi" and z.severity_est >= 5
        [inc] = [i for i in incidents.open_incidents(db, c) if i.zone_id == "sedavi"]
        assert inc.state in ("active", "attended")

        with pytest.raises(reports.BadReport, match="ya está en el mapa"):
            _file(db, c, "alcaldia-paiporta", "zone_new", "ahora también se inunda Sedaví")
        with pytest.raises(reports.BadReport, match="cómo se llama"):
            _file(db, c, "alcaldia-paiporta", "zone_new", "hay otra zona afectada más abajo")


def test_stock_that_arrives_is_added_and_a_wrong_count_is_corrected(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        pumps = db.get(Resource, (crisis_id, "bombas-achique"))
        before = pumps.available
        out = _file(db, c, "cecopi", "resource_new", "Nos llegan 200 mantas del almacén de Alicante y 4 bombas de achique")
        assert pumps.available == before + 4 and pumps.total == before + 4
        new = db.scalars(select(Resource).where(Resource.crisis_id == crisis_id, Resource.name == "Mantas")).all()
        assert len(new) == 1 and new[0].available == 200 or any(r.available >= 200 for r in new)
        assert len(out["effects"]) == 2 and out["signal_id"] is None  # logistics is not an incident

        _file(db, c, "cecopi", "resource_new", "Nos hemos equivocado: solo quedan 3 bombas de achique")
        assert db.get(Resource, (crisis_id, "bombas-achique")).available == 3

        with pytest.raises(reports.BadReport, match="cuántos"):
            _file(db, c, "cecopi", "resource_new", "nos llega material")


def test_whoever_turns_up_to_help_is_registered_with_what_they_bring(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        out = _file(db, c, "alcaldia-paiporta", "entity_new",
                    "Se suma Cruz Roja Valencia con 12 voluntarios para rescate y 2 embarcaciones")
        ent = db.get(Entity, (crisis_id, "cruz-roja-valencia"))
        assert ent.kind == "responder" and ent.units_available == 12 and ent.trust == "medium"
        assert "rescue" in ent.capabilities and ent.jurisdiction == ["paiporta"] and ent.provenance == "discovered"
        boats = db.scalars(select(Resource).where(Resource.crisis_id == crisis_id,
                                                  Resource.owner_entity_id == "cruz-roja-valencia")).all()
        assert [(r.name, r.available) for r in boats] == [("Embarcaciones", 2)]
        assert any("12 unidades" in e for e in out["effects"])

        # registered means usable: the kernel now accepts work for them
        from valte.core import actions

        res = actions.propose_action(db, c, {"actor": "cruz-roja-valencia", "verb": "rescue", "target_zones": ["paiporta"],
                                             "params": {"units": 2}, "evidence": ["x"], "reasoning": "y"}, origin="human")
        assert res.get("id") and not res.get("error")


def test_what_a_person_already_did_becomes_their_own_executed_action(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        out = _file(db, c, "alcaldia-paiporta", "action_done", "Ya hemos cortado el puente de la CV-36 por nuestra cuenta")
        act = db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "close_road")).one()
        assert act.actor == "alcaldia-paiporta" and act.origin == "human" and act.status == "executed"
        assert act.target_zones == ["paiporta"] and "CV-36" in act.params["road"]
        assert any(act.id in e for e in out["effects"]) and out["signal_id"] is None

        # the kernel's rules still apply: a town hall does not rescue, and nothing is recorded that it cannot do
        with pytest.raises(reports.BadReport, match="no puede"):
            _file(db, c, "alcaldia-paiporta", "action_done", "hemos rescatado a la familia del bajo")
        with pytest.raises(reports.BadReport, match="no sé qué habéis hecho"):
            _file(db, c, "alcaldia-paiporta", "action_done", "hemos estado toda la mañana liados")


def test_a_neighbour_cannot_change_the_world(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        offered = {k["id"] for k in reports.kinds(db.get(Entity, (crisis_id, "vecinos-paiporta")))}
        assert not offered & set(reports.WORLD_KINDS)
        for kind in ("zone_new", "resource_new", "entity_new", "action_done"):
            with pytest.raises(reports.BadReport):
                _file(db, c, "vecinos-paiporta", kind, "se suma mi cuñado con la furgoneta")
        assert {k["group"] for k in reports.kinds(db.get(Entity, (crisis_id, "cecopi")))} == {"incident", "world"}
