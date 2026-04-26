#!/usr/bin/env python3
"""
Fetch real App Store app icons for catalog vendors via the public iTunes
Search API and save them as 512×512 PNGs into ../logos/<vendor.id>.png.

Why this and not Simple Icons: App Store artwork is what users actually
see for these services on their phones, so it makes the SubDrop dashboard
feel real. iTunes Search is public, no API key, no rate-limit problems
at this scale.

Usage:
    python scripts/fetch-app-icons.py            # only fetch missing logos
    python scripts/fetch-app-icons.py --force    # refetch everything
    python scripts/fetch-app-icons.py --limit 5  # smoke-test on 5

Vendors that don't have a public App Store presence (Apple Arcade as a
service, iCloud+ as a service, etc.) are silently skipped — the app
falls back to the SF Symbol named in `iconName`.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"
LOGOS_DIR = Path(__file__).resolve().parent.parent / "logos"

ITUNES_SEARCH = "https://itunes.apple.com/search"

# Per-vendor App Store country override. iTunes Search defaults to US,
# which misses region-locked apps. List vendors whose canonical app lives
# only in another store (e.g. Canadian streaming services).
COUNTRY_OVERRIDES: dict[str, str] = {
    "crave": "ca",  # Bell Media's Crave is Canada-only on the App Store
}

# Per-vendor search overrides. The vendor `name` is used as the term by
# default; when iTunes returns the wrong app for that name (or the name
# contains noise like "+" / "Pro" that trips the search), specify a
# better term here. Right side is the term passed to ?term=.
SEARCH_OVERRIDES: dict[str, str] = {
    "youtube_premium": "YouTube",
    "apple_tv_plus": "Apple TV",
    "apple_news_plus": "Apple News",
    "chatgpt_plus": "ChatGPT",
    "claude_pro": "Claude by Anthropic",
    "github_copilot": "GitHub",        # no standalone Copilot app
    "playstation_plus": "PlayStation",
    "xbox_game_pass": "Xbox",
    "nintendo_switch_online": "Nintendo Switch Online",
    "microsoft_365": "Microsoft 365",
    "amazon_prime": "Amazon Shopping",  # the actual Prime-branded shopping app
    "discord_nitro": "Discord",
    "adobe_creative_cloud": "Adobe Creative Cloud",
    "1password": "1Password",
    "crave": "Crave",  # paired with COUNTRY_OVERRIDE 'ca'
    # Adobe no longer ships a flagship "Creative Cloud" iOS app; Adobe Express
    # is their current consumer creative app and carries the active brand mark.
    "adobe_creative_cloud": "Adobe Express",
}

# Some vendors have no useful App Store presence (system-bundled services,
# regional cable providers, etc.). Skip them upfront — saves a request and
# a misleading match.
SKIP: set[str] = {
    "icloud_plus",       # bundled in Settings
    "apple_arcade",      # bundled in App Store
}


def fetch_icon(vendor: dict, *, force: bool) -> tuple[str, str | None]:
    """Returns (status, matched_track_name) where status is one of
    "fetched", "skipped", "no_match", "skip_listed", "error"."""
    vid = vendor["id"]
    # Apple's artwork URLs serve JPEG payloads regardless of the extension
    # we save under. Use .jpg so the file format matches what consumers
    # (and the app's AsyncImage) expect.
    out = LOGOS_DIR / f"{vid}.jpg"

    if vid in SKIP:
        return "skip_listed", None
    if out.exists() and not force:
        return "skipped", None

    term = SEARCH_OVERRIDES.get(vid, vendor["name"])
    country = COUNTRY_OVERRIDES.get(vid, "us")
    qs = urllib.parse.urlencode({
        "term": term,
        "entity": "software",
        "limit": 5,
        "country": country,
    })

    try:
        with urllib.request.urlopen(f"{ITUNES_SEARCH}?{qs}", timeout=15) as r:
            payload = json.loads(r.read())
    except Exception as e:
        print(f"  ! search failed for {vid}: {e}", file=sys.stderr)
        return "error", None

    results = payload.get("results", [])
    if not results:
        return "no_match", None

    # Prefer the first hit; iTunes generally puts the most relevant on top.
    # For ambiguous searches (e.g. "Microsoft 365") we trust the override term.
    best = results[0]
    art = best.get("artworkUrl512") or best.get("artworkUrl100")
    if not art:
        return "no_match", best.get("trackName")

    try:
        with urllib.request.urlopen(art, timeout=15) as r:
            out.write_bytes(r.read())
    except Exception as e:
        print(f"  ! download failed for {vid}: {e}", file=sys.stderr)
        return "error", best.get("trackName")

    return "fetched", best.get("trackName")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="Re-download every icon, overwriting existing files.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N vendors.")
    args = parser.parse_args()

    if not CATALOG_PATH.exists():
        print(f"error: {CATALOG_PATH} not found", file=sys.stderr)
        return 3

    LOGOS_DIR.mkdir(exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text())
    vendors = catalog["vendors"]
    if args.limit:
        vendors = vendors[: args.limit]

    counts = {"fetched": 0, "skipped": 0, "no_match": 0, "skip_listed": 0, "error": 0}
    for vendor in vendors:
        status, matched = fetch_icon(vendor, force=args.force)
        counts[status] += 1
        symbol = {"fetched": "✓", "skipped": "·", "no_match": "✗",
                  "skip_listed": "—", "error": "!"}[status]
        suffix = f"  ← {matched}" if matched else ""
        print(f"  {symbol} {vendor['name']:<28}{suffix}")

    print()
    print(f"Fetched: {counts['fetched']}   Skipped (existing): {counts['skipped']}   "
          f"Skip-listed: {counts['skip_listed']}   No match: {counts['no_match']}   "
          f"Errors: {counts['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
