"""Post-run scorecard for the current kernel run.

Measures what the track judges: warning lead time per zone (alert vs wave
arrival), action quality (duplicates, rejections), reflex latency, and the
final population outcome vs the no-agent baseline."""

import json
import os
import sys
from collections import Counter
from datetime import datetime

import psycopg

# ground-truth wave arrivals for seed-42 dana-valencia (severity >= 6)
WAVE_ARRIVAL = {"chiva": "16:30", "torrent": "18:00", "paiporta": "18:45",
                "catarroja": "19:05", "alfafar": "19:10"}
BASELINE_RISK = {"chiva": 56.4, "torrent": 42.1, "paiporta": 34.1,
                 "catarroja": 23.7, "alfafar": 23.7}
REAL_ALERT = "20:11"


def hm(ts) -> str:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%H:%M")


def main():
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    rid = conn.execute("select id from runs order by started_at desc limit 1").fetchone()[0]

    actions = [r[0] for r in conn.execute(
        "select doc from actions where run_id=%s order by created_at", (rid,))]
    print(f"== ACTIONS: {len(actions)} total")
    print("   by verb:", dict(Counter(a["verb"] for a in actions)))
    print("   by status:", dict(Counter(a["status"] for a in actions)))
    dup_keys = Counter((a["actor"], a["verb"], tuple(sorted(a.get("target_zones") or [])))
                       for a in actions if a["actor"] != "system")
    dups = {k: c for k, c in dup_keys.items() if c > 1}
    print(f"   duplicate actor+verb+zones: {len(dups)}",
          {f"{k[0]}/{k[1]}": c for k, c in list(dups.items())[:5]})

    print("\n== WARNING LEAD TIME (alert sent vs wave arrival; real 2024 alert was 20:11)")
    alerts = [a for a in actions if a["verb"] == "send_es_alert"]
    first_alert_per_zone = {}
    for a in alerts:
        for z in a.get("target_zones") or []:
            t = hm(a["t"])
            if z not in first_alert_per_zone or t < first_alert_per_zone[z]:
                first_alert_per_zone[z] = t
    for z, wave in WAVE_ARRIVAL.items():
        alert = first_alert_per_zone.get(z)
        if alert:
            lead = (datetime.strptime(wave, "%H:%M") - datetime.strptime(alert, "%H:%M")).total_seconds() / 60
            mark = "BEFORE wave" if lead > 0 else "TOO LATE"
            print(f"   {z:<10} alert {alert} | wave {wave} | lead {lead:+.0f} min  [{mark}]")
        else:
            print(f"   {z:<10} NEVER ALERTED | wave {wave}")

    print("\n== POPULATION OUTCOME (final vs no-agent baseline)")
    for z in WAVE_ARRIVAL:
        row = conn.execute(
            "select doc->'population' from entities where run_id=%s and id=%s",
            (rid, f"civilians-{z}")).fetchone()
        p = row[0]
        base = BASELINE_RISK[z]
        print(f"   {z:<10} at_risk {p['at_risk_pct']:>5.1f}% (baseline {base}%)  "
              f"warned={p['warned']}  evac={p['evacuated_pct']:.0f}%")

    print("\n== SIGNALS")
    total = conn.execute("select count(*) from signals where run_id=%s", (rid,)).fetchone()[0]
    conf = dict(conn.execute(
        "select confidence, count(*) from signals where run_id=%s group by 1", (rid,)).fetchall())
    noise = conn.execute(
        "select count(*) from signals where run_id=%s and jsonb_array_length(doc->'claims')=0",
        (rid,)).fetchone()[0]
    print(f"   {total} ingested | confidence {conf} | noise stored: {noise}")

    print("\n== TRIPWIRES")
    for tw_id, status, doc in conn.execute(
            "select id, status, doc from tripwires where run_id=%s", (rid,)):
        fired = conn.execute(
            "select count(*) from actions where run_id=%s and doc->>'reasoning' like %s",
            (rid, f"Tripwire {tw_id}%")).fetchone()[0]
        print(f"   {tw_id:<24} {status:<8} fired {fired} action(s)")

    print("\n== SITUATION (final)")
    sit = conn.execute("select doc from situation where run_id=%s", (rid,)).fetchone()[0]
    print(f"   level {sit.get('emergency_level')}: {(sit.get('notes') or '')[:200]}")


if __name__ == "__main__":
    main()
