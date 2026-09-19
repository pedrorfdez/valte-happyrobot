import json

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from .config import settings

pool = ConnectionPool(settings.database_url, min_size=1, max_size=8,
                      kwargs={"row_factory": dict_row}, open=False)


def q(sql: str, params: tuple = (), one: bool = False):
    """Run a query in its own transaction; return rows (or one row)."""
    with pool.connection() as conn:
        cur = conn.execute(sql, params)
        if cur.description is None:
            return None
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def js(obj) -> Json:
    return Json(obj)


def current_run_id() -> str | None:
    row = q("select id from runs order by started_at desc limit 1", one=True)
    return str(row["id"]) if row else None
