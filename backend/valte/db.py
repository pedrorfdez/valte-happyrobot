import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from valte.settings import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 15} if is_sqlite else {},
        pool_pre_ping=not is_sqlite,
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


engine = _make_engine(settings.valte_db_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)

# One lock per crisis: routes run in the threadpool and the engine loop in
# another thread, and they all mutate the same world.
_locks: dict[str, threading.RLock] = defaultdict(threading.RLock)


def crisis_lock(crisis_id: str) -> threading.RLock:
    return _locks[crisis_id]


def init_db() -> None:
    from valte import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all never alters an existing table. During the hackathon the
    models move faster than the file on disk, so add what is missing."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {col["name"] for col in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
                default = getattr(col.default, "arg", None)
                if isinstance(default, bool):
                    ddl += f" DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    ddl += f" DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += f" DEFAULT '{default}'"
                conn.execute(text(ddl))


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit on success and only then publish the events it produced."""
    from valte import bus

    db = SessionLocal()
    try:
        yield db
        db.commit()
        for ev in db.info.pop("pending_events", []):
            bus.publish(ev["crisis_id"], ev)
    except Exception:
        db.rollback()
        db.info.pop("pending_events", None)
        raise
    finally:
        db.close()
