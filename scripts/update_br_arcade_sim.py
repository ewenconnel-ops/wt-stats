"""
Fills in vehicles.br_arcade and vehicles.br_sim, harvested from the same
wiki.warthunder.com List view as the original br_realistic seed — just
with the mode dropdown switched to Arcade Battles / Simulator Battles.

MUST run AFTER seed_from_wiki_csv.py — this only UPDATEs existing rows by
slug, it doesn't insert new vehicles.

Naval (Bluewater + Coastal Fleet) genuinely has no Simulator Battles mode
in War Thunder, so there's no *_sb.csv for those two — br_sim stays NULL
for every naval vehicle, correctly, not a gap in the data.

Place the 8 CSVs in data/ before running:
  data/ground_vehicles_ab.csv   data/ground_vehicles_sb.csv
  data/air_vehicles_ab.csv      data/air_vehicles_sb.csv
  data/helicopters_ab.csv       data/helicopters_sb.csv
  data/bluewater_fleet_ab.csv   (no sim file — naval has no Sim mode)
  data/coastal_fleet_ab.csv     (no sim file — naval has no Sim mode)

Run:
    python scripts/update_br_arcade_sim.py
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

# (filename, column to update)
FILES: list[tuple[str, str]] = [
    ("ground_vehicles_ab.csv", "br_arcade"),
    ("ground_vehicles_sb.csv", "br_sim"),
    ("air_vehicles_ab.csv", "br_arcade"),
    ("air_vehicles_sb.csv", "br_sim"),
    ("helicopters_ab.csv", "br_arcade"),
    ("helicopters_sb.csv", "br_sim"),
    ("bluewater_fleet_ab.csv", "br_arcade"),
    ("coastal_fleet_ab.csv", "br_arcade"),
]


def run() -> None:
    db = SessionLocal()
    total_updated = 0
    try:
        for filename, column in FILES:
            path = DATA_DIR / filename
            if not path.exists():
                print(f"skipping {filename}: not found in {DATA_DIR}")
                continue

            updated = 0
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        br = float(row[column])
                    except (KeyError, ValueError):
                        continue
                    result = db.execute(
                        text(f"UPDATE vehicles SET {column} = :br, updated_at = now() WHERE slug = :slug"),
                        {"br": br, "slug": row["id"]},
                    )
                    updated += result.rowcount
            db.commit()
            print(f"{filename}: updated {updated} vehicles' {column}")
            total_updated += updated

        print(f"done — {total_updated} field updates total")
    finally:
        db.close()


if __name__ == "__main__":
    run()
