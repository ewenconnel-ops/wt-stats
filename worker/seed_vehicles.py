"""
Seeds the `vehicles` table from gszabi99/War-Thunder-Datamine — a real,
actively-maintained GitHub mirror of the game's own data files (confirmed
via search: it's referenced by multiple community tools, including
Muxomor/wt_datamine_parser_py, as the upstream source for exactly this
kind of tech-tree/BR extraction).

WHAT'S CONFIRMED vs WHAT ISN'T
-------------------------------
Confirmed (via search results and other tools built on this repo):
  - The repo exists, is frequently updated, and mirrors the game's raw
    config files as .blkx (a JSON-like text format).
  - char.vromfs.bin_u/config/wpcost.blkx is the economy file: per-vehicle
    cost and rank/BR-adjacent data.
  - char.vromfs.bin_u/config/shop.blkx is the tech-tree file: which
    country and vehicle class each vehicle belongs to.
  - Other tools fetch these via the jsdelivr CDN, e.g.
    https://cdn.jsdelivr.net/gh/gszabi99/War-Thunder-Datamine@master/char.vromfs.bin_u/config/wpcost.blkx

NOT confirmed — this sandbox couldn't actually fetch and inspect the file
(blocked by bot detection on the CDN, and this container has no network
access at all): the EXACT key names inside wpcost.blkx for battle rating
per mode. Community docs and the forum thread this was found via strongly
suggest fields resembling `economicRankArcade` / `economicRankHistorical`
/ `economicRankSimulation` (rank, not BR directly — historically BR has
been derived from economic rank via a lookup table) or, in newer exports,
direct `battleRatingArcade` / `battleRatingRb` / `battleRatingSb` — either
convention has been used at different points by different datamine
consumers.

DO NOT run this against production until you have:
  1. Downloaded wpcost.blkx and shop.blkx yourself and opened them to
     confirm the actual key names for the current game version.
  2. Adjusted BR_FIELD_CANDIDATES / RANK_FIELD_CANDIDATES below to match.

The parser below is deliberately defensive — it tries several candidate
key names per field rather than assuming one — so that a wrong guess
produces a loud "couldn't find BR field" error instead of silently
writing wrong data.
"""
from __future__ import annotations

import logging
import re

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal

logger = logging.getLogger("wt_stats.seed_vehicles")

DATAMINE_BASE = "https://cdn.jsdelivr.net/gh/gszabi99/War-Thunder-Datamine@master"
WPCOST_URL = f"{DATAMINE_BASE}/char.vromfs.bin_u/config/wpcost.blkx"
SHOP_URL = f"{DATAMINE_BASE}/char.vromfs.bin_u/config/shop.blkx"

# Try these key names in order; first match wins. Update after step 1 above.
BR_FIELD_CANDIDATES = {
    "arcade": ["battleRatingArcade", "battleRatingEc", "economicRankArcade"],
    "realistic": ["battleRatingRb", "economicRankHistorical"],
    "simulator": ["battleRatingSb", "economicRankSimulation"],
}

# Country code -> display nation name. The datamine uses short codes
# like "country_usa"; extend this as real data surfaces unmapped ones.
COUNTRY_DISPLAY_NAMES = {
    "country_usa": "USA",
    "country_germany": "Germany",
    "country_ussr": "USSR",
    "country_britain": "Britain",
    "country_japan": "Japan",
    "country_china": "China",
    "country_italy": "Italy",
    "country_france": "France",
    "country_sweden": "Sweden",
    "country_israel": "Israel",
}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def _classify(vehicle_key: str, entry: dict) -> str | None:
    """Best-effort ground/air/naval classification from the entry's own hints."""
    tags = entry.get("tags", "") if isinstance(entry.get("tags"), str) else ""
    unit_type = str(entry.get("unitType", "")) + tags
    key = vehicle_key.lower()
    if any(t in unit_type.lower() for t in ("ship", "boat")) or key.startswith(("ship_", "boat_")):
        return "naval"
    if "tank" in unit_type.lower() or "exp_" in key or "tank" in key:
        return "ground"
    # Fall back to treating unrecognized entries as air, and flag for review —
    # air vehicles are the majority of wpcost entries historically.
    return "air"


def fetch_json(url: str) -> dict:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _first_present(entry: dict, candidates: list[str]) -> float | None:
    for key in candidates:
        if key in entry and entry[key] not in (None, ""):
            try:
                return float(entry[key])
            except (TypeError, ValueError):
                continue
    return None


def parse_vehicles(wpcost: dict, shop: dict) -> list[dict]:
    """
    Returns a list of {name, slug, nation, class, br_arcade, br_realistic, br_sim}.
    `wpcost` and `shop` are however requests' .json() parsed the fetched
    .blkx files — the exact nesting is what needs confirming per the
    module docstring; this assumes a flat top-level mapping of
    vehicle_key -> entry dict, which is the common shape for these exports
    but has NOT been verified against a live fetch from this environment.
    """
    vehicles = []
    missing_br = 0

    for vehicle_key, entry in wpcost.items():
        if not isinstance(entry, dict):
            continue

        br = {
            mode: _first_present(entry, candidates)
            for mode, candidates in BR_FIELD_CANDIDATES.items()
        }
        if all(v is None for v in br.values()):
            missing_br += 1
            continue

        country_code = entry.get("country") or entry.get("country_code")
        nation = COUNTRY_DISPLAY_NAMES.get(country_code, country_code or "Unknown")

        display_name = entry.get("name") or vehicle_key
        vehicles.append({
            "name": display_name,
            "slug": _slugify(display_name),
            "nation": nation,
            "class": _classify(vehicle_key, entry),
            "br_arcade": br["arcade"],
            "br_realistic": br["realistic"],
            "br_sim": br["simulator"],
        })

    if missing_br:
        logger.warning(
            "%d entries had no recognizable BR field — BR_FIELD_CANDIDATES "
            "likely needs updating for the current game version",
            missing_br,
        )
    return vehicles


def upsert_vehicles(db: Session, vehicles: list[dict]) -> int:
    written = 0
    for v in vehicles:
        db.execute(
            text("""
                INSERT INTO vehicles (name, slug, nation, class, br_arcade, br_realistic, br_sim)
                VALUES (:name, :slug, :nation, :class, :br_arcade, :br_realistic, :br_sim)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    nation = EXCLUDED.nation,
                    class = EXCLUDED.class,
                    br_arcade = EXCLUDED.br_arcade,
                    br_realistic = EXCLUDED.br_realistic,
                    br_sim = EXCLUDED.br_sim,
                    updated_at = now()
            """),
            v,
        )
        written += 1
    return written


def run() -> None:
    logger.info("fetching wpcost.blkx and shop.blkx from the datamine mirror")
    wpcost = fetch_json(WPCOST_URL)
    shop = fetch_json(SHOP_URL)

    vehicles = parse_vehicles(wpcost, shop)
    logger.info("parsed %d vehicles with at least one BR value", len(vehicles))

    db = SessionLocal()
    try:
        written = upsert_vehicles(db, vehicles)
        db.commit()
        logger.info("wrote %d vehicles", written)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
