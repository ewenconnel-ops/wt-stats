# WT Stats — backend skeleton

Free, non-paywalled War Thunder vehicle/BR statistics. No auth, no tiers.

## Layout

```
migrations/001_init.sql   Postgres schema
app/database.py           engine + session factory
app/schemas.py             Pydantic response models
app/main.py                FastAPI read API (heatmap, vehicle detail, compare)
worker/collector.py        scheduled job: pulls player snapshots -> player_samples
worker/aggregator.py       scheduled job: player_samples -> vehicle_stats_daily
```

## How the pieces fit together

1. **collector.py** runs on a schedule and pulls player stats.
   - `fetch_player_overall_stats()` is **confirmed working** — it hits
     `https://thunderskill.com/en/stat/<name>/export/json`, a real public
     endpoint fetched and inspected during development, and writes to the
     new `player_overall_stats` table (whole-account stats per mode: this
     powers a player-profile page).
   - `fetch_player_vehicle_snapshots()` — the per-vehicle breakdown that
     `player_samples` / `vehicle_stats_daily` actually need — is **not yet
     wired up**. Thunderskill clearly has this data (a "Vehicles" tab per
     profile, a site-wide `/en/vehicles` page) but the exact request behind
     it is behind bot detection from this environment. Next step: open
     `https://thunderskill.com/en/stat/<name>` in a real browser, open
     devtools → Network → XHR, click into the Vehicles tab, and see what
     it actually calls. Candidate URLs to try first are listed in the
     function's docstring.
2. **seed_vehicles.py** pulls vehicle metadata (name/nation/class/BR) from
   `gszabi99/War-Thunder-Datamine` on GitHub — a real, frequently-updated
   mirror of the game's own data files. The repo and its two relevant files
   (`wpcost.blkx`, `shop.blkx`) are confirmed to exist; the exact field
   names for battle rating inside them are **not yet confirmed** (this
   sandbox has no network access to fetch and inspect the file directly).
   Read the big warning at the top of that file before running it for real.
3. **aggregator.py** runs once a day, rolls `player_samples` up into
   `vehicle_stats_daily` per vehicle/mode/date, with Bayesian shrinkage so
   thin-sample vehicles don't show wild win rates. Unchanged from before —
   it's waiting on the per-vehicle collector above to actually have data
   to aggregate.
4. **app/main.py** is the public API. It reads ONLY from
   `vehicle_stats_daily` (via the `vehicle_stats_latest` view) — never from
   raw `player_samples` — so every response is a fast indexed lookup
   regardless of how much history has piled up.

## Getting it running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

createdb wt_stats
psql wt_stats -f migrations/001_init.sql

export DATABASE_URL=postgresql+psycopg://localhost/wt_stats
uvicorn app.main:app --reload
```

Then: `GET http://localhost:8000/health`, `GET /vehicles`, `GET /heatmap?mode=realistic&class=ground`.

## Not built yet

- Confirming the per-vehicle stats endpoint (see collector.py docstring)
  and implementing `fetch_player_vehicle_snapshots()` against it — this is
  the one real blocker before `vehicle_stats_daily` has any data in it.
- Confirming the exact `wpcost.blkx` field names (see seed_vehicles.py
  docstring) and adjusting `BR_FIELD_CANDIDATES` to match.
- A `players_to_check` queue table so the collector has something smarter
  than a hardcoded list to work through.
- Auth/rate-limiting on the API if it ever needs it — deliberately absent
  for now since nothing here is meant to be gated.
- A quick legal check on Thunderskill's terms before scraping it at scale —
  we're currently relying on a real endpoint, but "publicly reachable"
  isn't the same as "ToS-permitted for bulk automated use."
