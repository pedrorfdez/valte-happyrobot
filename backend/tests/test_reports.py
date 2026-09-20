"""The incident channel: an actor of the crisis reports what it sees, and it has consequences."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from valte.core import needs, plan, reports, views, world
from valte.db import session_scope
from valte.models import Action, Crisis, Entity, Resource, Signal, Zone


def test_a_town_hall_reports_a_collapsed_road_and_the_world_changes(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        plan.replace_plan(db, c, {"incidents": [], "plan": {"summary": "plan previo"}})
        r = reports.file_report(db, c, by="alcaldia-paiporta", kind="road_cut", place="puente de la CV-36",
                                text="Se acaba de hundir el puente de la CV-36, no se puede entrar por el sur")
        sig = db.get(Signal, (crisis_id, r["signal_id"]))
        assert sig.source == "alcaldia-paiporta" and sig.confidence == "high" and sig.zone_id == "paiporta"  # own town, trusted
        z = db.get(Zone, (crisis_id, "paiporta"))
        assert z.extra["access_penalty_min"] == 15 and "CV-36" in z.extra["road_cut"]
        assert any("+15 min" in e for e in r["effects"])

        # repercussion on resources: whoever is already inside beats whoever has to drive in, and units stay busy longer
        assert needs.access_penalty(db, c, ["paiporta"]) == 15
        assert [n["suggested_verb"] for n in needs.open_needs(db, c) if n["signal_id"] == sig.id] == ["close_road"]  # someone must act on it
        assert needs.pick_responder(db, c, "close_road", "paiporta").id == "policia-local-paiporta"
        from valte.core import actions
        res = actions.propose_action(db, c, {"actor": "bomberos-vlc", "verb": "rescue", "target_zones": ["paiporta"],
                                             "params": {"units": 2}, "evidence": [sig.id]})
        act = db.get(Action, (crisis_id, res["id"]))
        held = (world.scenario_now(c).fromisoformat(act.reserved["release_t"]) - act.t).total_seconds() / 60
        assert round(held) == 60  # 45 + 15 of detour

        assert any("carretera cortada" in x or "paiporta" in x for x in [views.reasons_es(", ".join(plan.check_plan_validity(db, c)))])
        assert world.active_plan(db, c.id).invalidated_reason  # the plan no longer describes the world
        lines = [x["text"] for x in views.recent_changes(db, c, limit=6)]
        assert any("Alcaldía de Paiporta reporta" in x and "Carretera cortada" in x for x in lines)
        assert any("invalidado" in x and "carretera cortada en paiporta" in x for x in lines)
        assert world.build_state(db, c)["zones"][3]["access_penalty_min"] == 15  # the brain is told


def test_trapped_people_reported_by_an_authority_get_units_at_once(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        needs.add_default_reflexes(db, c)
        db.flush()
        before = sum(e.units_available or 0 for e in db.scalars(select(Entity).where(Entity.crisis_id == crisis_id)))
        r = reports.file_report(db, c, by="ayto-picanya", kind="people_trapped", place="bajo de la calle Mayor 12",
                                text="Tres personas atrapadas en un bajo, el agua sube")
        rescues = list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "rescue")))
        assert rescues and r["signal_id"] in rescues[0].evidence and rescues[0].origin == "tripwire"
        after = sum(e.units_available or 0 for e in db.scalars(select(Entity).where(Entity.crisis_id == crisis_id)))
        assert after == before - 2


def test_lost_stock_and_units_out_of_service_hit_the_inventory(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        r = reports.file_report(db, c, by="bomberos-vlc", kind="resource_lost", resource="bombas-achique", qty=4,
                                text="Un camión con cuatro bombas ha quedado atrapado")
        pumps = db.get(Resource, (crisis_id, "bombas-achique"))
        assert (pumps.available, pumps.total) == (8, 8) and "−4" in r["effects"][0]
        reports.file_report(db, c, by="bomberos-vlc", kind="units_down", units=5, text="Cinco dotaciones aisladas por el agua")
        fire = db.get(Entity, (crisis_id, "bomberos-vlc"))
        assert (fire.units_available, fire.units_total) == (35, 35)
        with pytest.raises(reports.BadReport):  # somebody else's stock
            reports.file_report(db, c, by="samu", kind="resource_lost", resource="bombas-achique", qty=1, text="x")


def test_a_town_hall_only_speaks_for_its_own_town(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        with pytest.raises(reports.BadReport):
            reports.file_report(db, c, by="alcaldia-paiporta", kind="road_cut", zone="chiva", text="puente caído")
        with pytest.raises(reports.BadReport):
            reports.file_report(db, c, by="social-media", kind="other", zone="chiva", text="no soy una entidad")
        with pytest.raises(reports.BadReport):
            reports.file_report(db, c, by="alcaldia-paiporta", kind="road_cut", text="   ")


def test_a_name_and_a_kind_are_enough(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        needs.add_default_reflexes(db, c)
        db.flush()
        # coordination reports too; the zone comes out of the name, and the name is the spot
        r = reports.file_report(db, c, by="cecopi", kind="road_cut", text="Se hunde el puente de la CV-36 en Paiporta")
        assert r["zone"] == "paiporta" and "CV-36" in db.get(Zone, (crisis_id, "paiporta")).extra["road_cut"]
        assert db.get(Signal, (crisis_id, r["signal_id"])).location["precision"] == "street"
        # no zone in the name: a town hall means its own town, coordination the zone that is worst off
        db.get(Zone, (crisis_id, "cheste")).severity_est = 8
        assert reports.file_report(db, c, by="cecopi", kind="power_out", text="Sin luz ni cobertura")["zone"] == "cheste"
        assert reports.file_report(db, c, by="ayto-picanya", kind="people_trapped", text="Dos personas en un bajo")["zone"] == "picanya"
        assert list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "rescue")))  # units at once
        # which stock and how many: also out of the name ("CV-36" is not a quantity)
        r = reports.file_report(db, c, by="bomberos-vlc", kind="resource_lost", text="Perdemos cuatro bombas de achique en la CV-36")
        assert db.get(Resource, (crisis_id, "bombas-achique")).available == 8 and "−4" in r["effects"][0]
        reports.file_report(db, c, by="bomberos-vlc", kind="units_down", text="3 dotaciones aisladas por el agua")
        assert db.get(Entity, (crisis_id, "bomberos-vlc")).units_total == 37
        with pytest.raises(reports.BadReport, match="Bombas de achique"):  # cannot tell which one: say what there is
            reports.file_report(db, c, by="bomberos-vlc", kind="resource_lost", text="Nos quedamos sin material")


def test_reports_over_http():
    from valte.main import app

    with TestClient(app) as client:
        cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        r = client.post(f"/crises/{cid}/reports", json={"by": "ayto-cheste", "kind": "power_out", "text": "Todo Cheste sin luz"})
        assert r.status_code == 201 and r.json()["zone"] == "cheste" and r.json()["by_name"] == "Ayuntamiento de Cheste"
        r = client.post(f"/crises/{cid}/reports", json={"by": "cecopi", "kind": "other", "name": "Cae la red de radio en Chiva"})
        assert r.status_code == 201 and r.json()["zone"] == "chiva" and r.json()["text"] == "Cae la red de radio en Chiva"
        assert client.post(f"/crises/{cid}/reports", json={"by": "cecopi", "kind": "other"}).status_code == 422  # no name
        assert client.post(f"/crises/{cid}/reports", json={"by": "ayto-cheste", "kind": "road_cut", "zone": "paiporta", "text": "x"}).status_code == 422
        listing = client.get(f"/crises/{cid}/reports?by=ayto-cheste").json()
        assert [x["kind"] for x in listing["reports"]] == ["power_out"] and {k["id"] for k in listing["kinds"]} >= {"road_cut", "units_down"}
        assert any(s["signal"]["channel"] == "report" for s in client.get(f"/crises/{cid}/signals").json()["signals"])


def test_a_neighbour_reports_with_low_reliability_and_nothing_is_applied(crisis_id):
    with session_scope() as db:
        c = db.get(Crisis, crisis_id)
        needs.add_default_reflexes(db, c)
        db.flush()
        before = sum(e.units_available or 0 for e in db.scalars(select(Entity).where(Entity.crisis_id == crisis_id)))
        r = reports.file_report(db, c, by="vecinos-paiporta", kind="road_cut", text="Se ha hundido el puente de la CV-36")
        sig = db.get(Signal, (crisis_id, r["signal_id"]))
        assert r["zone"] == "paiporta" and r["reliability"] == "low"  # a neighbour talks about their own town
        assert sig.source_trust == "low" and sig.confidence == "low" and sig.channel == "report"
        assert "access_penalty_min" not in (db.get(Zone, (crisis_id, "paiporta")).extra or {})  # a lead, not a fact
        assert "fiabilidad baja" in r["effects"][0]

        # people trapped, street-level, severity 9: from an authority two units leave at once; on a neighbour's word alone, none
        r = reports.file_report(db, c, by="vecinos-picanya", kind="people_trapped", text="Tres personas atrapadas en la calle Mayor 12")
        assert not list(db.scalars(select(Action).where(Action.crisis_id == crisis_id, Action.verb == "rescue")))
        assert before == sum(e.units_available or 0 for e in db.scalars(select(Entity).where(Entity.crisis_id == crisis_id)))

        # what is not a neighbour's to tell, and other towns, are refused
        with pytest.raises(reports.BadReport):
            reports.file_report(db, c, by="vecinos-paiporta", kind="units_down", text="Tres dotaciones aisladas")
        with pytest.raises(reports.BadReport):
            reports.file_report(db, c, by="vecinos-paiporta", kind="road_cut", zone="chiva", text="puente caído")
        assert {k["id"] for k in reports.kinds(db.get(Entity, (crisis_id, "vecinos-paiporta")))} == set(reports.CIVILIAN_KINDS)

        # another source saying the same in the same town lifts it: the listing follows the signal
        reports.file_report(db, c, by="alcaldia-paiporta", kind="road_cut", text="Puente de la CV-36 hundido")
        mine = reports.list_reports(db, c, by="vecinos-paiporta")
        assert mine[0]["reliability"] == "low" and mine[0]["confidence"] == "low"  # same channel: not corroboration yet
        lines = [x["text"] for x in views.recent_changes(db, c, limit=10)]
        assert any("Vecinos · Paiporta reporta (sin verificar)" in x for x in lines)


def test_the_dashboard_a_neighbour_gets():
    from valte.main import app

    with TestClient(app) as client:
        cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        h = client.get(f"/crises/{cid}").json()
        assert h["access"]["role"] == "coordination" and len(h["access"]["screens"]) == 5
        assert {"role": "civilian", "entity_id": "vecinos-paiporta", "label": "Vecinos · Paiporta"} in h["roles"]
        assert client.get(f"/crises/{cid}?entity_id=bomberos-vlc").json()["access"]["role"] == "responder"

        h = client.get(f"/crises/{cid}?entity_id=vecinos-paiporta").json()
        assert h["access"] == {"role": "civilian", "screens": ["contacts"], "can_report": True, "report_reliability": "low",
                               "can_contact": False, "can_decide": False}
        assert h["ringing"] == []

        everyone = client.get(f"/crises/{cid}/directory").json()
        mine = client.get(f"/crises/{cid}/directory?entity_id=vecinos-paiporta").json()
        ids = {x["id"] for x in mine["contacts"]}
        assert "alcaldia-paiporta" in ids and "delegacion-gobierno" in ids and "ayto-chiva" not in ids  # their town, and who answers for all
        assert len(ids) < len(everyone["contacts"]) and h["kpis"]["contacts"]["entities"] == len(ids)
        assert all(x["communications"] == [] for x in mine["contacts"]) and mine["scope"]["zones"] == ["Paiporta"]

        r = client.post(f"/crises/{cid}/entities/alcaldia-paiporta/contact", json={"message": "hola", "by": "vecinos-paiporta"})
        assert r.status_code == 403
        r = client.post(f"/crises/{cid}/reports", json={"by": "vecinos-paiporta", "kind": "power_out", "name": "Sin luz en toda la calle"})
        assert r.status_code == 201 and r.json()["reliability"] == "low" and r.json()["confidence"] == "low"
        listing = client.get(f"/crises/{cid}/reports?by=vecinos-paiporta").json()
        assert listing["reliability"] == "low" and "units_down" not in {k["id"] for k in listing["kinds"]}


def test_a_situation_typed_in_the_outside_world_always_has_a_consequence():
    from valte.main import app

    with TestClient(app) as client:
        cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        r = client.post(f"/crises/{cid}/sim/inject", json={
            "kind": "situation", "content": "Hay 50 personas atrapadas en el colegio de Massanassa"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["injected"] == "situation" and body["kind"] == "people_trapped"
        assert body["zone"] == "massanassa" and body["reliability"] == "high"
        assert body["signal_id"] and body["effects"]
        sig = client.get(f"/crises/{cid}/signals").json()["signals"]
        assert any(s["signal"]["id"] == body["signal_id"] and s["signal"]["confidence"] == "high" for s in sig)


def test_a_trusted_other_report_is_read_into_the_kind_that_has_effects():
    from valte.main import app

    with TestClient(app) as client:
        cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        r = client.post(f"/crises/{cid}/reports", json={
            "by": "ayto-picanya", "kind": "other", "name": "Hay dos personas atrapadas en un bajo de la calle Mayor"})
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "people_trapped" and r.json()["zone"] == "picanya"
        assert r.json()["reliability"] == "high"


def test_an_unknown_town_typed_as_cut_off_enters_the_map_isolated():
    from types import SimpleNamespace

    from valte.core.world_parse import parse_local
    from valte.main import app

    zones = [SimpleNamespace(id="paiporta", name="Paiporta")]
    out = parse_local("Begís está aislada", zones=zones)
    assert out["kind"] == "zone_new" and out["place"] == "Begís" and not out["zone"]
    assert parse_local("begís está aislada", zones=zones)["kind"] == "zone_new"
    assert parse_local("he añadido begís y está aislada", zones=zones)["kind"] == "zone_new"
    already = zones + [SimpleNamespace(id="begis", name="Begís")]
    cut = parse_local("Begís está aislada", zones=already)
    assert cut["kind"] == "road_cut" and cut["zone"] == "begis"
    assert parse_local("Cinco dotaciones aisladas por el agua", zones=already)["kind"] == "units_down"
    from valte.core.world_parse import combine
    shrugged = combine({"kind": "other", "zone": "", "severity": 6}, cut)
    assert shrugged["kind"] == "road_cut" and shrugged["zone"] == "begis"

    with TestClient(app) as client:
        cid = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        r = client.post(f"/crises/{cid}/sim/inject", json={"kind": "situation", "content": "Begís está aislada"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["injected"] == "situation" and body["kind"] == "zone_new" and body["zone"] == "begis"
        assert any("Acceso a Begís" in e for e in body["effects"])
        z = next(x for x in client.get(f"/crises/{cid}/zones").json()["zones"] if x["id"] == "begis")
        assert z["access_penalty_min"] == 15 and z["road_cut"]

        cid2 = client.post("/crises", json={"pack": "riada-paiporta", "start": False}).json()["id"]
        added = client.post(f"/crises/{cid2}/sim/inject", json={"kind": "situation", "content": "añado Begís"})
        assert added.status_code == 200, added.text
        assert added.json()["kind"] == "zone_new" and added.json()["zone"] == "begis"
        z = next(x for x in client.get(f"/crises/{cid2}/zones").json()["zones"] if x["id"] == "begis")
        assert z["access_penalty_min"] == 0
        isolated = client.post(f"/crises/{cid2}/sim/inject", json={"kind": "situation", "content": "está aislada"})
        assert isolated.status_code == 200, isolated.text
        assert isolated.json()["kind"] == "road_cut" and isolated.json()["zone"] == "begis"
        z = next(x for x in client.get(f"/crises/{cid2}/zones").json()["zones"] if x["id"] == "begis")
        assert z["access_penalty_min"] == 15


def test_world_parse_is_a_small_fast_extract():
    from valte.hr import specs

    spec = next(s for s in specs.all_specs() if s.name == "PedroD-world-parse")
    ids = {n.name: n.name for n in spec.nodes}
    cfg = spec.nodes[1].config(ids, specs.Ctx(secret="s"))
    assert cfg["model"]["static"]["id"] == "gpt-4.1-mini"
    assert spec.nodes[0].config(ids, specs.Ctx(secret="s"))["params"] == [
        "text", "environment", "zones", "hint_kind", "reporter"]
    assert "aislada" in specs.WORLD_PARSE_PROMPT and "Do not invent" in specs.WORLD_PARSE_PROMPT
