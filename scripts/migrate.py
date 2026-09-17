"""
Applies every .sql file in migrations/, in filename order, using the same
DATABASE_URL the app itself uses. Safe to run on every deploy: each
statement's own "already exists" error is caught and skipped rather than
failing the whole run, so re-running against an already-migrated database
is a no-op.

Run manually:
    python scripts/migrate.py

Run automatically on Render: set the build command to
    pip install -r requirements.txt && python scripts/migrate.py
"""
from __future__ import annotations

import pathlib
import re

import psycopg

from app.database import DATABASE_URL

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent / "migrations"

# app/database.py's DATABASE_URL is a SQLAlchemy URL (postgresql+psycopg://...);
# psycopg.connect wants the plain libpq form (postgresql://...).
PLAIN_URL = re.sub(r"^postgresql\+psycopg://", "postgresql://", DATABASE_URL)


def split_statements(sql: str) -> list[str]:
    """Naive split on ';' — fine for these migration files (no functions/triggers
    with embedded semicolons). Revisit if a future migration needs those."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def run() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("no migration files found in", MIGRATIONS_DIR)
        return

    with psycopg.connect(PLAIN_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            for path in files:
                print(f"applying {path.name}")
                for statement in split_statements(path.read_text()):
                    try:
                        cur.execute(statement)
                    except psycopg.errors.DuplicateObject:
                        print(f"  already exists, skipping: {statement[:60]}...")
                    except psycopg.errors.DuplicateTable:
                        print(f"  already exists, skipping: {statement[:60]}...")
    print("migrations complete")


if __name__ == "__main__":
    run()
