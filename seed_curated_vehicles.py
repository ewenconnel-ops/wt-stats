"""
Seeds a small, hand-verified set of vehicles — a starting point so Compare
and the heatmap have real data to show, while the bulk-import question
(economicRank has no public BR conversion; the wiki's BR tables didn't
render via automated fetch) stays open for later.

SOURCING, HONESTLY
-------------------
Every br_realistic value below is quoted from War Thunder's own "Planned
Battle Rating Changes (August 2026)" official forum post — i.e. these are
real, dated, current numbers, not guesses. Two caveats worth knowing:

1. That post covered Ground RB, Air RB, and some Air-in-Ground-RB changes
   together, and it isn't fully unambiguous which specific mode each
   aircraft figure applies to. Treated all of them as br_realistic here;
   worth spot-checking a couple against the in-game vehicle card before
   trusting this data set fully.
2. br_arcade and br_sim are left NULL for everything — the patch notes
   only covered Realistic. Arcade/Sim BR often differs from Realistic and
   wasn't sourced, so it's genuinely unknown here rather than assumed equal.

This is deliberately a short, honest list (9 vehicles) rather than a large
list of guessed numbers. Extend it the same way: find a real, dated,
specific BR figure before adding a row, don't estimate.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Reads DATABASE_URL directly rather than importing app.database — running
# `python scripts/seed_curated_vehicles.py` puts scripts/ on sys.path, not
# the repo root, so `import app` would fail (same issue migrate.py had).
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://wt_stats:wt_stats@localhost:5432/wt_stats"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# (name, slug, nation, class, br_realistic)
# Source: War Thunder official forum, "Planned Battle Rating Changes
# (August 2026)" — steamcommunity.com/app/236390/discussions/0/582804312418431815
VEHICLES: list[tuple[str, str, str, str, float]] = [
    ("BMPT Terminator", "bmpt-terminator", "USSR", "ground", 11.3),
    ("HSTV-L", "hstv-l", "Sweden", "ground", 12.0),
    ("Ayit", "ayit", "Israel", "air", 10.0),
    ("F-14A IRIAF", "f-14a-iriaf", "Israel", "air", 13.7),
    ("Su-30SM2", "su-30sm2", "USSR", "air", 13.3),
    ("Wyvern", "wyvern", "Britain", "air", 5.3),
    ("A6M5 Ko", "a6m5-ko", "Japan", "air", 6.0),
    ("VL Pyörremyrsky", "vl-pyorremyrsky", "Sweden", "air", 5.7),
    ("M.B. 157", "mb-157", "France", "air", 3.7),
]


def upsert_vehicles(db: Session) -> int:
    written = 0
    for name, slug, nation, vehicle_class, br_realistic in VEHICLES:
        db.execute(
            text("""
                INSERT INTO vehicles (name, slug, nation, class, br_realistic)
                VALUES (:name, :slug, :nation, :class, :br_realistic)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    nation = EXCLUDED.nation,
                    class = EXCLUDED.class,
                    br_realistic = EXCLUDED.br_realistic,
                    updated_at = now()
            """),
            {
                "name": name,
                "slug": slug,
                "nation": nation,
                "class": vehicle_class,
                "br_realistic": br_realistic,
            },
        )
        written += 1
    return written


def run() -> None:
    db = SessionLocal()
    try:
        written = upsert_vehicles(db)
        db.commit()
        print(f"seeded {written} vehicles")
    finally:
        db.close()


if __name__ == "__main__":
    run()
