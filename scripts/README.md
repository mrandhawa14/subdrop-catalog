# Catalog refresh helper

`refresh.py` asks Claude (with the web_search server tool) to verify the current list price for every vendor tier in `vendors.json`. It prints a human-readable diff of proposed changes; it only writes back to `vendors.json` when you pass `--apply`.

## Run locally

```bash
cd /path/to/subdrop-catalog
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
python scripts/refresh.py            # dry-run
python scripts/refresh.py --limit 3  # smoke-test on 3 vendors
python scripts/refresh.py --apply    # write changes to vendors.json
```

After `--apply`, review the diff with `git diff vendors.json` and either commit or `git restore` if something looks wrong.

## Cost

Roughly one Claude Sonnet 4.6 call per tier. With ~30 tiers and web_search enabled, expect well under $1 per full run.

## What the script will and won't do

- ✅ Verifies *list* prices (the number on the vendor's pricing page, exclusive of tax).
- ✅ Refuses to propose a change if the model returns a different currency than the tier expects (guards against the model finding the US price for a CA tier).
- ✅ Bumps `version` and `updated` only when changes are applied.
- ❌ Doesn't touch tax, regional promotions, grandfathered prices, or the user's actual paid amount — those come from on-device sources (StoreKit, statement parsing) in the SubDrop app.
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
