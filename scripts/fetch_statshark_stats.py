"""
Fetches fresh win-rate data from StatShark's public global-stats endpoint
and writes it to data/statshark_vehicle_stats.json, in the same shape
seed_vehicle_stats_from_statshark.py already expects.

CONFIRMED WORKING as a plain server-side request (no browser, no
Cloudflare Turnstile token needed) — verified by capturing the real
request StatShark's own page makes and replaying it directly.

THE ONE MANUAL PIECE: this needs a "stat period id" (e.g.
"diff_2026_august_september") that StatShark generates per month. There's
a listing endpoint (getAvailableGlobalStats) that would give this
automatically, but it consistently rejected scripted requests during
development (406, cause unconfirmed — possibly a Turnstile-gated
endpoint like the per-player ones, possibly something else). Rather than
fight that, this script takes the id as an env var you update roughly
monthly:

    STATSHARK_STAT_ID=diff_2026_september_october

To find the current id: open https://statshark.net/globalstats in a
browser, click the latest month button, and check what id that triggers
(or just ask Claude to check — the browser-based capture process that
found the first one is quick to repeat).

Run:
    STATSHARK_STAT_ID=diff_2026_august_september python scripts/fetch_statshark_stats.py
"""
from __future__ import annotations

import json
import os
import pathlib

import requests

STATSHARK_URL = "https://statshark.net/api/misc/getGlobalUserStats"
OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "data" / "statshark_vehicle_stats.json"

DEFAULT_STAT_ID = "diff_2026_august_september"  # last known-good id as of this writing


def run() -> None:
    stat_id = os.environ.get("STATSHARK_STAT_ID", DEFAULT_STAT_ID)
    print(f"fetching StatShark global stats for id={stat_id!r}")

    resp = requests.post(
        STATSHARK_URL,
        json={"id": stat_id},
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; wt-stats-refresh/0.1; contact: <fill in before relying on this long-term>)",
        },
        timeout=60,
    )

    if resp.status_code != 200:
        raise SystemExit(
            f"StatShark returned {resp.status_code} for id={stat_id!r}. "
            f"The id is probably stale — check statshark.net/globalstats for "
            f"the current one and update STATSHARK_STAT_ID. Body: {resp.text[:300]}"
        )

    payload = resp.json()
    vehicle_count = sum(len(v) for v in payload.get("vehicle_stats", {}).values())
    if vehicle_count == 0:
        raise SystemExit(f"got a 200 but no vehicle_stats entries — response shape may have changed: {resp.text[:300]}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload))
    print(f"wrote {OUTPUT_PATH} ({vehicle_count} vehicle entries across all modes)")


if __name__ == "__main__":
    run()
