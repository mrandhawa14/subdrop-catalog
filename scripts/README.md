# Catalog refresh helper

`refresh.py` reconciles a set of researched list prices against `vendors.json`. Price *discovery* happens outside the script — by a human or by an agent (e.g. Claude Code) using web search — and is handed in as a plans file. The script is the deterministic half: it diffs the plans against the catalog, prints a human-readable diff, and only writes back when you pass `--apply`. No API keys, no network calls — pure stdlib.

## fetch-app-icons.py — App Store artwork

Fetches the actual App Store icon for each vendor via the public iTunes Search API. Saves 512×512 JPEG payloads to `../logos/<vendor.id>.jpg`. These are the icons users already see on their phones, so the SubDrop dashboard feels like the real services.

```bash
python scripts/fetch-app-icons.py            # only fetch missing
python scripts/fetch-app-icons.py --force    # refetch everything
python scripts/fetch-app-icons.py --limit 5  # smoke-test
```

No external dependencies — pure stdlib. Per-vendor `SEARCH_OVERRIDES` and `COUNTRY_OVERRIDES` inside the script handle ambiguous matches (e.g. Crave is region-locked to the CA store).

Vendors that don't have an App Store presence (`apple_arcade`, `icloud_plus`) are skip-listed and fall back to SF Symbol in the app.

## fetch-logos.py — Simple Icons fallback (legacy)

Pulls monochrome SVGs from Simple Icons (CC0), rasterizes to PNGs. Kept around in case we ever want monochrome silhouettes alongside the colored App Store icons.

```bash
brew install cairo                                       # one-time, macOS only
pip install -r scripts/requirements.txt
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
    python scripts/fetch-logos.py            # only generate missing
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
    python scripts/fetch-logos.py --force    # regenerate everything
```

The `DYLD_FALLBACK_LIBRARY_PATH` is needed on Apple Silicon so `cairocffi` can find Homebrew's libcairo. On Linux/CI no env var is needed (cairo is on the standard loader path).

Vendors without a Simple Icons match are silently skipped.

---

## refresh.py — price reconciliation

No dependencies, no API key — pure stdlib.

```bash
cd /path/to/subdrop-catalog

# 1. Emit a research brief: every vendor + the tiers to verify.
python scripts/refresh.py --emit-brief > brief.json

# 2. Research current list prices (web search) and write a plans file.
#    Start from a skeleton if you like — it pre-fills the current tiers,
#    so you only correct the amounts and add a source_url:
python scripts/refresh.py --emit-template > plans.json

# 3. Dry-run the reconcile to see the proposed diff.
python scripts/refresh.py --plans plans.json

# 4. Apply once it looks right.
python scripts/refresh.py --plans plans.json --apply
```

After `--apply`, review with `git diff vendors.json` and either commit or `git restore` if anything looks off.

### Doing the research in Claude Code

The intended flow: open this repo in Claude Code and ask it to "update the catalog." Claude reads `vendors.json` (or `--emit-brief`), uses its web-search tool to confirm each vendor's current list price from the official pricing page, writes a `plans.json`, then runs `refresh.py --plans plans.json --apply`. No third-party API key is involved — the search happens through the agent.

### Plans file shape

```jsonc
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
```

## What the script will and won't do

- ✅ Reconciles *list* prices (the number on the vendor's pricing page, exclusive of tax).
- ✅ Additive-only matching on `(name, cycle, region, currency)`: a missed tier in the plans file never deletes the catalog tier — it's simply left untouched.
- ✅ Bumps `version` and `updated`, and appends a `priceHistory` entry for every amount change, only when changes are applied.
- ❌ Doesn't touch tax, regional promotions, grandfathered prices, or the user's actual paid amount — those come from on-device sources (statement parsing, etc.) in the SubDrop app.
- ❌ Doesn't update cancellation steps, retention warnings, or vendor metadata. Those need a human edit.
- ❌ Doesn't do any web research itself — that's the agent/human's job (step 2).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No changes detected, or `--apply` succeeded |
| 1 | `--apply` ran but applied nothing (no diffs found) |
| 2 | Dry-run found changes (used by CI to gate a PR) |
| 3 | Configuration error (missing/unparseable plans file, etc.) |

The CI workflow at `.github/workflows/refresh.yml` keys off these codes.
