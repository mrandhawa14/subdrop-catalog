#!/usr/bin/env python3
"""
SubDrop catalog refresh helper.

Iterates every vendor tier in vendors.json, asks Claude (with the
web_search server tool) to verify the current list price, and reports
proposed changes. By default this is a dry-run — pass --apply to
modify vendors.json in place.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scripts/refresh.py             # dry-run, prints diff
    python scripts/refresh.py --apply     # writes changes to vendors.json
    python scripts/refresh.py --limit 5   # only check first 5 vendors

Exit codes:
    0  no changes (or changes successfully applied with --apply)
    1  applied no changes (with --apply when nothing differed)
    2  changes detected (dry-run only — useful in CI to gate a PR)
    3  configuration / runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("error: install dependencies first → pip install -r scripts/requirements.txt",
          file=sys.stderr)
    sys.exit(3)


# Sonnet 4.6 is the right cost/capability point for "verify a number, return JSON."
# Bump to claude-opus-4-7 if you find Sonnet missing nuanced regional pricing.
MODEL = "claude-sonnet-4-6"

# Web search server tool — runs on Anthropic's side, no extra setup.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"

# How far new vs. old must differ (in currency units) before we propose a change.
# 1¢ tolerance handles floating-point drift from the model's response parsing.
CHANGE_THRESHOLD = 0.01


def verify_tier(client: anthropic.Anthropic, vendor: dict, tier: dict) -> dict | None:
    """
    Asks Claude to look up the current list price for a vendor's tier.
    Returns a change-proposal dict, or None if the price is unchanged or
    we couldn't verify with confidence.
    """
    region = tier.get("region", "US")
    currency = tier.get("currency", "USD")
    prompt = (
        f"You are verifying the current LIST price (excluding tax) for a "
        f"subscription service.\n\n"
        f"Service: {vendor['name']}\n"
        f"Tier: {tier['name']}\n"
        f"Region: {region}\n"
        f"Currency: {currency}\n"
        f"Last known amount: {tier['amount']}\n\n"
        f"Use web_search to find the OFFICIAL current list price for this exact "
        f"tier in this region. Look at the vendor's own pricing page first "
        f"(check the official domain, not third-party comparison sites).\n\n"
        f"Return ONLY a single JSON object with these fields, nothing else:\n"
        f"  amount       — number, list price exclusive of tax\n"
        f"  currency     — must equal \"{currency}\"\n"
        f"  source_url   — string, page where you confirmed it\n"
        f"  confidence   — \"high\" | \"medium\" | \"low\"\n\n"
        f"If you cannot find current pricing with reasonable confidence, "
        f"return: {{\"unknown\": true, \"reason\": \"...\"}}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=[WEB_SEARCH_TOOL],
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        print(f"    ! API error: {e}", file=sys.stderr)
        return None

    # Concatenate all text blocks; web_search results live in tool_use blocks
    # and aren't user-facing — Claude's final text response is what we parse.
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    parsed = _extract_json(text)
    if not parsed:
        return None

    if parsed.get("unknown"):
        return None

    new_amount = parsed.get("amount")
    returned_currency = parsed.get("currency")

    # Validation: refuse to propose a change if currency drifted.
    if returned_currency != currency:
        return None
    if not isinstance(new_amount, (int, float)):
        return None
    if abs(float(new_amount) - float(tier["amount"])) < CHANGE_THRESHOLD:
        return None

    return {
        "vendor_id": vendor["id"],
        "vendor_name": vendor["name"],
        "tier_id": tier["id"],
        "tier_name": tier["name"],
        "region": region,
        "currency": currency,
        "old_amount": float(tier["amount"]),
        "new_amount": float(new_amount),
        "source": parsed.get("source_url"),
        "confidence": parsed.get("confidence", "unknown"),
    }


def _extract_json(text: str) -> dict | None:
    """Pulls the first {...} block out of a model response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def apply_changes(catalog: dict, changes: list[dict]) -> None:
    """Mutates `catalog` in place — bumps version, stamps updated, applies prices."""
    by_vendor: dict[str, dict] = {v["id"]: v for v in catalog["vendors"]}
    for change in changes:
        vendor = by_vendor.get(change["vendor_id"])
        if not vendor:
            continue
        for tier in vendor.get("tiers", []):
            if tier["id"] == change["tier_id"]:
                tier["amount"] = change["new_amount"]
                break

    catalog["version"] = int(catalog.get("version", 1)) + 1
    catalog["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to vendors.json (default: dry-run).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only check the first N vendors (useful for testing).")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 3

    if not CATALOG_PATH.exists():
        print(f"error: {CATALOG_PATH} not found", file=sys.stderr)
        return 3

    catalog = json.loads(CATALOG_PATH.read_text())
    client = anthropic.Anthropic(api_key=api_key)

    vendors = catalog["vendors"]
    if args.limit:
        vendors = vendors[: args.limit]

    print(f"Checking {len(vendors)} vendor(s) using {MODEL}…\n", file=sys.stderr)

    proposals: list[dict] = []
    for vendor in vendors:
        for tier in vendor.get("tiers", []):
            label = f"  → {vendor['name']:<28} {tier['name']:<32} ({tier['currency']} {tier['amount']:.2f})"
            print(label, file=sys.stderr)
            change = verify_tier(client, vendor, tier)
            if change:
                proposals.append(change)
                arrow = f"    ↑ {change['old_amount']:.2f} → {change['new_amount']:.2f} [{change['confidence']}]"
                print(arrow, file=sys.stderr)
                if change["source"]:
                    print(f"      {change['source']}", file=sys.stderr)

    print(file=sys.stderr)
    if not proposals:
        print("✓ No price changes detected.")
        return 0

    print(f"Proposed changes ({len(proposals)}):\n")
    for c in proposals:
        print(f"  {c['vendor_name']} / {c['tier_name']} ({c['region']}): "
              f"{c['currency']} {c['old_amount']:.2f} → {c['new_amount']:.2f} "
              f"[{c['confidence']}]")
        if c["source"]:
            print(f"    source: {c['source']}")
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
