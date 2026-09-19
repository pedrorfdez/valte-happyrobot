"""Live terminal view of the crisis system. Polls the kernel every 2 s.

  python3 scripts/watch.py            (kernel on localhost:8100)
  KERNEL=https://... python3 scripts/watch.py
"""

import json
import os
import sys
import time
import urllib.request

KERNEL = os.environ.get("KERNEL", "http://localhost:8100")
TOKEN = os.environ.get("WORLD_API_TOKEN", "")
BOLD, DIM, RED, YEL, GRN, CYA, END = "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[32m", "\033[36m", "\033[0m"


def get(path):
    req = urllib.request.Request(KERNEL + path,
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def sev_color(s):
    return RED if s >= 7 else YEL if s >= 4 else GRN


def risk_bar(pct, width=20):
    filled = round(pct / 100 * width)
    color = RED if pct > 25 else YEL if pct > 10 else GRN
    return color + "#" * filled + DIM + "." * (width - filled) + END


def render():
    run = get("/runs/current")
    state = get("/state")
    sit = state.get("situation") or {}
    tws = state.get("active_tripwires") or []
    acts = state.get("recent_actions") or []
    sigs = state.get("recent_signals") or []
    ents = {e["id"]: e for e in state.get("entities", [])}

    hazards = {}
    try:
        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            rid = c.execute("select id from runs order by started_at desc limit 1").fetchone()
            if rid:
                for z, s, t in c.execute(
                        "select zone, severity, trend from hazards where run_id=%s", (rid[0],)):
                    hazards[z] = (s, t)
    except Exception:
        pass

    out = []
    out.append(f"{BOLD}== VALTE CRISIS SYSTEM == level {sit.get('emergency_level', '-')}"
               f"  {DIM}{time.strftime('%H:%M:%S')}{END}")
    out.append(f"{DIM}run {str(run.get('id'))[:8]} '{run.get('notes') or run.get('scenario_id')}'"
               f" started {str(run.get('started_at'))[11:19]} UTC"
               f" | new run: POST /runs{END}")
    out.append(f"{DIM}{(sit.get('notes') or 'no situation yet')[:110]}{END}")
    out.append("")

    # no-agent baseline share of people in danger at end of run (seed 42)
    BASELINE_PCT = {"chiva": 56.4, "torrent": 42.1, "paiporta": 34.1,
                    "catarroja": 23.7, "alfafar": 23.7}
    zone_docs = {z["id"]: z for z in state.get("zones", [])}
    total_now = total_base = 0
    out.append(f"{BOLD}ZONES{END}          hazard(truth)    people in danger (if nobody acted)")
    for zid in ["chiva", "torrent", "paiporta", "catarroja", "alfafar"]:
        pop = (ents.get(f"civilians-{zid}") or {}).get("population") or {}
        total = pop.get("total", 0)
        hz = hazards.get(zid)
        if hz:
            hz_s = f"{sev_color(hz[0])}sev {hz[0]} {hz[1]:<7}{END}"
        else:
            # forecast: severe hazard upstream means a countdown, not calm
            zdoc = zone_docs.get(zid) or {}
            ups = [u for u in (zdoc.get("downstream_of") or []) if (hazards.get(u) or (0,))[0] >= 6]
            if ups:
                hz_s = f"{YEL}wave ~{zdoc.get('propagation_delay_min', '?')} min{END} "
            else:
                hz_s = f"{DIM}calm         {END}"
        warned = f"{GRN}WARNED{END}" if pop.get("warned") else f"{RED}unwarned{END}"
        people = round(total * pop.get("at_risk_pct", 0) / 100)
        base = round(total * BASELINE_PCT[zid] / 100)
        total_now += people; total_base += base
        color = RED if people > base * 0.5 else YEL if people > base * 0.15 else GRN
        out.append(f"  {zid:<12} {hz_s}  {color}{people:>6,}{END} {DIM}(vs ~{base:,}){END}"
                   f"  {warned}  evac {pop.get('evacuated_pct', 0):.0f}%")
    saved = total_base - total_now
    out.append(f"  {BOLD}{'TOTAL':<12}{END}                {GRN}{total_now:>6,}{END} "
               f"{DIM}(vs ~{total_base:,} if nobody acted -> ~{saved:,} people protected){END}")
    out.append("")
    out.append(f"{BOLD}RESPONDERS{END}")
    for eid in ["bomberos-torrent", "bomberos-valencia", "ume", "cruz-roja"]:
        e = ents.get(eid) or {}
        u = e.get("units") or {}
        asg = e.get("active_assignments") or []
        where = ", ".join(f"{a['units']}u->{a['zone']}" for a in asg) or "-"
        out.append(f"  {eid:<20} {u.get('available','?')}/{u.get('total','?')} units"
                   f"  [{e.get('status','?')}]  {DIM}{where}{END}")
    UNIT_VERBS = {"rescue", "pump_water", "shelter", "supplies", "wellness_check", "heavy_equipment"}
    ops = [a for a in acts if a["verb"] in UNIT_VERBS]
    if ops:
        out.append(f"  {DIM}operations: " + " | ".join(
            f"{a['verb']} {','.join(a.get('target_zones') or ['-'])} "
            f"({a['actor'].split('-')[-1]}, {'active' if a['status'] == 'in_progress' else a['status']})"
            for a in ops[:4]) + END)
    out.append("")
    out.append(f"{BOLD}TRIPWIRES{END} " + (", ".join(
        f"{CYA}{t['id']}{END}" for t in tws) or f"{DIM}none{END}"))
    out.append("")
    out.append(f"{BOLD}LAST ACTIONS{END}")
    for a in acts[:6]:
        color = YEL if a["status"] == "pending_approval" else GRN if a["status"] in ("executed", "approved") else DIM
        out.append(f"  {color}{a['status']:<17}{END} {a['actor'][:20]:<20} {a['verb']:<24}"
                   f" {DIM}{(a.get('reasoning') or '')[:55]}{END}")
    out.append("")
    out.append(f"{BOLD}LAST SIGNALS{END}")
    for s in sigs[:5]:
        conf = s.get("confidence", "?")
        c = GRN if conf == "high" else YEL if conf == "medium" else DIM
        out.append(f"  {c}{conf:<7}{END} {s['source'][:14]:<14} {s['location'].get('zone') or '-':<10}"
                   f" {DIM}{s.get('content', '')[:60]}{END}")
    return "\n".join(out)


def main():
    while True:
        try:
            frame = render()
        except Exception as e:
            frame = f"kernel unreachable: {e}"
        sys.stdout.write("\033[2J\033[H" + frame + "\n")
        sys.stdout.flush()
        time.sleep(2)


if __name__ == "__main__":
    main()
