"""
Seeds vehicle_stats_daily from a real aggregate dataset pulled live from
StatShark's own site-wide vehicle statistics (statshark.net/globalstats),
via their public API endpoint api/misc/getGlobalUserStats. This is real,
current, large-sample data (games in the thousands to hundreds of
thousands per vehicle) — not synthetic, not derived.

MUST run AFTER seed_from_wiki_csv.py — this looks up each vehicle by slug
in the already-seeded `vehicles` table and skips anything not found.

Source JSON shape: {"vehicle_stats": {"arcade": [...], "historical": [...],
"simulation": [...]}}, each entry: {name, games, spawns, rp, sl, air_kills,
deaths, victories, defeats, ground_kills, naval_kills}. "historical" is
War Thunder's internal name for Realistic Battles.

`name` matches our `vehicles.slug` in 3,173 of 3,180 cases once
lowercased (verified directly against the wiki-sourced vehicle CSVs) —
the small remainder are vehicles StatShark tracks that aren't in our
current vehicle catalog (or vice versa), and are simply skipped.

No smoothing is applied here (unlike the aggregator.py Bayesian-shrinkage
path meant for our own future collector): sample sizes in this dataset are
already large enough per vehicle that raw win rate is meaningful as-is.

Place the JSON file at data/statshark_vehicle_stats.json before running.

Run:
    python scripts/seed_vehicle_stats_from_statshark.py
"""
from __future__ import annotations

import json
import os
import pathlib
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://wt_stats:wt_stats@localhost:5432/wt_stats"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

DATA_PATH = pathlib.Path(__file__).parent.parent / "data" / "statshark_vehicle_stats.json"

# StatShark's mode keys -> our schema's mode enum
MODE_MAP = {"arcade": "arcade", "historical": "realistic", "simulation": "simulator"}


def compute_row(entry: dict) -> dict | None:
    games = entry.get("games") or 0
    victories = entry.get("victories") or 0
    defeats = entry.get("defeats") or 0
    deaths = entry.get("deaths") or 0
    kills = (entry.get("air_kills") or 0) + (entry.get("ground_kills") or 0) + (entry.get("naval_kills") or 0)

    decided = victories + defeats
    if decided == 0 or games == 0:
        return None

    return {
        "win_rate": round(100.0 * victories / decided, 2),
        "kd_ratio": round(kills / deaths, 2) if deaths else round(float(kills), 2),
        "avg_kills": round(kills / games, 2),
        "sample_size": games,
    }


def load_slug_to_id(db) -> dict[str, int]:
    rows = db.execute(text("SELECT id, slug FROM vehicles")).all()
    return {slug.lower(): vid for vid, slug in rows}


def run() -> None:
    with DATA_PATH.open(encoding="utf-8") as f:
        payload = json.load(f)

    db = SessionLocal()
    try:
        slug_to_id = load_slug_to_id(db)
        today = date.today()
        total_written = 0
        total_skipped = 0

        for source_mode, our_mode in MODE_MAP.items():
            entries = payload.get("vehicle_stats", {}).get(source_mode, [])
            written = 0
            for entry in entries:
                vehicle_id = slug_to_id.get(str(entry.get("name", "")).lower())
                if vehicle_id is None:
                    total_skipped += 1
                    continue
                stats = compute_row(entry)
                if stats is None:
                    total_skipped += 1
                    continue

                db.execute(
                    text("""
                        INSERT INTO vehicle_stats_daily
                            (vehicle_id, mode, date, win_rate, kd_ratio, avg_kills, sample_size, raw_win_rate)
                        VALUES
                            (:vehicle_id, :mode, :date, :win_rate, :kd_ratio, :avg_kills, :sample_size, :win_rate)
                        ON CONFLICT (vehicle_id, mode, date) DO UPDATE SET
                            win_rate = EXCLUDED.win_rate,
                            kd_ratio = EXCLUDED.kd_ratio,
                            avg_kills = EXCLUDED.avg_kills,
                            sample_size = EXCLUDED.sample_size,
                            raw_win_rate = EXCLUDED.raw_win_rate
                    """),
                    {
                        "vehicle_id": vehicle_id,
                        "mode": our_mode,
                        "date": today,
                        **stats,
                    },
                )
                written += 1
            db.commit()
            print(f"{source_mode} -> {our_mode}: wrote {written} rows")
            total_written += written

        print(f"done — {total_written} rows written, {total_skipped} entries skipped (no matching vehicle or no games)")
    finally:
        db.close()


if __name__ == "__main__":
    run()
