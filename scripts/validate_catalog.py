#!/usr/bin/env python3
"""Validate timeline and historical-price invariants in vendors.json.

This deliberately uses only the Python standard library. JSON Schema tools can
validate shape in CI, while this script handles relationships that a schema
cannot express cleanly: launch/retirement order, tier references, and history
windows. It never edits the catalog.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"


def parse_date(raw: str, path: str, errors: list[str]) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        errors.append(f"{path}: expected YYYY-MM-DD, got {raw!r}")
        return None


def validate(catalog: dict) -> list[str]:
    errors: list[str] = []
    seen_vendor_ids: set[str] = set()

    for vendor in catalog.get("vendors", []):
        vendor_id = vendor.get("id", "<missing>")
        prefix = f"vendors[{vendor_id}]"
        if vendor_id in seen_vendor_ids:
            errors.append(f"{prefix}: duplicate vendor id")
        seen_vendor_ids.add(vendor_id)

        launched = None
        retired = None
        if vendor.get("launchedAt"):
            launched = parse_date(vendor["launchedAt"], f"{prefix}.launchedAt", errors)
        if vendor.get("retiredAt"):
            retired = parse_date(vendor["retiredAt"], f"{prefix}.retiredAt", errors)
        if launched and retired and retired < launched:
            errors.append(f"{prefix}: retiredAt precedes launchedAt")

        tiers = vendor.get("tiers", [])
        tiers_by_id = {tier.get("id"): tier for tier in tiers}
        if len(tiers_by_id) != len(tiers):
            errors.append(f"{prefix}: duplicate tier id")

        for tier in tiers:
            tier_id = tier.get("id", "<missing>")
            tier_prefix = f"{prefix}.tiers[{tier_id}]"
            available = None
            tier_retired = None
            if tier.get("availableFrom"):
                available = parse_date(
                    tier["availableFrom"], f"{tier_prefix}.availableFrom", errors
                )
            if tier.get("retiredAt"):
                tier_retired = parse_date(
                    tier["retiredAt"], f"{tier_prefix}.retiredAt", errors
                )
            if launched and available and available < launched:
                errors.append(f"{tier_prefix}: availableFrom precedes vendor launchedAt")
            if available and tier_retired and tier_retired < available:
                errors.append(f"{tier_prefix}: retiredAt precedes availableFrom")

        history_by_tier: dict[str, list[tuple[date, date | None]]] = {}
        for index, entry in enumerate(vendor.get("priceHistory", [])):
            history_prefix = f"{prefix}.priceHistory[{index}]"
            tier_id = entry.get("tierId")
            tier = tiers_by_id.get(tier_id)
            if not tier:
                errors.append(f"{history_prefix}: unknown tierId {tier_id!r}")
                continue
            if entry.get("currency") != tier.get("currency"):
                errors.append(f"{history_prefix}: currency differs from referenced tier")

            effective_from = parse_date(
                entry.get("effectiveFrom"), f"{history_prefix}.effectiveFrom", errors
            )
            effective_to = None
            if entry.get("effectiveTo"):
                effective_to = parse_date(
                    entry["effectiveTo"], f"{history_prefix}.effectiveTo", errors
                )
            if not effective_from:
                continue
            if effective_to and effective_to < effective_from:
                errors.append(f"{history_prefix}: effectiveTo precedes effectiveFrom")

            if tier.get("availableFrom"):
                tier_start = parse_date(
                    tier["availableFrom"],
                    f"{prefix}.tiers[{tier_id}].availableFrom",
                    errors,
                )
                if tier_start and effective_from < tier_start:
                    errors.append(f"{history_prefix}: price predates tier availability")
            history_by_tier.setdefault(tier_id, []).append((effective_from, effective_to))

        for tier_id, windows in history_by_tier.items():
            starts = [window[0] for window in windows]
            if len(starts) != len(set(starts)):
                errors.append(f"{prefix}.priceHistory[{tier_id}]: duplicate effectiveFrom")

    return errors


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text())
    errors = validate(catalog)
    if errors:
        print("Catalog validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        f"Catalog timeline validation passed: "
        f"{len(catalog.get('vendors', []))} vendors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
