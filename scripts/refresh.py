#!/usr/bin/env python3
"""
SubDrop catalog refresh helper.

Price discovery is done *outside* this script — by a human or by an agent
(e.g. Claude Code) using web search — and handed in as a plans file. This
script is the deterministic half: it reconciles discovered plans against
vendors.json and, with --apply, writes the changes back (bumping version,
stamping `updated`, and appending priceHistory entries).

No API keys, no network calls. Pure stdlib.

Typical workflow:

    # 1. Emit a research brief listing every vendor + the tiers to verify.
    python scripts/refresh.py --emit-brief > brief.json

    # 2. Research current list prices (web search) and write a plans file
    #    in the shape documented below (see --emit-template for a skeleton).

    # 3. Dry-run the reconcile to see the proposed diff.
    python scripts/refresh.py --plans plans.json

    # 4. Apply once it looks right.
    python scripts/refresh.py --plans plans.json --apply

Plans file shape (JSON):

    {
      "netflix": [
        {
          "name": "Standard",          // vendor's own tier name
          "cycle": "monthly",          // monthly | yearly | weekly | quarterly
          "amount": 18.99,             // list price, excluding tax
          "currency": "CAD",           // ISO 4217
          "region": "CA",              // ISO 3166-1 alpha-2
          "source_url": "https://...", // optional, where it was confirmed
          "confidence": "high"         // optional: high | medium | low
        }
      ]
    }

Matching is additive-only: a discovered plan that matches an existing tier
on (name, cycle, region, currency) proposes an amount update; one with no
match proposes a new tier; existing tiers not present in the plans file are
left untouched (so a missed search never deletes a tier).

Exit codes:
    0  no changes (or changes successfully applied with --apply)
    1  --apply ran but applied nothing
    2  dry-run found changes (used by CI to gate a PR)
    3  configuration / runtime error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"

# Cents tolerance — absorbs floating-point noise.
CHANGE_THRESHOLD = 0.01

# Cycles we model. Anything else in a plans file is dropped.
ALLOWED_CYCLES = {"weekly", "monthly", "quarterly", "yearly"}


def _primary_region(vendor: dict) -> str:
    for tier in vendor.get("tiers", []):
        if tier.get("region"):
            return tier["region"]
    return "US"


def _primary_currency(vendor: dict) -> str:
    for tier in vendor.get("tiers", []):
        if tier.get("currency"):
            return tier["currency"]
    return "USD"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def clean_plans(plans_raw: list[dict]) -> list[dict]:
    """Normalize and validate a list of discovered plan dicts. Drops any plan
    with an unknown cycle or a non-numeric amount."""
    cleaned: list[dict] = []
    for p in plans_raw:
        try:
            cycle = str(p["cycle"]).lower().strip()
            if cycle not in ALLOWED_CYCLES:
                continue
            amount = float(p["amount"])
            cleaned.append({
                "name": str(p["name"]).strip(),
                "cycle": cycle,
                "amount": amount,
                "currency": str(p["currency"]).strip().upper(),
                "region": str(p["region"]).strip().upper(),
                "source_url": p.get("source_url"),
                "confidence": p.get("confidence", "unknown"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return cleaned


def reconcile(vendor: dict, discovered: list[dict]) -> list[dict]:
    """
    Diffs `discovered` against `vendor['tiers']`. Returns a list of change
    proposals — additions and amount updates. Existing tiers absent from
    `discovered` are left alone (additive-only) so we don't drop a tier the
    search merely missed.

    Match key: (name, cycle, region, currency). All four must equal.
    """
    proposals: list[dict] = []
    existing = vendor.get("tiers", [])

    for plan in discovered:
        match = next(
            (t for t in existing
             if t.get("name") == plan["name"]
             and (t.get("cycle") or _infer_cycle(t)) == plan["cycle"]
             and t.get("region") == plan["region"]
             and t.get("currency") == plan["currency"]),
            None,
        )
        if match is None:
            proposals.append({
                "kind": "add",
                "vendor_id": vendor["id"],
                "vendor_name": vendor["name"],
                "tier": {
                    "id": _synthesize_tier_id(vendor, plan),
                    "name": plan["name"],
                    "cycle": plan["cycle"],
                    "currency": plan["currency"],
                    "amount": plan["amount"],
                    "region": plan["region"],
                },
                "source": plan.get("source_url"),
                "confidence": plan.get("confidence", "unknown"),
            })
        elif abs(float(match["amount"]) - plan["amount"]) >= CHANGE_THRESHOLD:
            proposals.append({
                "kind": "update",
                "vendor_id": vendor["id"],
                "vendor_name": vendor["name"],
                "tier_id": match["id"],
                "tier_name": match["name"],
                "cycle": plan["cycle"],
                "region": plan["region"],
                "currency": plan["currency"],
                "old_amount": float(match["amount"]),
                "new_amount": plan["amount"],
                "source": plan.get("source_url"),
                "confidence": plan.get("confidence", "unknown"),
            })

    return proposals


def _infer_cycle(tier: dict) -> str:
    """Back-compat: tiers without explicit `cycle` infer from id/name."""
    probe = (str(tier.get("id", "")) + " " + str(tier.get("name", ""))).lower()
    if "yearly" in probe or "annual" in probe:
        return "yearly"
    if "weekly" in probe:
        return "weekly"
    if "quarterly" in probe:
        return "quarterly"
    return "monthly"


def _synthesize_tier_id(vendor: dict, plan: dict) -> str:
    base = f"{_slug(plan['name'])}_{plan['cycle']}_{plan['region'].lower()}"
    existing_ids = {t.get("id") for t in vendor.get("tiers", [])}
    if base not in existing_ids:
        return base
    # Disambiguate on the rare collision (e.g. same name+cycle+region across currencies).
    return f"{base}_{plan['currency'].lower()}"


def apply_changes(catalog: dict, proposals: list[dict]) -> None:
    """Mutates `catalog` in place — bumps version, stamps updated, applies tier
    additions and amount updates, and appends a priceHistory entry for every
    update so the SubDrop client can surface a 'this got more expensive' banner."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_vendor: dict[str, dict] = {v["id"]: v for v in catalog["vendors"]}

    for change in proposals:
        vendor = by_vendor.get(change["vendor_id"])
        if not vendor:
            continue

        if change["kind"] == "add":
            vendor.setdefault("tiers", []).append(change["tier"])
            continue

        # update
        for tier in vendor.get("tiers", []):
            if tier["id"] == change["tier_id"]:
                tier["amount"] = change["new_amount"]
                # Backfill cycle on legacy tiers as we touch them.
                if not tier.get("cycle"):
                    tier["cycle"] = change["cycle"]
                break

        history = vendor.setdefault("priceHistory", [])
        history.append({
            "tierId": change["tier_id"],
            "currency": change["currency"],
            "amount": change["new_amount"],
            "effectiveFrom": today,
        })

    catalog["version"] = int(catalog.get("version", 1)) + 1
    catalog["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_brief(catalog: dict) -> dict:
    """A research brief: for each vendor, what to look up and the tiers we
    currently hold. Feed this to whoever (human or agent) does the web search."""
    vendors = []
    for v in catalog["vendors"]:
        vendors.append({
            "id": v["id"],
            "name": v["name"],
            "domain": v.get("domain"),
            "primary_region": _primary_region(v),
            "primary_currency": _primary_currency(v),
            "current_tiers": [
                {
                    "name": t.get("name"),
                    "cycle": t.get("cycle") or _infer_cycle(t),
                    "currency": t.get("currency"),
                    "region": t.get("region"),
                    "amount": t.get("amount"),
                }
                for t in v.get("tiers", [])
            ],
        })
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instructions": (
            "For each vendor, find the official pricing page and confirm the "
            "current list price (excluding tax) for the primary region/currency. "
            "Write a plans file keyed by vendor id; see refresh.py --emit-template."
        ),
        "vendors": vendors,
    }


def build_template(catalog: dict) -> dict:
    """A plans-file skeleton pre-populated with current tiers, so the
    researcher only has to correct the amounts and source_url."""
    template: dict[str, list[dict]] = {}
    for v in catalog["vendors"]:
        template[v["id"]] = [
            {
                "name": t.get("name"),
                "cycle": t.get("cycle") or _infer_cycle(t),
                "amount": t.get("amount"),
                "currency": t.get("currency"),
                "region": t.get("region"),
                "source_url": None,
                "confidence": "high",
            }
            for t in v.get("tiers", [])
        ]
    return template


def load_plans(path: Path) -> dict[str, list[dict]]:
    """Reads and normalizes a plans file: {vendor_id: [plan, ...]}."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("plans file must be a JSON object keyed by vendor id")
    return {vid: clean_plans(plans or []) for vid, plans in data.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plans", type=Path, default=None,
                        help="JSON file of discovered plans, keyed by vendor id.")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to vendors.json (default: dry-run).")
    parser.add_argument("--emit-brief", action="store_true",
                        help="Print a research brief (vendors + current tiers) and exit.")
    parser.add_argument("--emit-template", action="store_true",
                        help="Print a plans-file skeleton (current tiers) and exit.")
    args = parser.parse_args()

    if not CATALOG_PATH.exists():
        print(f"error: {CATALOG_PATH} not found", file=sys.stderr)
        return 3

    catalog = json.loads(CATALOG_PATH.read_text())

    if args.emit_brief:
        print(json.dumps(build_brief(catalog), indent=2))
        return 0
    if args.emit_template:
        print(json.dumps(build_template(catalog), indent=2))
        return 0

    if not args.plans:
        print("error: pass --plans <file> (or --emit-brief / --emit-template)",
              file=sys.stderr)
        return 3
    if not args.plans.exists():
        print(f"error: plans file {args.plans} not found", file=sys.stderr)
        return 3

    try:
        plans_by_vendor = load_plans(args.plans)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: could not parse plans file: {e}", file=sys.stderr)
        return 3

    by_id = {v["id"]: v for v in catalog["vendors"]}
    unknown_ids = [vid for vid in plans_by_vendor if vid not in by_id]
    for vid in unknown_ids:
        print(f"  ! plans file has unknown vendor id '{vid}' — skipped", file=sys.stderr)

    proposals: list[dict] = []
    for vid, discovered in plans_by_vendor.items():
        vendor = by_id.get(vid)
        if not vendor or not discovered:
            continue
        vendor_proposals = reconcile(vendor, discovered)
        for c in vendor_proposals:
            if c["kind"] == "add":
                t = c["tier"]
                print(f"  + {vendor['name']}: add {t['name']} / {t['cycle']} "
                      f"({t['currency']} {t['amount']:.2f})", file=sys.stderr)
            else:
                print(f"  ↑ {vendor['name']}: {c['tier_name']} / {c['cycle']}: "
                      f"{c['old_amount']:.2f} → {c['new_amount']:.2f} "
                      f"[{c['confidence']}]", file=sys.stderr)
        proposals.extend(vendor_proposals)

    print(file=sys.stderr)
    if not proposals:
        print("✓ No catalog changes detected.")
        return 1 if args.apply else 0

    additions = [c for c in proposals if c["kind"] == "add"]
    updates = [c for c in proposals if c["kind"] == "update"]
    print(f"Proposed changes: {len(additions)} addition(s), {len(updates)} update(s)\n")

    for c in additions:
        t = c["tier"]
        print(f"  + {c['vendor_name']} / {t['name']} ({t['cycle']}, {t['region']}): "
              f"{t['currency']} {t['amount']:.2f}")
        if c.get("source"):
            print(f"      source: {c['source']}")
    for c in updates:
        print(f"  ↑ {c['vendor_name']} / {c['tier_name']} ({c['cycle']}, {c['region']}): "
              f"{c['currency']} {c['old_amount']:.2f} → {c['new_amount']:.2f} "
              f"[{c['confidence']}]")
        if c.get("source"):
            print(f"      source: {c['source']}")
    print()

    if args.apply:
        apply_changes(catalog, proposals)
        CATALOG_PATH.write_text(json.dumps(catalog, indent=2) + "\n")
        print(f"Applied {len(proposals)} change(s) to {CATALOG_PATH.name} "
              f"(now v{catalog['version']}).")
        return 0
    else:
        print("Dry-run. Pass --apply to write changes to vendors.json.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
