"""Valte · Mundo exterior — the light app that plays the outside world.

Press Start and it begins sending data to the kernel (one crisis or several
at once: each Start adds a crisis to the stack, nothing is replaced): 112 calls, social
posts, news bulletins and gauge readings, plus the things that go wrong
mid-run (a gauge dies, a bridge collapses, someone stops answering).
It follows the kernel's scenario clock, so pause, speed and the automatic
slow-motion during a live call are all respected.

  cd simulator && uv run --project ../backend uvicorn app:app --port 8030
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

BACKEND = os.environ.get("VALTE_BACKEND", "http://localhost:8010").rstrip("/")
DASHBOARD = os.environ.get("VALTE_DASHBOARD", f"{BACKEND}/app/")
PAGE = Path(__file__).with_name("index.html")


class Feed:
    """One crisis this app is feeding. Several run side by side: starting a new one never touches the others."""

    def __init__(self, crisis_id: str, pack: str, timeline: list[dict[str, Any]], offset_min: float, header: dict[str, Any]) -> None:
        self.crisis_id, self.pack, self.timeline = crisis_id, pack, timeline
        self.offset_min = offset_min          # scenario minutes already elapsed when we attached
        self.sent: dict[int, str] = {}        # item index -> result
        self.running = True
        self.header: dict[str, Any] = header
        self.log: list[dict[str, str]] = []

    def say(self, text: str, kind: str = "info") -> None:
        self.log.append({"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "text": text})
        del self.log[:-200]

    @property
    def now_min(self) -> float:
        return float((self.header.get("clock") or {}).get("elapsed_min", 0)) - self.offset_min

    def summary(self) -> dict[str, Any]:
        h, clock = self.header, self.header.get("clock") or {}
        return {"id": self.crisis_id, "code": h.get("code"), "name": h.get("name"), "status": h.get("status"),
                "severity": h.get("severity"), "clock": clock, "running": self.running, "pack": self.pack,
                "sent": len(self.sent), "total": len(self.timeline)}


class World:
    def __init__(self) -> None:
        self.feeds: dict[str, Feed] = {}      # insertion order = the stack, oldest first
        self.backend_ok = False
        self.lock = asyncio.Lock()

    def feed(self, crisis_id: str | None) -> Feed:
        """The feed a control refers to; without an id, the most recently started one."""
        if crisis_id and crisis_id in self.feeds:
            return self.feeds[crisis_id]
        if not crisis_id and self.feeds:
            return next(reversed(self.feeds.values()))
        raise HTTPException(status_code=404, detail="esta app no está alimentando esa crisis")


world = World()
http = httpx.AsyncClient(timeout=15.0)


def label(item: dict[str, Any]) -> str:
    if item["kind"] == "raw_input":
        p = item["payload"]
        return p.get("transcript") or p.get("text") or f"{p.get('headline', '')} — {p.get('body', '')}"
    if item["kind"] == "sensor":
        return item["content"]
    return item.get("note") or item.get("op", "")


def icon(item: dict[str, Any]) -> str:
    return {"call": "☎ 112", "social": "＠ Redes", "news": "▤ Medios"}.get(item.get("channel", ""), "") or \
        {"sensor": "◉ Sensor", "world": "⚠ Mundo"}.get(item["kind"], item["kind"])


async def send(cid: str, item: dict[str, Any]) -> str:
    if item["kind"] == "world":
        body = {k: v for k, v in item.items() if k not in ("at_min", "kind", "op")}
        r = await http.post(f"{BACKEND}/crises/{cid}/sim/inject", json={"kind": item["op"], **body})
    elif item["kind"] == "sensor":
        r = await http.post(f"{BACKEND}/crises/{cid}/inputs", json={
            "channel": "sensor", "source": item["source"], "zone": item.get("zone"),
            "severity": item.get("severity"), "content": item["content"]})
    else:
        r = await http.post(f"{BACKEND}/crises/{cid}/inputs", json={
            "channel": item["channel"], "source": item["source"], "payload": item["payload"],
            "fallback": item.get("fallback")})
    r.raise_for_status()
    res = r.json()
    return str(res.get("id") or res.get("injected") or res.get("dropped") or "ok")


async def tick(feed: Feed) -> None:
    r = await http.get(f"{BACKEND}/crises/{feed.crisis_id}")
    if r.status_code == 404:  # the kernel was reset under us: forget that crisis
        world.feeds.pop(feed.crisis_id, None)
        return
    h = feed.header = r.json()
    if h.get("status") != "active":
        if feed.running:
            feed.say("La crisis se ha cerrado: dejo de enviar.", "warn")
        feed.running = False
        return
    if not feed.running or h["clock"]["paused"]:
        return
    for i, item in enumerate(feed.timeline):
        if i in feed.sent or item["at_min"] > feed.now_min:
            continue
        try:
            feed.sent[i] = await send(feed.crisis_id, item)
            feed.say(f"{icon(item)} → {label(item)[:110]}", "sent")
        except Exception as e:  # keep the world turning; show what failed
            feed.sent[i] = "error"
            feed.say(f"No se pudo enviar ({icon(item)}): {e}", "error")
    if feed.timeline and len(feed.sent) == len(feed.timeline):
        feed.say("Guion completo: no queda nada por enviar.", "info")
        feed.running = False


async def loop() -> None:
    while True:
        await asyncio.sleep(1.0)
        try:
            world.backend_ok = (await http.get(f"{BACKEND}/health")).status_code == 200
        except Exception:
            world.backend_ok = False
            continue
        async with world.lock:
            for feed in list(world.feeds.values()):  # every crisis keeps its own pace; one failing does not stop the rest
                try:
                    await tick(feed)
                except Exception as e:
                    feed.say(f"Sin conexión con el backend: {e}", "error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(loop())
    yield
    task.cancel()
    await http.aclose()


app = FastAPI(title="Valte · Mundo exterior", lifespan=lifespan)


class StartIn(BaseModel):
    pack: str = "riada-paiporta"
    speed: float = 20
    crisis_id: str | None = None  # feed a crisis declared from the dashboard instead of creating one
    resume: bool = True           # False: attach without touching its clock (it stays paused if it was)
    skip_elapsed: bool = False    # re-attaching to a crisis this script was already feeding: do not replay what is past


class SpeedIn(BaseModel):
    speed: float
    crisis_id: str | None = None


class InjectIn(BaseModel):
    crisis_id: str | None = None
    kind: str
    zone: str | None = None
    entity: str | None = None
    source: str | None = None
    resource: str | None = None
    qty: float | None = None
    severity: int | None = None
    note: str = ""
    channel: str = "call"
    content: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/status")
async def status(crisis_id: str | None = None) -> dict[str, Any]:
    crises, packs = [], []
    try:
        crises = (await http.get(f"{BACKEND}/crises", params={"status": "active"})).json()
        packs = (await http.get(f"{BACKEND}/packs")).json()
    except Exception:
        pass
    sel = world.feeds.get(crisis_id or "") or (next(reversed(world.feeds.values())) if world.feeds else None)
    return {
        "backend": BACKEND, "backend_ok": world.backend_ok, "dashboard": DASHBOARD, "packs": packs,
        "feeds": [f.summary() for f in reversed(world.feeds.values())],   # newest on top of the stack
        "crises": [c for c in crises if c["id"] not in world.feeds],       # active in the kernel, not fed by this app
        "selected": sel.crisis_id if sel else None, "crisis": sel.header if sel else None,
        "running": sel.running if sel else False, "sent": len(sel.sent) if sel else 0,
        "total": len(sel.timeline) if sel else 0,
        "items": [{"i": i, "at_min": it["at_min"], "icon": icon(it), "label": label(it)[:160],
                   "status": "error" if sel.sent.get(i) == "error" else "sent" if i in sel.sent
                   else "next" if it["at_min"] <= sel.now_min + 5 else "pending", "ref": sel.sent.get(i)}
                  for i, it in enumerate(sel.timeline)] if sel else [],
        "log": sel.log[-40:][::-1] if sel else [],
    }


@app.post("/api/start")
async def start(body: StartIn) -> dict[str, Any]:
    """Adds a crisis to the stack. Whatever was already being fed keeps running."""
    async with world.lock:
        if body.crisis_id and body.crisis_id in world.feeds:  # already ours: carry on where it was, do not resend
            feed = world.feeds[body.crisis_id]
            await http.post(f"{BACKEND}/crises/{feed.crisis_id}/clock", json={"speed": body.speed, "paused": False})
            feed.running = True
            feed.say("Reanudado.", "info")
            return {"crisis_id": feed.crisis_id, "code": feed.header.get("code")}
        try:
            if body.crisis_id:
                h = (await http.get(f"{BACKEND}/crises/{body.crisis_id}")).json()
                await http.post(f"{BACKEND}/crises/{body.crisis_id}/feed", json={"external": True})
                if body.resume:
                    await http.post(f"{BACKEND}/crises/{body.crisis_id}/clock", json={"speed": body.speed, "paused": False})
                offset = float(h["clock"]["elapsed_min"])
            else:
                r = await http.post(f"{BACKEND}/crises", json={"pack": body.pack, "speed": body.speed,
                                                                "external_feed": True, "start": True})
                r.raise_for_status()
                h, offset = r.json(), 0.0
            # Each crisis gets its own script: the pack's when it fits, otherwise one generated from its zones and
            # hazard (a wildfire declared from the wizard must not be told about a flood).
            t = await http.get(f"{BACKEND}/crises/{h['id']}/timeline")
            t.raise_for_status()
            timeline = t.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"backend: {e}")
        feed = world.feeds[h["id"]] = Feed(h["id"], body.pack, timeline, 0.0 if body.skip_elapsed else offset, h)
        if body.skip_elapsed:
            feed.sent = {i: "antes" for i, it in enumerate(timeline) if it["at_min"] <= offset}
        feed.say(f"START · {h['name']} ({h['code']}) a {body.speed:g}×. {len(timeline)} eventos en el guion. "
                 f"{len(world.feeds)} crisis en marcha.", "info")
        return {"crisis_id": h["id"], "code": h["code"]}


async def _clock(feed: Feed, **body: Any) -> None:
    await http.post(f"{BACKEND}/crises/{feed.crisis_id}/clock", json=body)


@app.post("/api/pause")
async def pause(crisis_id: str | None = None) -> dict[str, Any]:
    feed = world.feed(crisis_id)
    await _clock(feed, paused=True)
    feed.say("Pausa: el reloj del escenario se detiene.", "info")
    return {"paused": True}


@app.post("/api/resume")
async def resume(crisis_id: str | None = None) -> dict[str, Any]:
    feed = world.feed(crisis_id)
    await _clock(feed, paused=False)
    feed.running = True
    feed.say("Reanudado.", "info")
    return {"paused": False}


@app.post("/api/speed")
async def speed(body: SpeedIn) -> dict[str, Any]:
    feed = world.feed(body.crisis_id)
    await _clock(feed, speed=body.speed)
    feed.say(f"Velocidad {body.speed:g}×.", "info")
    return {"speed": body.speed}


@app.post("/api/stop")
async def stop(crisis_id: str | None = None, close: bool = False) -> dict[str, Any]:
    """Stops feeding ONE crisis (and optionally closes it in the kernel). The others are not touched."""
    feed = world.feed(crisis_id)
    feed.running = False
    if close:
        await http.post(f"{BACKEND}/crises/{feed.crisis_id}/close")
        feed.say("Crisis cerrada: el sistema guarda lo aprendido para la próxima.", "info")
    else:
        feed.say("Envío detenido.", "info")
    return {"running": False}


@app.post("/api/remove")
async def remove(crisis_id: str) -> dict[str, Any]:
    """Take a crisis off this app's stack. It stays in the kernel exactly as it is."""
    world.feeds.pop(crisis_id, None)
    return {"removed": crisis_id}


@app.post("/api/inject")
async def inject(body: InjectIn) -> dict[str, Any]:
    """Something unscripted happens: the judges' '¿y si…?'."""
    feed = world.feed(body.crisis_id)
    r = await http.post(f"{BACKEND}/crises/{feed.crisis_id}/sim/inject",
                        json=body.model_dump(exclude_none=True, exclude={"crisis_id"}))
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=r.text[:300])
    feed.say(f"⚠ Inyectado: {body.kind} {body.zone or body.entity or body.source or ''} {body.note or body.content}"[:140], "sent")
    return r.json()
