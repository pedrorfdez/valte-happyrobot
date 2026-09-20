"""Run the simulator inside the kernel process, controlled from the
dashboard. One simulation at a time; the engine runs in a daemon thread
and emits through the same public channel URLs as the CLI (perception
via HappyRobot webhooks, sensors via localhost)."""

import os
import sys
import threading

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import require_token

router = APIRouter(dependencies=[Depends(require_token)])

_lock = threading.Lock()
_state: dict = {"running": False, "engine": None, "error": None}


def _run_engine(scenario_id: str, speed: float, seed: int):
    try:
        # sensors and effects loop back over localhost inside the container
        port = os.environ.get("PORT", "8100")
        os.environ["KERNEL_SIGNALS_URL"] = f"http://127.0.0.1:{port}/signals"
        for repo_dir in ("/app", str(__import__("pathlib").Path(__file__).resolve().parents[3])):
            if repo_dir not in sys.path:
                sys.path.insert(0, repo_dir)
        from sim.emitters import make_emitter
        from sim.engine import Engine
        from sim.loader import load_scenario

        pack = load_scenario(scenario_id)
        engine = Engine(pack, speed=speed, seed=seed,
                        emitter=make_emitter("live"), tick_wall_s=1.0)
        _state["engine"] = engine
        engine.run()
        _state["error"] = None
    except Exception as e:
        _state["error"] = str(e)[:300]
    finally:
        _state["running"] = False
        _state["engine"] = None


@router.post("/sim/start")
def sim_start(body: dict = Body(default={})):
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "a simulation is already running; stop it first")
        _state["running"] = True
        _state["error"] = None
    t = threading.Thread(
        target=_run_engine,
        args=(body.get("scenario_id", "dana-valencia"),
              float(body.get("speed", 30)), int(body.get("seed", 42))),
        daemon=True)
    t.start()
    return {"started": True, "speed": body.get("speed", 30), "seed": body.get("seed", 42)}


@router.post("/sim/stop")
def sim_stop():
    eng = _state.get("engine")
    if not _state["running"] or eng is None:
        return {"running": False}
    eng.stop_requested = True
    return {"stopping": True}


@router.get("/sim/status")
def sim_status():
    eng = _state.get("engine")
    out = {"running": _state["running"], "error": _state["error"]}
    if eng is not None:
        try:
            out["scenario_t"] = eng.clock.now().isoformat()
            out["emitted"] = eng.emitted
        except Exception:
            pass
    return out
