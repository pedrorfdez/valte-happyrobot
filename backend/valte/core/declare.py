"""Declaring a crisis in one go: a person writes (or dictates) everything they know, and this turns it into the
spec `world.create_crisis` takes. HappyRobot reads the text when it is available; `parse_local` is the labelled
stand-in (offline, tests, an outage). Whoever reads it, `normalize` has the last word, and what had to be
assumed is said out loud so the person can correct the text before launching anything."""

import asyncio
import json
import logging
import re
import time
from typing import Any

from valte.core.world import list_packs, load_pack, slugify
from valte.db import session_scope
from valte.hr import registry
from valte.hr.client import hr

log = logging.getLogger("valte.declare")

HAZARD_LABEL = {"flood": "Inundación", "fire": "Incendio forestal", "blackout": "Apagón",
                "infra": "Fallo de infraestructura", "mci": "Víctimas múltiples", "other": "Emergencia"}
HAZARD_WORDS = [
    ("flood", r"inundaci|riada|crecida|desbord|\bdana\b|barranco|torrencial|gota fr[ií]a|tromba"),
    ("fire", r"incendio|\bfuego\b|\bllamas\b|\bhumo\b"),
    ("blackout", r"apag[oó]n|sin luz|sin suministro|corte (?:de luz|el[eé]ctrico|de suministro)|ca[ií]da de la red"),
    ("infra", r"\bpresa\b|colapso|derrumbe|\bfuga\b|tuber[ií]a|infraestructura|descarrila|socav[oó]n"),
    ("mci", r"v[ií]ctimas m[uú]ltiples|accidente m[uú]ltiple|atentado|explosi[oó]n|decenas de heridos"),
]
# Who usually has something to say, and how far to believe them.
KNOWN_SOURCES = [
    (r"\b112\b", "112", "Llamadas de emergencia", "high"),
    (r"\baemet\b", "AEMET", "Avisos y predicción meteorológica", "high"),
    (r"\bchj\b|confederaci[oó]n hidrogr[aá]fica|\baforos?\b", "Aforos CHJ", "Caudales y niveles en tiempo real", "high"),
    (r"\bdgt\b", "DGT", "Estado de las carreteras", "high"),
    (r"red el[eé]ctrica|\bree\b|iberdrola|i-de\b", "Red Eléctrica", "Estado del suministro eléctrico", "high"),
    (r"copernicus|effis|sat[eé]lite", "Copernicus", "Imágenes y perímetros por satélite", "high"),
    (r"sensor|c[aá]maras?\b|pluvi[oó]metro", "Sensores", "Lecturas automáticas sobre el terreno", "high"),
    (r"à punt|a punt\b|levante|rtve|\bprensa\b|medios|radio\b|televisi[oó]n|peri[oó]dico", "Medios locales", "Prensa, radio y televisión", "medium"),
    (r"redes sociales|twitter|\btuits?\b|telegram|whatsapp|instagram|tiktok", "Redes sociales", "Publicaciones sin verificar", "low"),
]
DEFAULT_SOURCES = ("112", "Medios locales", "Redes sociales")
# A number followed by one of these is not a resource.
NOT_A_RESOURCE = (r"habitantes?|hab|vecinos?|personas?|residentes?|min|minutos?|h|horas?|km|kil[oó]metros?|m|metros?|"
                  r"a[ñn]os?|heridos?|fallecidos?|muertos?|atrapad[oa]s?|evacuad[oa]s?|desaparecid[oa]s?|grados?|"
                  r"litros por|mm|hect[aá]reas?|ha|zonas?|municipios?|pueblos?|d[ií]as?|mil|millones|de la|de")

_W = r"[A-ZÀ-Ý][\wÀ-ÿ'’·-]+"
PLACE = rf"{_W}(?:\s+(?:de\s+la\s+|de\s+les\s+|de\s+los\s+|del\s+|dels\s+|de\s+|d['’]|la\s+|el\s+|les\s+)?{_W})*"
_NUM = r"\d{1,3}(?:[.\s]\d{3})+|\d+"
_TIME = r"(\d+)\s*(min(?:utos?)?|h(?:oras?)?)\b"


_SPOKEN_TIME = [(r"una hora y media|hora y media", "90 minutos"), (r"tres cuartos de hora", "45 minutos"),
                (r"(?:un )?cuarto de hora", "15 minutos"), (r"media hora", "30 minutos"), (r"un par de horas", "120 minutos"),
                (r"una hora", "60 minutos")]
_ONES = {w: i for i, w in enumerate("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
                                    "dieciséis diecisiete dieciocho diecinueve veinte veintiuno veintidós veintitrés veinticuatro "
                                    "veinticinco veintiséis veintisiete veintiocho veintinueve".split())}
_ONES.update({"un": 1, "una": 1, "veintiún": 21, "veintiuna": 21, "dieciseis": 16, "veintidos": 22, "veintitres": 23, "veintiseis": 26})
_TENS = dict(zip("treinta cuarenta cincuenta sesenta setenta ochenta noventa".split(), range(30, 100, 10)))
_HUNDREDS = {"cien": 100, "ciento": 100, **{w + s: v for w, v in (("doscient", 200), ("trescient", 300), ("cuatrocient", 400),
             ("quinient", 500), ("seiscient", 600), ("setecient", 700), ("ochocient", 800), ("novecient", 900)) for s in ("os", "as")}}
_NUMWORD = "|".join(sorted({*_ONES, *_TENS, *_HUNDREDS, "mil"}, key=len, reverse=True))


def spoken_to_digits(text: str) -> str:
    """Dictation writes some numbers as words ("ocho autobombas", "veintiséis mil", "una hora"). Articles stay:
    a lone un/una/uno is not a quantity."""
    for rx, digits in _SPOKEN_TIME:
        text = re.sub(rf"\b(?:{rx})\b", digits, text, flags=re.I)

    def number(m: re.Match[str]) -> str:
        words = [w for w in re.split(r"\s+", m.group(0).lower()) if w != "y"]
        if all(w in ("un", "una", "uno") for w in words):
            return m.group(0)
        total = cur = 0
        for w in words:
            if w == "mil":
                total, cur = total + (cur or 1) * 1000, 0
            else:
                cur += _ONES.get(w) or _TENS.get(w) or _HUNDREDS.get(w) or 0
        return str(total + cur)

    text = re.sub(r"\b(\d{1,3})\s+mil\b", lambda m: str(int(m.group(1)) * 1000), text)  # "26 mil habitantes"
    return re.sub(rf"\b(?:{_NUMWORD})(?:\s+(?:y\s+)?(?:{_NUMWORD}))*\b", number, text, flags=re.I)


def _int(s: str) -> int:
    return int(re.sub(r"\D", "", s) or 0)


def _minutes(n: str, unit: str) -> int:
    return int(n) * (60 if unit.lower().startswith("h") else 1)


def parse_local(text: str) -> dict[str, Any]:
    """Rules of thumb for Spanish prose. Good with the way people list things ("Serra (3.300 habitantes)",
    "de Serra a Náquera en 40 minutos", "8 autobombas"); everything it could not find is left empty."""
    head = re.split(r"[.\n]", text.strip(), maxsplit=1)[0].strip()
    original = text  # as the person said it: what becomes the first reports
    text = spoken_to_digits(text)
    low = text.lower()
    hits = [(m.start(), h) for h, rx in HAZARD_WORDS for m in [re.search(rx, low)] if m]
    hazard = min(hits)[1] if hits else "other"

    zones: dict[str, dict[str, Any]] = {}

    def zone(name: str) -> dict[str, Any] | None:
        name = re.sub(r"^(?:En|El|La|Los|Las|Desde|De|Y|Hay|Tenemos|Afecta|Fuentes|Recursos|Zonas)\s+", "", name.strip(" .,;:"))
        if len(name) < 3 or slugify(name) in ("aemet", "chj", "dgt", "ume", "cecopi", "copernicus"):
            return None
        return zones.setdefault(slugify(name), {"name": name, "population": 0, "is_origin": False, "to": []})

    said = r"(?:\(|:|·|-|–|,?\s*(?:que\s+)?(?:con|tiene|son|tendrá|cuenta con)|,)?"
    for m in re.finditer(rf"({PLACE})\s*{said}\s*(?:unos\s+|unas\s+|aprox\.?\s+)?({_NUM})\s*(mil\s+)?(?:habitantes|hab\b\.?|vecinos|residentes)"
                         rf"(?:\s+y\s+({PLACE})\s*{said}\s*({_NUM})\b(?!\s*(?:min|h\b|hora)))?", text):
        z = zone(m.group(1))
        if z:
            z["population"] = _int(m.group(2)) * (1000 if m.group(3) else 1)
        also = zone(m.group(4)) if m.group(4) else None  # "Náquera tiene 7.500 habitantes y Bétera 26.000"
        if also:
            also["population"] = _int(m.group(5))
    for m in re.finditer(r"(?:zonas?|municipios?|pueblos?|barrios?|localidades|poblaciones)(?:\s+afectad[oa]s)?\s*(?::|son\b|es\b)\s*([^.\n]+)|afecta(?:n|ndo|r[aá])?\s+a\s+([^.\n]+)", text, re.I):
        for item in re.split(r",|;|\s+y\s+|\s+e\s+", m.group(1) or m.group(2)):
            found = re.match(rf"\s*(?:a\s+|en\s+)?({PLACE})", item)
            if found:
                zone(found.group(1))

    def edge(src: str, dst: str, delay: int) -> None:
        a, b = zone(src), zone(dst)
        if a and b and a is not b:
            a["to"] = [t for t in a["to"] if slugify(t["name"]) != slugify(b["name"])] + [{"name": b["name"], "delay_min": delay}]

    for m in re.finditer(rf"\b(?i:de|desde)\s+({PLACE})\s+(?:a|hasta|hacia)\s+({PLACE})[^.\n]{{0,30}}?{_TIME}", text):
        edge(m.group(1), m.group(2), _minutes(m.group(3), m.group(4)))
    for m in re.finditer(rf"({PLACE})\s*(?:→|->|=>)\s*({PLACE})\s*\(?\s*(?:en\s+)?{_TIME}", text):
        edge(m.group(1), m.group(2), _minutes(m.group(3), m.group(4)))

    for m in re.finditer(rf"(?i:empieza|comienza|empez[oó]|comenz[oó]|se inicia|se inici[oó]|se origina|se origin[oó]|origen|foco|nace|declarado|declarada)\b[^.\n]{{0,25}}?\ben\s+({PLACE})", text):
        z = zone(m.group(1))
        if z:
            z["is_origin"] = True
    first = next((z for z in zones.values() if z["is_origin"]), None) or next(iter(zones.values()), None)
    for m in re.finditer(rf"lleg\w+\s+a\s+({PLACE})\s+en\s+(?:unos\s+|unas\s+)?{_TIME}", text):
        if first:
            edge(first["name"], m.group(1), _minutes(m.group(2), m.group(3)))

    region = ""
    m = re.search(rf"\b(?:comarca|provincia|regi[oó]n|t[eé]rmino)\s+(?:de\s+la\s+|de\s+l['’]|del\s+|de\s+)?({PLACE})", text)
    m = m or re.search(rf"\b((?:Sierra|Valle|Vall|Vega|Ribera|Horta|Marina|Plana|Camp|Costa|Parque Natural)\s+(?:de\s+la\s+|de\s+|del\s+|d['’])?{PLACE})", text)
    if m:
        region = m.group(1)

    resources: dict[str, dict[str, Any]] = {}
    for m in re.finditer(rf"\b({_NUM})\s+(?!(?:{NOT_A_RESOURCE})\b)([a-zà-ÿ]{{3,}}(?:\s+(?:de\s+)?(?!y\b|en\b|que\b|para\b|con\b)[a-zà-ÿ]{{3,}}){{0,2}})", text):
        name = m.group(2).strip()
        resources.setdefault(slugify(name), {"name": name[0].upper() + name[1:], "qty": _int(m.group(1)), "unit": "", "desc": ""})

    sources = [{"name": name, "desc": desc, "trust": trust} for rx, name, desc, trust in KNOWN_SOURCES if re.search(rx, low)]

    place = (first or {}).get("name") or region
    name = head[0].upper() + head[1:] if 0 < len(head) <= 60 else f"{HAZARD_LABEL[hazard]}{' en ' + place if place else ''}"
    ordered = sorted(zones.values(), key=lambda z: text.find(z["name"]))  # in the order the person named them
    return {"name": name, "region": region, "hazard_type": hazard, "summary": head[:200], "zones": ordered,
            "sources": sources, "resources": list(resources.values()), "reports": _facts_local(original, ordered)}


GRAVE = [(9, r"atrapad|arrastrad|desaparecid|v[ií]ctimas|fallecid|muert|no pued\w+ salir"),
         (8, r"desbordad|fuera de control|sin control|descontrolad|evacuando|entra en las casas|llamas (?:junto|cerca|a las puertas)|colaps|derrumb|al l[ií]mite"),
         (7, r"avanza r[aá]pid|muy r[aá]pid|nivel rojo|aviso rojo|extrem|crece r[aá]pid|sube r[aá]pid|poniente|racha")]
SITES = r"residencias?|hospital(?:es)?|colegios?|guarder[ií]as?|camping|centro de salud|geri[aá]trico|urbanizaci[oó]n|pol[ií]gono"


def _gravity(sentence: str, floor: int) -> int:
    low = sentence.lower()
    return max([sev for sev, rx in GRAVE if re.search(rx, low)] + [floor])


def _spot(phrase: str) -> str:
    """'residencias de mayores y un hospital con el grupo…' → 'residencias de mayores': the place, not the sentence."""
    words = re.split(r"\s+(?:y|e|con|que|donde|sin|al|a)\s+", phrase.strip(), maxsplit=1)[0].split()[:5]
    while words and words[-1].lower() in ("de", "del", "la", "las", "los", "el", "en"):
        words.pop()
    return " ".join(words)


def _facts_local(text: str, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the description states is already happening, as the first reports of the crisis: the hazard where it
    has started, and the people or vulnerable places it names. A rule of thumb; HappyRobot reads it better."""
    if not zones:
        return []
    origins = [z for z in zones if z["is_origin"]] or zones[:1]
    sentences = [x.strip() for x in re.split(r"(?<=[.;!?])\s+|\n+", text) if x.strip()]
    whole = _gravity(text, 6)
    out = []
    for z in origins:
        here = next((x for x in sentences if z["name"].lower() in x.lower()), sentences[0] if sentences else "")
        out.append({"zone": z["name"], "severity": max(_gravity(here, 6), min(whole, 7)), "text": here[:280], "place": "", "people": 0})
    for x in sentences:
        site = re.search(rf"(?:\d+\s+|una?\s+|dos\s+|el\s+|la\s+|los\s+|las\s+)?((?:{SITES})[^,.;]{{0,50}})", x, re.I)
        trapped = re.search(r"atrapad|herid|aislad|no pued\w+ salir|subid[oa]s? a", x, re.I)
        if not site and not trapped:
            continue
        zone = next((z["name"] for z in zones if z["name"].lower() in x.lower()), origins[0]["name"])
        people = [int(re.sub(r"\D", "", m.group(1))) for m in re.finditer(
            r"(\d[\d.]*)\s+(?:personas|vecinos|ancianos|mayores|residentes|ni[ñn]os|heridos|atrapad[oa]s|pacientes)", spoken_to_digits(x.lower()))]
        out.append({"zone": zone, "severity": _gravity(x, 8 if trapped else 7), "text": x[:280],
                    "place": _spot(site.group(1)) if site else "", "people": max(people, default=0)})
    return out


def quantities(text: str) -> list[tuple[int, str]]:
    """"nos llegan 200 mantas y 4 bombas de achique" -> [(200, "mantas"), (4, "bombas de achique")].
    Shared with the incident channel: one parser for how people write amounts."""
    out: list[tuple[int, str]] = []
    for m in re.finditer(rf"\b({_NUM})\s+(?!(?:{NOT_A_RESOURCE})\b)([a-zà-ÿ]{{3,}}(?:\s+(?:de\s+)?(?!y\b|en\b|que\b|para\b|con\b)[a-zà-ÿ]{{3,}}){{0,2}})",
                         spoken_to_digits(text)):
        out.append((_int(m.group(1)), m.group(2).strip()))
    return out


def match_pack(text: str, hazard: str) -> dict[str, Any] | None:
    """An official plan we already hold beats anything typed: it brings who to call, the doctrine and the stock."""
    low = slugify(text)
    for card in list_packs():
        pack = load_pack(card["id"])
        named = sum(1 for z in pack.get("zones") or [] if slugify(z["name"]) in low)
        if pack.get("hazard_type") == hazard and (named >= 2 or slugify(pack["name"]) in low):
            return pack
    return None


def normalize(raw: dict[str, Any], text: str) -> dict[str, Any]:
    """One shape whoever parsed it, plus what is missing and what we assumed."""
    hazard = str(raw.get("hazard_type") or raw.get("scenario") or "other").lower()
    hazard = hazard if hazard in HAZARD_LABEL else "other"
    assumptions: list[str] = [str(a) for a in raw.get("assumptions") or [] if a]

    pack = match_pack(text, hazard)
    if pack:
        names = {z["id"]: z["name"] for z in pack["zones"]}
        spec = {"name": pack["name"], "region": pack["region"], "hazard_type": hazard, "pack": pack["id"],
                "summary": str(raw.get("summary") or pack.get("description") or ""),
                "zones": [{"id": z["id"], "name": z["name"], "population": z["population"], "is_origin": bool(z.get("is_origin")),
                           "to": [{"name": names.get(e["to"], e["to"]), "delay_min": e["delay_min"]} for e in z.get("downstream") or []]}
                          for z in pack["zones"]],
                "sources": [{"name": e["name"], "desc": e.get("notes") or "", "trust": e.get("trust", "medium")}
                            for e in pack["entities"] if e["kind"] == "information_source"],
                "resources": [{"name": r["name"], "qty": r["total"], "unit": r.get("unit") or "", "desc": ""} for r in pack["resources"]]}
        notes = [f"Reconozco el plan oficial «{pack['name']}»: cargo sus zonas, entidades, doctrina y recursos."]
        spec["reports"] = _reports(raw, spec["zones"], notes)
        return {"spec": spec, "missing": [], "blocking": False, "assumptions": notes, "risk": risk_by_zone(spec["zones"], spec["reports"])}

    zones: dict[str, dict[str, Any]] = {}
    for z in raw.get("zones") or []:
        name = str((z or {}).get("name") or "").strip()
        if not name:
            continue
        pop = z.get("population") or 0
        zones.setdefault(slugify(name), {"name": name, "population": _int(str(pop)) if isinstance(pop, str) else int(pop),
                                         "is_origin": str(z.get("is_origin", "")).lower() in ("true", "1"), "to": z.get("to") or []})
    for z in list(zones.values()):  # a zone that is only named as a destination is a zone too
        edges = []
        for t in z["to"]:
            target = str((t.get("name") or t.get("to") or "") if isinstance(t, dict) else t).strip()
            delay = int((t.get("delay_min") if isinstance(t, dict) else 0) or 30)
            if target and slugify(target) != slugify(z["name"]):
                zones.setdefault(slugify(target), {"name": target, "population": 0, "is_origin": False, "to": []})
                edges.append({"name": zones[slugify(target)]["name"], "delay_min": max(1, delay)})
        z["to"] = edges
    zl = list(zones.values())
    for z in zl:
        z.setdefault("to", [])

    if len(zl) > 1 and not any(z["to"] for z in zl):
        for a, b in zip(zl, zl[1:]):
            a["to"] = [{"name": b["name"], "delay_min": 30}]
        assumptions.append("No dices cómo avanza de una zona a otra: supongo que sigue el orden en que las nombras, 30 min entre cada una.")
    if zl and not any(z["is_origin"] for z in zl):
        reached = {slugify(t["name"]) for z in zl for t in z["to"]}
        origins = [z for z in zl if slugify(z["name"]) not in reached] or zl[:1]
        for z in origins:
            z["is_origin"] = True
        assumptions.append(f"Tomo como origen {', '.join(z['name'] for z in origins)}.")

    sources = [{"name": str(s.get("name")).strip(), "desc": str(s.get("desc") or s.get("description") or ""),
                "link": str(s.get("link") or ""), "trust": s.get("trust") if s.get("trust") in ("high", "medium", "low") else "medium"}
               for s in raw.get("sources") or [] if (s or {}).get("name")]
    if not sources:
        sources = [{"name": n, "desc": d, "link": "", "trust": t} for _, n, d, t in KNOWN_SOURCES if n in DEFAULT_SOURCES]
        assumptions.append("No nombras fuentes de datos: escucho las habituales (112, medios y redes sociales).")

    resources = []
    for r in raw.get("resources") or []:
        if not (r or {}).get("name"):
            continue
        try:
            qty = float(str(r.get("qty", r.get("total", 0)) or 0).replace(",", "."))
        except ValueError:
            qty = 0
        resources.append({"name": str(r["name"]).strip(), "qty": int(qty) if qty == int(qty) else qty,
                          "unit": str(r.get("unit") or ""), "desc": str(r.get("desc") or r.get("description") or "")})

    region = str(raw.get("region") or "").strip()
    name = str(raw.get("name") or "").strip() or f"{HAZARD_LABEL[hazard]}{' en ' + (zl[0]['name'] if zl else region) if (zl or region) else ''}"
    missing = []
    if not zl:
        missing.append("qué zonas afecta (municipios o barrios, y cuánta gente vive en cada uno)")
    elif any(not z["population"] for z in zl):
        missing.append("habitantes de " + ", ".join(z["name"] for z in zl if not z["population"]))
    if not resources:
        missing.append("con qué recursos se cuenta (p. ej. «8 autobombas y 300 mantas»)")
    reports = _reports(raw, zl, assumptions)
    return {"spec": {"name": name[:80], "region": region, "hazard_type": hazard, "pack": None,
                     "summary": str(raw.get("summary") or "")[:300], "zones": zl, "sources": sources, "resources": resources,
                     "reports": reports},
            "missing": missing, "blocking": not zl, "assumptions": assumptions, "risk": risk_by_zone(zl, reports)}


# ── the declaration is the first data ────────────────────────────────────

HAZARD_BAND = 5  # same band as core/signals.py: from here a zone threatens whatever is downstream


def _reports(raw: dict[str, Any], zones: list[dict[str, Any]], assumptions: list[str]) -> list[dict[str, Any]]:
    """What the description says is already happening, one entry per fact, tied to a zone that exists."""
    by_slug = {slugify(z["name"]): z["name"] for z in zones}
    out = []
    for r in raw.get("reports") or []:
        zone = by_slug.get(slugify(str((r or {}).get("zone") or "")))
        text = str((r or {}).get("text") or "").strip()
        if not zone or not text:
            continue
        try:
            sev = max(1, min(10, int(float(r.get("severity") or 0))))
        except (TypeError, ValueError):
            sev = 6
        try:
            people = max(0, int(float(r.get("people") or 0)))
        except (TypeError, ValueError):
            people = 0
        out.append({"zone": zone, "severity": sev, "text": text[:280], "place": str(r.get("place") or "").strip()[:80], "people": people})
    origins = [z["name"] for z in zones if z.get("is_origin")]
    if zones and not any(r["severity"] >= HAZARD_BAND and r["zone"] in origins for r in out):
        for name in origins:  # a crisis somebody bothers to declare has started somewhere
            out.insert(0, {"zone": name, "severity": 6, "text": f"Declarada por el coordinador: la amenaza ya está en {name}.", "place": "", "people": 0})
        if origins:
            assumptions.append(f"No dices cómo de grave está ahora: parto de severidad 6 en {', '.join(origins)} hasta que lleguen datos.")
    return out[:12]


def risk_by_zone(zones: list[dict[str, Any]], reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where it is now and when it reaches each other zone, from the declaration alone: the same reasoning the kernel
    applies to live data (core/signals.recompute_zone_estimates), so the preview matches what the crisis opens with."""
    now = {z["name"]: max([r["severity"] for r in reports if r["zone"] == z["name"]] + [0]) for z in zones}
    eta: dict[str, int] = {n: 0 for n, sev in now.items() if sev >= HAZARD_BAND}
    via: dict[str, str] = {}
    frontier = list(eta)
    while frontier:  # shortest travel time along the propagation graph
        a = min(frontier, key=lambda n: eta[n])
        frontier.remove(a)
        for t in next((z["to"] for z in zones if z["name"] == a), []):
            reach = eta[a] + int(t.get("delay_min") or 30)
            if t["name"] in now and reach < eta.get(t["name"], 10 ** 9):
                eta[t["name"]], via[t["name"]] = reach, a
                frontier.append(t["name"])
    worst = max(now.values(), default=0)
    out = []
    for z in zones:
        n, sev = z["name"], now[z["name"]]
        when = eta.get(n)
        threat = sev if sev else max(0, worst - 1) if when is not None else 0
        out.append({"zone": n, "severity": sev, "eta_min": when, "from": via.get(n), "threat": threat,
                    "level": "critical" if threat >= 7 else "warning" if threat >= 4 else "calm",
                    "label": f"{sev}/10 ahora" if sev >= HAZARD_BAND else f"llega en ~{when} min desde {via[n]}" if when else
                             f"{sev}/10, sin propagarse aún" if sev else "sin amenaza aguas arriba",
                    "people_at_stake": int(z.get("population") or 0)})
    return out


def seed(db: Any, c: Any, reports: list[dict[str, Any]]) -> list[str]:
    """The description is the first data of the crisis: each fact it states enters as a report signed by whoever
    declared it. From there the ordinary machinery does the rest at once — severity and countdown per zone,
    incidents, open needs, reflexes and the brains' first actions and plan — and every reading that arrives later
    (calls, sensors, media) corrects it: an estimate holds until fresher data says otherwise."""
    from valte.core.signals import upsert_signal
    from valte.models import Entity

    who = (c.config or {}).get("coordination_entity") or "cecopi"
    if db.get(Entity, (c.id, who)) is None:
        return []
    made = []
    for r in reports or []:
        text = r["text"] + (f" ({r['people']} personas)" if r.get("people") and str(r["people"]) not in r["text"] else "")
        sig, _ = upsert_signal(db, c, sig_id=None, t=None, source=who, channel="operator", content=text, is_noise=False,
                               claims=[{"hazard_type": c.hazard_type, "severity_hint": int(r["severity"])}], zone=r["zone"],
                               precision="street" if r.get("place") else "zone", location_text=r.get("place") or "",
                               summary="", perceived_by="operator")
        made.append(sig.id)
    return made


# ── HappyRobot reads it ──────────────────────────────────────────────────

TIMEOUT_S = 40
DONE = {"completed", "success", "succeeded", "finished"}
DEAD = {"failed", "error", "cancelled", "canceled"}


async def _parse_hr(text: str, workflow_id: str, extract_node: str) -> dict[str, Any]:
    run_id = await hr().trigger_run(workflow_id, {"text": text})
    t0 = time.monotonic()
    while time.monotonic() - t0 < TIMEOUT_S:
        await asyncio.sleep(1.5)
        status = str((await hr().get_run(run_id)).get("status") or "").lower()
        if status in DEAD:
            raise RuntimeError(f"run {status}")
        if status in DONE:
            out = await hr().node_output(run_id, extract_node)
            response = ((out or {}).get("data") or {}).get("response")
            if isinstance(response, str):
                response = json.loads(response)
            doc = (response or {}).get("crisis_json")
            doc = json.loads(doc) if isinstance(doc, str) else doc
            if not isinstance(doc, dict):
                raise RuntimeError("el run terminó sin salida legible")
            return doc
    raise TimeoutError("HappyRobot no respondió a tiempo")


async def draft(text: str) -> dict[str, Any]:
    """Text → a crisis the person can look over before launching it."""
    text = text.strip()
    with session_scope() as db:
        wf = registry.get(db, registry.CRISIS_PARSE) if registry.usable(db, registry.CRISIS_PARSE) else None
        target = (wf.workflow_id, (wf.node_ids or {}).get("extract")) if wf else None
    parsed_by, note = "local", ""
    raw: dict[str, Any] | None = None
    if target and target[1]:
        try:
            raw, parsed_by = await _parse_hr(text, *target), "happyrobot"
        except Exception as e:
            log.warning("crisis-parse failed, reading it locally: %s", e)
            note = f"HappyRobot no ha podido leerlo ({e}); lo he interpretado con las reglas locales."
    if raw is None:
        raw = parse_local(text)
    return {**normalize(raw, text), "parsed_by": parsed_by, "note": note}
