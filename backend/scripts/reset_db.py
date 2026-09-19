"""Wipe crises, signals, actions, lessons... but KEEP the HappyRobot workflow registry.

  uv run python scripts/reset_db.py            # everything except hr_workflows
  uv run python scripts/reset_db.py --keep-lessons

Stop the server first (or restart it afterwards): it caches nothing, but a
crisis that is mid-tick would be recreated half-way.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valte.db import Base, engine, init_db  # noqa: E402

KEEP = {"hr_workflows"} | ({"lessons"} if "--keep-lessons" in sys.argv else set())

init_db()
with engine.begin() as conn:
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEEP:
            n = conn.execute(table.delete()).rowcount
            if n:
                print(f"  {table.name}: {n} rows deleted")
print("kept:", ", ".join(sorted(KEEP)))
