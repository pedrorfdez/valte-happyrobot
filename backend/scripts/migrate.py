"""Apply migrations/*.sql in order against DATABASE_URL."""

import os
import sys
from pathlib import Path

import psycopg

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main():
    from kernel.config import settings
    with psycopg.connect(settings.database_url) as conn:
        for sql_file in sorted((BACKEND / "migrations").glob("*.sql")):
            print(f"applying {sql_file.name}")
            conn.execute(sql_file.read_text())
        conn.commit()
    print("migrations applied")


if __name__ == "__main__":
    main()
