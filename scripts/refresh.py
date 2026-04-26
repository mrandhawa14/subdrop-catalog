#!/usr/bin/env python3
"""
SubDrop catalog refresh helper.

Iterates every vendor tier in vendors.json, asks Gemini (with Google
Search grounding) to verify the current list price, and reports
proposed changes. Dry-run by default; --apply mutates vendors.json
in place.

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

# How far new vs. old must differ before we propose a change. 1¢ tolerance
# absorbs floating-point noise from the model's response.
CHANGE_THRESHOLD = 0.01


def verify_tier(client, vendor: dict, tier: dict) -> dict | None:
    """
    Asks Gemini to look up the current list price for one tier.
    Returns a change-proposal dict, or None if unchanged or unverified.
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
        f"Use Google Search to find the OFFICIAL current list price for "
        f"this exact tier in this region. Look at the vendor's own pricing "
        f"page first (their official domain, not third-party comparison "
        f"sites).\n\n"
        f"Return ONLY a single JSON object with these fields, nothing else:\n"
        f"  amount       — number, list price exclusive of tax\n"
        f"  currency     — must equal \"{currency}\"\n"
        f"  source_url   — string, page where you confirmed it\n"
        f"  confidence   — \"high\" | \"medium\" | \"low\"\n\n"
        f"If you cannot find current pricing with reasonable confidence, "
        f"return: {{\"unknown\": true, \"reason\": \"...\"}}"
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
        return None

    new_amount = parsed.get("amount")
    returned_currency = parsed.get("currency")

    # Refuse to propose a change if currency drifted (search may have found
    # the US price for a CA tier, etc.).
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
    """Pulls the first {...} block out of a model response. Tolerates
    Markdown fences (```json ... ```) the model sometimes wraps things in."""
    # Strip a Markdown code fence if present.
    if text.startswith("```"):
        # remove leading fence line and trailing fence
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
        for tier in vendor.get("tiers", []):
            label = f"  → {vendor['name']:<28} {tier['name']:<32} ({tier['currency']} {tier['amount']:.2f})"
            print(label, file=sys.stderr)
            change = verify_tier(client, vendor, tier)
            if change:
                proposals.append(change)
                print(f"    ↑ {change['old_amount']:.2f} → {change['new_amount']:.2f} [{change['confidence']}]", file=sys.stderr)
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
