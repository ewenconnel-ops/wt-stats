"""
Run this ONCE, locally, to find out what the real battle-rating field
names are in wpcost.blkx — then paste its output back so seed_vehicles.py
can be corrected to match, instead of guessing.

This is a read-only inspection script. It doesn't touch the database.

Usage:
    pip install requests
    python scripts/inspect_wpcost.py
"""
import json
import re

import requests

URL = "https://raw.githubusercontent.com/gszabi99/War-Thunder-Datamine/master/char.vromfs.bin_u/config/wpcost.blkx"

# Any key containing one of these (case-insensitive) is worth printing —
# casts a wide net since we don't know the exact naming convention yet.
INTERESTING = re.compile(r"rank|rating|country|unittype|tags|class", re.IGNORECASE)


def main() -> None:
    print(f"Downloading {URL} ...")
    resp = requests.get(URL, timeout=60)
    resp.raise_for_status()
    print(f"Downloaded {len(resp.content) / 1_000_000:.1f} MB, parsing JSON...")

    data = json.loads(resp.text)
    print(f"Top-level entry count: {len(data)}")

    shown = 0
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        interesting_keys = {k: v for k, v in entry.items() if INTERESTING.search(k)}
        if not interesting_keys:
            continue

        print(f"\n=== {key} ===")
        for k, v in interesting_keys.items():
            print(f"  {k!r}: {v!r}")

        shown += 1
        if shown >= 8:
            break

    if shown == 0:
        print(
            "\nNo keys matched the usual naming patterns at all — paste a raw "
            "sample entry (any single vehicle's full dict) back instead, e.g.:\n"
            "  print(next(iter(data.items())))"
        )


if __name__ == "__main__":
    main()
