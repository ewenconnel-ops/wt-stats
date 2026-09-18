"""
Seeds the vehicles table from CSV files harvested live from the official
War Thunder Wiki's vehicle browser (wiki.warthunder.com), Realistic Battles
mode. Real, current, per-vehicle decimal BR — not derived or guessed.

Each CSV has columns: id,name,country,rank,br_realistic
- id is the wiki's own vehicle slug (e.g. "us_m4a1_sherman") — used directly
  as our `vehicles.slug` since it's already unique and url-safe.
- br_arcade and br_sim are NOT in these files (only Realistic was
  harvested) and are left NULL. Extend the same way later if wanted:
  switch the wiki's mode dropdown to AB/SB and re-harvest.

Place the 5 CSVs in a `data/` folder next to this script before running:
  data/ground_vehicles_rb.csv
  data/air_vehicles_rb.csv
  data/helicopters_rb.csv
  data/bluewater_fleet_rb.csv
  data/coastal_fleet_rb.csv

Run:
    python scripts/seed_from_wiki_csv.py
"""
from __future__ import annotations

import csv
import os
import pathlib

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://wt_stats:wt_stats@localhost:5432/wt_stats"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

# (filename, vehicle class) — helicopters count as "air" in our 3-way
# ground/air/naval schema; both fleet categories count as "naval".
FILES: list[tuple[str, str]] = [
    ("ground_vehicles_rb.csv", "ground"),
    ("air_vehicles_rb.csv", "air"),
    ("helicopters_rb.csv", "air"),
    ("bluewater_fleet_rb.csv", "naval"),
    ("coastal_fleet_rb.csv", "naval"),
]

COUNTRY_DISPLAY_NAMES = {
    "usa": "USA",
    "germany": "Germany",
    "ussr": "USSR",
    "britain": "Britain",
    "japan": "Japan",
    "china": "China",
    "italy": "Italy",
    "france": "France",
    "sweden": "Sweden",
    "israel": "Israel",
}


def load_rows(filename: str, vehicle_class: str) -> list[dict]:
    path = DATA_DIR / filename
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                br = float(row["br_realistic"])
            except (KeyError, ValueError):
                continue
            rows.append({
                "slug": row["id"],
                "name": row["name"],
                "nation": COUNTRY_DISPLAY_NAMES.get(row["country"], row["country"]),
                "class": vehicle_class,
                "br_realistic": br,
            })
    return rows


def upsert(db, rows: list[dict]) -> int:
    written = 0
    for r in rows:
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
            r,
        )
        written += 1
    return written


def run() -> None:
    db = SessionLocal()
    total = 0
    try:
        for filename, vehicle_class in FILES:
            path = DATA_DIR / filename
            if not path.exists():
                print(f"skipping {filename}: not found in {DATA_DIR}")
                continue
            rows = load_rows(filename, vehicle_class)
            written = upsert(db, rows)
            db.commit()
            print(f"{filename}: seeded {written} vehicles")
            total += written
        print(f"done — {total} vehicles total")
    finally:
        db.close()


if __name__ == "__main__":
    run()
