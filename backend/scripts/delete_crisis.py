"""Remove one crisis and everything that hangs from it (rehearsals, mistakes).

  uv run python scripts/delete_crisis.py <crisis-id-or-code>
  uv run python scripts/delete_crisis.py --all     # every catastrophe; global lessons stay
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from valte.db import Base, init_db, session_scope  # noqa: E402
from valte.models import Crisis, Lesson  # noqa: E402


def wipe(db, c: Crisis, *, keep_global_lessons: bool) -> tuple[str, str]:
    cid, name = c.id, c.name
    for table in reversed(Base.metadata.sorted_tables):
        if "crisis_id" in table.c:
            db.execute(table.delete().where(table.c.crisis_id == cid))
    if keep_global_lessons:
        db.execute(Lesson.__table__.delete().where(Lesson.source_crisis_id == cid, Lesson.scope == "crisis"))
    else:
        db.execute(Lesson.__table__.delete().where(Lesson.source_crisis_id == cid))
    db.delete(c)
    return name, cid


def main() -> None:
    init_db()
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__.strip())
        raise SystemExit(0 if args else 2)
    all_of_them = args[0] == "--all"
    with session_scope() as db:
        if all_of_them:
            crises = list(db.scalars(select(Crisis)))
            if not crises:
                print("no crises")
                return
            for c in crises:
                name, cid = wipe(db, c, keep_global_lessons=True)
                print(f"deleted {name} ({cid})")
            return
        ref = args[0]
        c = db.get(Crisis, ref) or db.scalars(select(Crisis).where(Crisis.code == ref)).first()
        if c is None:
            raise SystemExit(f"no such crisis: {ref}")
        name, cid = wipe(db, c, keep_global_lessons=False)
    print(f"deleted {name} ({cid})")


if __name__ == "__main__":
    main()
