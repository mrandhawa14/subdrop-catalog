#!/usr/bin/env python3
"""
Fetch vendor logos from Simple Icons (CC0) and render them as 256×256
white-on-transparent PNGs into ../logos/<vendor.id>.png.

Usage:
    pip install -r scripts/requirements.txt
    python scripts/fetch-logos.py            # only generate missing logos
    python scripts/fetch-logos.py --force    # regenerate all
    python scripts/fetch-logos.py --size 512 # render at a different size

Why monochrome white-on-transparent: the SubDrop UI layers logos over a
brand-color tile (the vendor's `colorHex`). A white silhouette on top of
the tinted tile gives consistent recognizability across the dashboard
without per-vendor full-color asset wrangling.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

try:
    import cairosvg
except ImportError:
    print("error: install dependencies first → pip install -r scripts/requirements.txt",
          file=sys.stderr)
    sys.exit(3)


CATALOG_PATH = Path(__file__).resolve().parent.parent / "vendors.json"
LOGOS_DIR = Path(__file__).resolve().parent.parent / "logos"

SIMPLE_ICONS_TEMPLATE = "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg"


def fetch_svg(slug: str) -> str | None:
    """Downloads the Simple Icons SVG for `slug`. Returns None on 404 / error."""
    url = SIMPLE_ICONS_TEMPLATE.format(slug=slug)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            if r.status != 200:
                return None
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"  ! fetch failed for {slug}: {e}", file=sys.stderr)
        return None


def force_white_fill(svg: str) -> str:
    """
    Simple Icons SVGs ship with a single black `<path>` and no fill attribute,
    relying on `currentColor`. Force a white fill on the root <svg> element so
    the rasterized PNG is clearly white-on-transparent regardless of viewer.
    """
    if "fill=" in svg.split(">", 1)[0]:
        # already has a root fill — replace it
        return re.sub(r'(<svg[^>]*?)\sfill="[^"]*"', r'\1 fill="#FFFFFF"', svg, count=1)
    return svg.replace("<svg ", '<svg fill="#FFFFFF" ', 1)


def render_png(svg: str, size: int) -> bytes:
    """SVG → PNG bytes at the given pixel size."""
    return cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=size,
        output_height=size,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch and re-render every logo, overwriting existing files.")
    parser.add_argument("--size", type=int, default=256,
                        help="Output PNG side length in pixels (default 256).")
    args = parser.parse_args()

    if not CATALOG_PATH.exists():
        print(f"error: {CATALOG_PATH} not found", file=sys.stderr)
        return 3

    LOGOS_DIR.mkdir(exist_ok=True)
    catalog = json.loads(CATALOG_PATH.read_text())

    fetched = 0
    skipped = 0
    missing: list[str] = []

    for vendor in catalog["vendors"]:
        slug = vendor.get("simpleIconsSlug")
        out = LOGOS_DIR / f"{vendor['id']}.png"

        if not slug:
            missing.append(vendor["id"])
            continue

        if out.exists() and not args.force:
            skipped += 1
            continue

        print(f"  → {vendor['name']:<28} (slug: {slug})")
        svg = fetch_svg(slug)
        if not svg:
            missing.append(f"{vendor['id']} (fetch failed)")
            continue

        try:
            png = render_png(force_white_fill(svg), args.size)
        except Exception as e:
            print(f"    ! render failed: {e}", file=sys.stderr)
            missing.append(f"{vendor['id']} (render failed)")
            continue

        out.write_bytes(png)
        fetched += 1

    print()
    print(f"Fetched: {fetched}   Skipped (existing): {skipped}   Missing: {len(missing)}")
    if missing:
        print("Vendors without logos (will fall back to SF Symbol in the app):")
        for m in missing:
            print(f"  · {m}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
