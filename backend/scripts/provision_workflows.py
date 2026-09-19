"""Create/update the PedroD-* workflows in HappyRobot.

  uv run python scripts/provision_workflows.py --dry-run
  uv run python scripts/provision_workflows.py --only PedroD-ingest-calls
  uv run python scripts/provision_workflows.py            # all, idempotent
  uv run python scripts/provision_workflows.py --static-url https://xxxx.lhr.life   # bake the callback URL

Never touches a workflow that is not named PedroD-*: the client refuses.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valte.db import init_db  # noqa: E402
from valte.hr.client import HRClient  # noqa: E402
from valte.hr.provision import provision  # noqa: E402
from valte.hr.specs import Ctx, all_specs  # noqa: E402
from valte.settings import settings  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated workflow names")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-publish even if the spec did not change")
    ap.add_argument("--static-url", default="", help="bake this base URL into callback nodes instead of {{callback_base}}")
    args = ap.parse_args()

    if not settings.happyrobot_api_key:
        print("HAPPYROBOT_API_KEY is not set"); return 2
    if not settings.happyrobot_webhook_secret and not args.dry_run:
        print("HAPPYROBOT_WEBHOOK_SECRET is empty: set it first (it is the bearer HappyRobot sends to our callbacks)"); return 2

    init_db()
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    ctx = Ctx(secret=settings.happyrobot_webhook_secret or "<secret>", static_base=args.static_url.rstrip("/"))
    client = HRClient()
    failed = 0
    try:
        for spec in all_specs():
            if only and spec.name not in only:
                continue
            try:
                res = await provision(client, spec, ctx, force=args.force, dry_run=args.dry_run)
            except Exception as e:
                failed += 1
                print(f"✗ {spec.name}: {e}")
                continue
            if args.dry_run:
                print(f"── {spec.name} (exists: {res['exists']})")
                print(json.dumps(res["nodes"], ensure_ascii=False, indent=1).replace(ctx.secret, "<secret>")[:6000])
            else:
                extra = ""
                if res.get("missing_variables"):
                    extra += f" missing_variables={json.dumps(res['missing_variables'], ensure_ascii=False)[:300]}"
                if res.get("test_errors"):
                    extra += f" test_errors={json.dumps(res['test_errors'], ensure_ascii=False)[:300]}"
                print(f"✓ {spec.name}: {res['status']} {res.get('workflow_id', '')} live={res.get('live')}{extra}")
    finally:
        await client.aclose()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
