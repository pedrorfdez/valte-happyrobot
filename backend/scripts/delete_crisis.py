"""Remove one crisis and everything that hangs from it (rehearsals, mistakes). Lessons it taught go too.

  uv run python scripts/delete_crisis.py <crisis-id-or-code>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from valte.db import Base, init_db, session_scope  # noqa: E402
from valte.models import Crisis, Lesson  # noqa: E402

init_db()
ref = sys.argv[1]
with session_scope() as db:
    c = db.get(Crisis, ref) or db.scalars(select(Crisis).where(Crisis.code == ref)).first()
    if c is None:
        raise SystemExit(f"no such crisis: {ref}")
    cid, name = c.id, c.name
    for table in reversed(Base.metadata.sorted_tables):
        if "crisis_id" in table.c:
            db.execute(table.delete().where(table.c.crisis_id == cid))
    db.execute(Lesson.__table__.delete().where(Lesson.source_crisis_id == cid))
    db.delete(c)
print(f"deleted {name} ({cid})")
