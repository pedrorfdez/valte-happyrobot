"""Simulator CLI.

  python -m sim validate --scenario dana-valencia
  python -m sim run --scenario dana-valencia --speed 30 --seed 42 --emit console
"""

import argparse
import json
import sys

from .emitters import make_emitter
from .engine import Engine
from .loader import load_scenario


def main():
    p = argparse.ArgumentParser(prog="sim")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="load and validate a scenario pack")
    pv.add_argument("--scenario", required=True)

    pr = sub.add_parser("run", help="run a scenario")
    pr.add_argument("--scenario", required=True)
    pr.add_argument("--speed", type=float, default=30.0,
                    help="scenario minutes per wall minute (default 30)")
    pr.add_argument("--seed", type=int, default=42, help="noise RNG seed")
    pr.add_argument("--emit", default="console",
                    help="console | file:<path> | live (URLs from env, see emitters.py)")
    pr.add_argument("--tick", type=float, default=1.0, help="wall seconds per tick")
    pr.add_argument("--truth", default=None, metavar="PATH",
                    help="also log normalized ground-truth signals (with claims) to this JSONL, for scoring perception")

    args = p.parse_args()

    try:
        pack = load_scenario(args.scenario)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    if args.cmd == "validate":
        s = pack["scenario"]
        print(f"OK: {s['name']}")
        print(f"  window: {s['time']['start']} -> {s['time']['end']}")
        print(f"  zones: {len(pack['zones'])} | entities: {len(pack['entities'])} "
              f"| timeline entries: {len(pack['timeline'])} "
              f"| noise sources: {len(pack['noise']['sources'])}")
        return

    emitter = make_emitter(args.emit)
    engine = Engine(pack, speed=args.speed, seed=args.seed, emitter=emitter,
                    tick_wall_s=args.tick, truth_path=args.truth)
    print(f"Running {pack['scenario']['id']} at {args.speed}x, seed {args.seed}. Ctrl-C to stop.")
    try:
        summary = engine.run()
    except KeyboardInterrupt:
        summary = engine.world.summary(engine.clock.now())
        print("\ninterrupted")
    finally:
        emitter.close()

    print(f"\n== RUN SUMMARY ({summary['t'][11:16]}) ==")
    print(f"signals emitted: {engine.emitted}")
    for h in summary["hazards"]:
        print(f"hazard {h['id']}: zone={h['zone']} severity={h['severity']} trend={h['trend']}")
    for zid, pop in summary["population"].items():
        print(f"population {zid}: warned={pop['warned']} at_risk={pop['at_risk_pct']:.1f}% "
              f"evacuated={pop['evacuated_pct']:.0f}%")
    if summary["entities_status"]:
        print("entity status:", summary["entities_status"])


if __name__ == "__main__":
    main()
