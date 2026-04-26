#!/usr/bin/env python3
"""
Refresh rates.json from open.er-api.com.

The endpoint is free, requires no API key, and updates daily from a
mix of central-bank and market sources. We pin the base to USD and
keep only the 30 currencies SubDrop's UI exposes — enough coverage
for ~99% of subscription-paying countries.

Usage:
    python scripts/refresh-rates.py             # write rates.json
    python scripts/refresh-rates.py --diff      # show change vs current
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://open.er-api.com/v6/latest/USD"
RATES_PATH = Path(__file__).resolve().parent.parent / "rates.json"

# Currencies SubDrop exposes in its picker. Adding a code here makes it
# selectable in the app *after* the next rates.json refresh.
CURRENCIES: list[str] = sorted([
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF",
    "CNY", "INR", "MXN", "BRL", "KRW", "SGD", "HKD",
    "NOK", "SEK", "DKK", "PLN", "CZK", "ILS", "TRY",
    "ZAR", "AED", "SAR", "THB", "MYR", "IDR", "PHP", "VND",
])


def fetch_rates() -> tuple[dict[str, float], str]:
    with urllib.request.urlopen(ENDPOINT, timeout=15) as r:
        payload = json.loads(r.read())
    if payload.get("result") != "success":
        raise RuntimeError(f"upstream returned: {payload.get('result')}")
    return payload["rates"], payload.get("time_last_update_utc", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--diff", action="store_true",
                        help="Print delta vs current rates.json without writing.")
    args = parser.parse_args()

    try:
        upstream, source_timestamp = fetch_rates()
    except Exception as e:
        print(f"error: fetch failed: {e}", file=sys.stderr)
        return 3

    missing = [c for c in CURRENCIES if c not in upstream]
    if missing:
        print(f"warning: upstream missing {missing}", file=sys.stderr)

    selected = {c: round(upstream[c], 6) for c in CURRENCIES if c in upstream}

    out = {
        "schema": 1,
        "version": _bump_version(),
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "open.er-api.com",
        "sourceUpdated": source_timestamp,
        "base": "USD",
        "rates": selected,
    }

    if args.diff:
        _print_diff(out)
        return 0

    RATES_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {RATES_PATH.name}: v{out['version']}, {len(selected)} currencies")
    return 0


def _bump_version() -> int:
    if not RATES_PATH.exists():
        return 1
    try:
        prev = json.loads(RATES_PATH.read_text())
        return int(prev.get("version", 0)) + 1
    except Exception:
        return 1


def _print_diff(new: dict) -> None:
    if not RATES_PATH.exists():
        print("No existing rates.json — every code would be added.")
        return
    prev = json.loads(RATES_PATH.read_text())
    prev_rates = prev.get("rates", {})
    print(f"version {prev.get('version', 0)} → {new['version']}")
    for code in sorted(new["rates"].keys()):
        old_v = prev_rates.get(code)
        new_v = new["rates"][code]
        if old_v is None:
            print(f"  + {code}: {new_v}")
        elif abs(old_v - new_v) > 1e-6:
            delta = (new_v - old_v) / old_v * 100
            print(f"  ~ {code}: {old_v:.4f} → {new_v:.4f} ({delta:+.2f}%)")


if __name__ == "__main__":
    sys.exit(main())
