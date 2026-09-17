"""
Collector: pulls player stat snapshots and appends them to the database.
Run on a schedule (cron / APScheduler), NOT on request.

STATUS OF THE TWO DATA SOURCES THIS FILE TOUCHES
--------------------------------------------------
1. Whole-account, per-mode stats -> player_overall_stats.
   CONFIRMED WORKING. https://thunderskill.com/en/stat/<name>/export/json
   is a live, public, unauthenticated JSON endpoint. Fetched for real during
   development (player "RESET") and returned:

       {"stats": {"nick": "...", "rank": "...", "last_stat": "...",
                   "a": {...arcade...}, "r": {...realistic...}, "s": {...simulator...}}}

   Each mode block includes (among others): win, mission, death, winrate,
   kd, kb (kills per battle). Field names are exactly as shown below —
   this is not a guess, it's what the endpoint returned.

   Two known behaviors to handle:
     - a hidden profile returns HTTP 403 with body {"error": "player profile is hidden"}
     - some numeric fields come back as null for players with too little
       data in a mode (e.g. "kd": null) - treat as "no data", not zero.

2. Per-VEHICLE stats -> player_samples (what vehicle_stats_daily is actually
   built from). NOT YET WIRED UP. Thunderskill's own site clearly has this
   data (there's a "Vehicles" tab on every profile, and a site-wide
   /en/vehicles page broken down "by Mode & Country"), but the pages that
   would reveal the underlying request are behind bot detection from here.
   Likely candidates worth checking with real browser devtools (Network
   tab, filter XHR) before writing this function:
       https://thunderskill.com/en/stat/<name>/vehicles/export/json
       https://thunderskill.com/en/stat/<name>/export/json?tab=vehicles
       (or a separate endpoint entirely — check what the "Vehicles" tab
        click actually fires)
   Until this is confirmed, fetch_player_vehicle_snapshots() below raises
   NotImplementedError on purpose rather than shipping a guessed URL.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal

logger = logging.getLogger("wt_stats.collector")

REQUEST_DELAY_SECONDS = 1.5  # be polite to a third party's servers
BATCH_SIZE = 200
THUNDERSKILL_EXPORT_URL = "https://thunderskill.com/en/stat/{name}/export/json"
REQUEST_TIMEOUT = 10

MODE_KEY_TO_ENUM = {"a": "arcade", "r": "realistic", "s": "simulator"}


@dataclass
class OverallModeStats:
    mode: str  # "arcade" | "realistic" | "simulator"
    wins: int | None
    battles: int | None
    deaths: int | None
    win_rate: float | None
    kd_ratio: float | None
    kills_per_battle: float | None


@dataclass
class VehicleSnapshot:
    """Shape kept for when fetch_player_vehicle_snapshots is filled in."""
    vehicle_slug: str
    mode: str
    wins: int
    losses: int
    kills: int
    deaths: int
    battles: int


def fetch_player_overall_stats(player_name: str) -> tuple[list[OverallModeStats], datetime | None]:
    """
    CONFIRMED WORKING against the real endpoint. Returns (per-mode stats,
    the source's own last_stat timestamp) or ([], None) for a player with
    no public profile — never raises for that case, only for network errors.
    """
    url = THUNDERSKILL_EXPORT_URL.format(name=player_name)
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
        "User-Agent": "wt-stats-collector/0.1 (contact: <fill in before deploying>)",
    })

    if resp.status_code == 403:
        logger.info("player %s has a hidden profile, skipping", player_name)
        return [], None
    resp.raise_for_status()

    payload = resp.json()
    stats = payload.get("stats")
    if not stats:
        return [], None

    last_stat = None
    if stats.get("last_stat"):
        try:
            last_stat = datetime.strptime(stats["last_stat"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            logger.warning("unrecognized last_stat format: %r", stats.get("last_stat"))

    results: list[OverallModeStats] = []
    for key, mode in MODE_KEY_TO_ENUM.items():
        block = stats.get(key)
        if not block:
            continue
        results.append(OverallModeStats(
            mode=mode,
            wins=block.get("win"),
            battles=block.get("mission"),
            deaths=block.get("death"),
            win_rate=block.get("winrate"),
            kd_ratio=block.get("kd"),
            kills_per_battle=block.get("kb"),
        ))
    return results, last_stat


def fetch_player_vehicle_snapshots(player_name: str) -> list[VehicleSnapshot]:
    """
    NOT YET IMPLEMENTED — see the module docstring. Confirm the real
    endpoint with browser devtools before filling this in; don't guess a URL.
    """
    raise NotImplementedError(
        "per-vehicle endpoint not yet confirmed; see module docstring for where to look"
    )


def _get_or_create_player(db: Session, name: str) -> int:
    row = db.execute(text("SELECT id FROM players WHERE name = :name"), {"name": name}).first()
    if row:
        db.execute(text("UPDATE players SET last_seen = now() WHERE id = :id"), {"id": row[0]})
        return row[0]
    new_id = db.execute(
        text("INSERT INTO players (name) VALUES (:name) RETURNING id"), {"name": name}
    ).scalar_one()
    return new_id


def collect_overall_stats_for_player(db: Session, player_name: str) -> int:
    """Fetches one player's overall stats and inserts rows. Returns rows inserted."""
    mode_stats, last_stat = fetch_player_overall_stats(player_name)
    if not mode_stats:
        return 0

    player_id = _get_or_create_player(db, player_name)
    for s in mode_stats:
        db.execute(
            text("""
                INSERT INTO player_overall_stats
                    (player_id, mode, wins, battles, deaths, win_rate, kd_ratio,
                     kills_per_battle, source_last_stat)
                VALUES
                    (:player_id, :mode, :wins, :battles, :deaths, :win_rate, :kd_ratio,
                     :kills_per_battle, :source_last_stat)
            """),
            {
                "player_id": player_id,
                "mode": s.mode,
                "wins": s.wins,
                "battles": s.battles,
                "deaths": s.deaths,
                "win_rate": s.win_rate,
                "kd_ratio": s.kd_ratio,
                "kills_per_battle": s.kills_per_battle,
                "source_last_stat": last_stat,
            },
        )
    return len(mode_stats)


def run(player_names: list[str]) -> None:
    db = SessionLocal()
    total = 0
    try:
        for name in player_names[:BATCH_SIZE]:
            try:
                total += collect_overall_stats_for_player(db, name)
                db.commit()
            except requests.RequestException:
                logger.exception("network error collecting player %s", name)
                db.rollback()
            except Exception:
                logger.exception("failed collecting player %s", name)
                db.rollback()
            time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        db.close()
    logger.info("collector run complete: %d stat rows inserted", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # TODO: replace with a real queue (a `players_to_check` table, or a
    # squadron roster crawl) instead of a hardcoded list.
    run(player_names=[])
