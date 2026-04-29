#!/usr/bin/env python3
"""
SubDrop catalog refresh helper.

For every vendor in vendors.json, asks Gemini (with Google Search
grounding) to enumerate the FULL public plan matrix — every tier
(by vendor's own name) × every billing cycle the vendor publishes —
and reconciles the result against the catalog. Dry-run by default;
--apply mutates vendors.json in place.

Usage:
    export GEMINI_API_KEY=...
    python scripts/refresh.py             # dry-run, prints diff
    python scripts/refresh.py --apply     # writes changes to vendors.json
    python scripts/refresh.py --limit 5   # only check first 5 vendors

Exit codes:
    0  no changes (or changes successfully applied with --apply)
    1  --apply ran but applied nothing
    2  dry-run found changes (used by CI to gate a PR)
    3  configuration / runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("error: install dependencies first → pip install -r scripts/requirements.txt",
          file=sys.stderr)
    sys.exit(3)


# Flash is plenty for "look up a number, return JSON" — fast, cheap, and
# search-grounded. Bump to gemini-2.5-pro if you ever see Flash missing
# nuanced regional pricing.
MODEL = "gemini-2.5-flash"

CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"

# Cents tolerance — absorbs floating-point noise from the model's response.
CHANGE_THRESHOLD = 0.01

# Cycles we model. Anything else returned by the model is dropped.
ALLOWED_CYCLES = {"weekly", "monthly", "quarterly", "yearly"}


def discover_plans(client, vendor: dict) -> list[dict] | None:
    """
    Asks Gemini to enumerate every public plan offered by `vendor` —
    each tier × each billing cycle, with current list price.
    Returns a list of plan dicts, or None on API error / unparseable response.
    """
    region_hint = _primary_region(vendor)
    currency_hint = _primary_currency(vendor)
    prompt = (
        f"You are cataloguing the FULL public plan matrix for a subscription service.\n\n"
        f"Service: {vendor['name']}\n"
        f"Domain (authoritative): {vendor.get('domain') or 'unknown'}\n"
        f"Primary region: {region_hint}\n"
        f"Primary currency: {currency_hint}\n\n"
        f"Use Google Search to find this vendor's official pricing page. "
        f"List EVERY consumer tier they currently publish — using the vendor's "
        f"own terminology (e.g. \"Premium Individual\", \"Standard with ads\", "
        f"\"Family\", \"Student\", \"Duo\"). For each tier, include EVERY billing "
        f"cycle that vendor offers it on (monthly, yearly, weekly, quarterly).\n\n"
        f"Skip business / enterprise / education-bulk plans. Skip add-ons that "
        f"only attach to another tier (e.g. \"4K add-on\"). Skip free tiers.\n\n"
        f"Return ONLY a single JSON object, no Markdown. Shape:\n"
        f"{{\n"
        f"  \"plans\": [\n"
        f"    {{\n"
        f"      \"name\": string — vendor's own tier name,\n"
        f"      \"cycle\": \"monthly\" | \"yearly\" | \"weekly\" | \"quarterly\",\n"
        f"      \"amount\": number — list price excluding tax,\n"
        f"      \"currency\": ISO 4217 code,\n"
        f"      \"region\": ISO 3166-1 alpha-2 country code,\n"
        f"      \"source_url\": string — page where you confirmed it,\n"
        f"      \"confidence\": \"high\" | \"medium\" | \"low\"\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n\n"
        f"Return for the primary region only ({region_hint}, {currency_hint}). "
        f"If you cannot determine a tier's price for that region, omit it. "
        f"If the entire vendor is unverifiable, return: "
        f"{{\"plans\": [], \"unknown\": true, \"reason\": \"...\"}}"
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0,
            ),
        )
    except Exception as e:
        print(f"    ! API error: {e}", file=sys.stderr)
        return None

    text = (response.text or "").strip()
    parsed = _extract_json(text)
    if not parsed:
        return None
    if parsed.get("unknown"):
        return []

    plans_raw = parsed.get("plans") or []
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


def _extract_json(text: str) -> dict | None:
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to vendors.json (default: dry-run).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only check the first N vendors (useful for testing).")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("error: GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        return 3

    if not CATALOG_PATH.exists():
        print(f"error: {CATALOG_PATH} not found", file=sys.stderr)
        return 3

    catalog = json.loads(CATALOG_PATH.read_text())
    client = genai.Client(api_key=api_key)

    vendors = catalog["vendors"]
    if args.limit:
        vendors = vendors[: args.limit]

    print(f"Checking {len(vendors)} vendor(s) using {MODEL}…\n", file=sys.stderr)

    proposals: list[dict] = []
    for vendor in vendors:
        print(f"  → {vendor['name']}", file=sys.stderr)
        discovered = discover_plans(client, vendor)
        if discovered is None:
            print(f"    ! skipped (API error)", file=sys.stderr)
            continue
        if not discovered:
            print(f"    · no plans returned", file=sys.stderr)
            continue
        vendor_proposals = reconcile(vendor, discovered)
        if not vendor_proposals:
            print(f"    · {len(discovered)} plan(s) verified, no changes", file=sys.stderr)
            continue
        for c in vendor_proposals:
            if c["kind"] == "add":
                t = c["tier"]
                print(f"    + add {t['name']} / {t['cycle']} ({t['currency']} {t['amount']:.2f})", file=sys.stderr)
            else:
                print(f"    ↑ {c['tier_name']} / {c['cycle']}: {c['old_amount']:.2f} → {c['new_amount']:.2f} [{c['confidence']}]", file=sys.stderr)
        proposals.extend(vendor_proposals)

    print(file=sys.stderr)
    if not proposals:
        print("✓ No catalog changes detected.")
        return 0

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
