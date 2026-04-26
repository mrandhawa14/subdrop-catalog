# Catalog refresh helper

`refresh.py` asks Claude (with the web_search server tool) to verify the current list price for every vendor tier in `vendors.json`. It prints a human-readable diff of proposed changes; it only writes back to `vendors.json` when you pass `--apply`.

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

## refresh.py — price verification

Uses Gemini 2.5 Flash with Google Search grounding to verify the current list price for every vendor tier in `vendors.json`.

```bash
cd /path/to/subdrop-catalog
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

export GEMINI_API_KEY=...                # or GOOGLE_API_KEY
python scripts/refresh.py                # dry-run, prints diff
python scripts/refresh.py --limit 3      # smoke-test 3 vendors
python scripts/refresh.py --apply        # write changes to vendors.json
```

After `--apply`, review with `git diff vendors.json` and either commit or `git restore` if anything looks off.

## Cost

One Gemini 2.5 Flash call per tier with search grounding. ~30 tiers per full run; expect cents per run on the paid tier, free on the AI Studio free tier (subject to rate limits).

## What the script will and won't do

- ✅ Verifies *list* prices (the number on the vendor's pricing page, exclusive of tax).
- ✅ Refuses to propose a change if the model returns a different currency than the tier expects (guards against the model finding the US price for a CA tier).
- ✅ Bumps `version` and `updated` only when changes are applied.
- ❌ Doesn't touch tax, regional promotions, grandfathered prices, or the user's actual paid amount — those come from on-device sources (statement parsing, etc.) in the SubDrop app.
- ❌ Doesn't update cancellation steps, retention warnings, or vendor metadata. Those need a human edit.
- ❌ Doesn't fix entries where the tier `name` or `id` is ambiguous — review those by hand.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No changes detected, or `--apply` succeeded |
| 1 | `--apply` ran but applied nothing (no diffs found) |
| 2 | Dry-run found changes (used by CI to gate a PR) |
| 3 | Configuration error (missing API key, missing file, etc.) |

The CI workflow at `.github/workflows/refresh.yml` keys off these codes.
