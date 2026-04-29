#!/usr/bin/env python3
"""
One-off seed of plan matrices for the headliner vendors. Hand-curated from
training-data knowledge of public CAD pricing (early 2026); marked as
medium-confidence. Re-run is idempotent — overwrites the listed vendors'
tiers arrays.

Usage:
    python scripts/seed-plans.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "vendors.json"


# Each entry: list of (id, name, cycle, currency, amount, region) tuples.
# Only entries the author is confident in are listed — vendors prone to
# heavy promotional pricing (e.g. NordVPN yearly) get monthly-only.
SEEDS = {
    "netflix": [
        ("standard_ads_monthly_ca", "Standard with ads", "monthly", "CAD",  5.99, "CA"),
        ("standard_monthly_ca",     "Standard",          "monthly", "CAD", 17.99, "CA"),
        ("premium_monthly_ca",      "Premium",           "monthly", "CAD", 24.99, "CA"),
    ],
    "spotify": [
        ("individual_monthly_ca", "Premium Individual", "monthly", "CAD", 11.99, "CA"),
        ("duo_monthly_ca",        "Premium Duo",        "monthly", "CAD", 14.99, "CA"),
        ("family_monthly_ca",     "Premium Family",     "monthly", "CAD", 16.99, "CA"),
        ("student_monthly_ca",    "Premium Student",    "monthly", "CAD",  5.99, "CA"),
    ],
    "disney_plus": [
        ("standard_ads_monthly_ca", "Standard with Ads", "monthly", "CAD",   7.99, "CA"),
        ("standard_monthly_ca",     "Standard",          "monthly", "CAD",  11.99, "CA"),
        ("standard_yearly_ca",      "Standard",          "yearly",  "CAD", 119.99, "CA"),
        ("premium_monthly_ca",      "Premium",           "monthly", "CAD",  14.99, "CA"),
        ("premium_yearly_ca",       "Premium",           "yearly",  "CAD", 149.99, "CA"),
    ],
    "youtube_premium": [
        ("individual_monthly_ca", "Individual", "monthly", "CAD", 13.99, "CA"),
        ("family_monthly_ca",     "Family",     "monthly", "CAD", 25.99, "CA"),
        ("student_monthly_ca",    "Student",    "monthly", "CAD",  7.99, "CA"),
    ],
    "apple_music": [
        ("student_monthly_ca",    "Student",    "monthly", "CAD",   5.99, "CA"),
        ("individual_monthly_ca", "Individual", "monthly", "CAD",  11.99, "CA"),
        ("individual_yearly_ca",  "Individual", "yearly",  "CAD", 119.00, "CA"),
        ("family_monthly_ca",     "Family",     "monthly", "CAD",  17.99, "CA"),
    ],
    "apple_tv_plus": [
        ("standard_monthly_ca", "Standard", "monthly", "CAD",  12.99, "CA"),
        ("standard_yearly_ca",  "Standard", "yearly",  "CAD", 129.00, "CA"),
    ],
    "amazon_prime": [
        ("monthly_ca",         "Monthly",         "monthly", "CAD",  9.99, "CA"),
        ("yearly_ca",          "Yearly",          "yearly",  "CAD", 99.00, "CA"),
        ("student_monthly_ca", "Student Monthly", "monthly", "CAD",  4.99, "CA"),
        ("student_yearly_ca",  "Student Yearly",  "yearly",  "CAD", 49.00, "CA"),
    ],
    "chatgpt_plus": [
        ("plus_monthly_us", "Plus", "monthly", "USD",  20.00, "US"),
        ("plus_monthly_ca", "Plus", "monthly", "CAD",  27.99, "CA"),
        ("pro_monthly_us",  "Pro",  "monthly", "USD", 200.00, "US"),
    ],
    "claude_pro": [
        ("pro_monthly_us", "Pro", "monthly", "USD",  20.00, "US"),
        ("pro_yearly_us",  "Pro", "yearly",  "USD", 200.00, "US"),
        ("pro_monthly_ca", "Pro", "monthly", "CAD",  27.99, "CA"),
    ],
    "adobe_creative_cloud": [
        # Adobe's CA SKU set is large + region-promotional; sticking to the
        # two best-documented monthly prices.
        ("all_apps_monthly_ca",     "All Apps",          "monthly", "CAD", 77.99, "CA"),
        ("photography_monthly_ca",  "Photography Plan",  "monthly", "CAD", 14.49, "CA"),
    ],
    "nordvpn": [
        # Yearly intentionally omitted — NordVPN's promotional cadence makes
        # static yearly prices stale within weeks.
        ("basic_monthly_ca",    "Basic",    "monthly", "CAD", 16.99, "CA"),
    ],
    "microsoft_365": [
        ("personal_monthly_ca", "Personal", "monthly", "CAD",   9.99, "CA"),
        ("personal_yearly_ca",  "Personal", "yearly",  "CAD",  99.00, "CA"),
        ("family_monthly_ca",   "Family",   "monthly", "CAD",  12.99, "CA"),
        ("family_yearly_ca",    "Family",   "yearly",  "CAD", 129.00, "CA"),
        ("basic_monthly_ca",    "Basic",    "monthly", "CAD",   2.99, "CA"),
        ("basic_yearly_ca",     "Basic",    "yearly",  "CAD",  24.99, "CA"),
    ],
}


def main() -> int:
    catalog = json.loads(CATALOG.read_text())
    by_id = {v["id"]: v for v in catalog["vendors"]}

    touched = 0
    for vendor_id, rows in SEEDS.items():
        v = by_id.get(vendor_id)
        if not v:
            print(f"!  unknown vendor id: {vendor_id}")
            continue
        v["tiers"] = [
            {
                "id": tid,
                "name": name,
                "cycle": cycle,
                "currency": cur,
                "amount": amt,
                "region": region,
            }
            for (tid, name, cycle, cur, amt, region) in rows
        ]
        touched += 1
        print(f"✓  {v['name']:<26} {len(rows)} tier(s)")

    catalog["version"] = int(catalog.get("version", 1)) + 1
    catalog["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"\nUpdated {touched} vendor(s). Catalog now v{catalog['version']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
