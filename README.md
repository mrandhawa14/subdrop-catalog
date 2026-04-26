# subdrop-catalog

Public reference catalog of subscription services consumed by [SubDrop](https://github.com/mrandhawa14/SubDrop) — a privacy-first iOS subscription tracker.

## What's in here

- **`vendors.json`** — the catalog itself: vendor names, categories, list prices by region, cancellation playbook (URL, method, steps, retention warnings, est. time), known price history.
- **`schema.json`** — JSON Schema describing the catalog shape. Bumps when the structure changes.
- **`CHANGELOG.md`** — human-readable log of what changed each version.

## How SubDrop uses it

The app fetches `vendors.json` at most once every 24 hours, caches it locally, and falls back to a bundled snapshot when offline or on first launch.

**No user data is sent.** The fetch is a plain GET — no identifiers, no analytics, no cookies. SubDrop's "Data Not Collected" privacy label is preserved.

The catalog supplies *reference* prices and metadata. The user's *actual* paid amount (including tax) comes from on-device sources: StoreKit for App Store subscriptions, statement/receipt parsing for everything else. The catalog is never the source of truth for what a user pays — it's the source of truth for "what's the list price?" and "how do I cancel this?"

## Schema (v1)

```jsonc
{
  "schema": 1,             // schema version — app refuses higher versions
  "version": 1,            // content version — monotonic, bumps every update
  "updated": "2026-04-25T00:00:00Z",
  "vendors": [
    {
      "id": "netflix",
      "name": "Netflix",
      "aliases": ["NFLX"],
      "domain": "netflix.com",
      "category": "Entertainment",
      "tags": ["streaming", "video"],
      "iconName": "play.rectangle.fill",  // SF Symbol fallback
      "colorHex": "#E50914",
      "tiers": [
        { "id": "standard_ads_us", "name": "Standard with ads", "currency": "USD", "amount": 7.99, "region": "US" },
        { "id": "standard_ca",     "name": "Standard",          "currency": "CAD", "amount": 16.49, "region": "CA" }
      ],
      "trial": { "lengthDays": 0 },
      "cancellation": {
        "method": "web",
        "url": "https://www.netflix.com/cancelplan",
        "steps": [
          "Sign in at netflix.com",
          "Account → Membership → Cancel Membership",
          "Confirm cancellation (decline retention offer)"
        ],
        "retentionOffer": "May offer 50% off for two months. Decline if you actually want to cancel.",
        "estimatedMinutes": 3
      },
      "priceHistory": [
        { "tierId": "standard_ca", "currency": "CAD", "amount": 14.99, "effectiveFrom": "2023-10-18" },
        { "tierId": "standard_ca", "currency": "CAD", "amount": 16.49, "effectiveFrom": "2024-10-15" }
      ]
    }
  ]
}
```

### Field notes

- **`id`**: stable lowercase slug. Never reused, never renamed.
- **`region`**: ISO 3166-1 alpha-2. v1 ships `US` and `CA` only.
- **`currency`**: ISO 4217. Always matches what the vendor charges in that region.
- **`tiers[].amount`**: vendor's *list* price, exclusive of tax. The user's app derives tax = actual − list.
- **`cancellation.method`**: `web` | `app` | `phone` | `email` | `unknown`.
- **`priceHistory`**: optional. When present, lets the app show "↑ went up $X since `effectiveFrom`" badges.
- **`iconName`**: SF Symbol name used until proper logo PNGs ship in v1.1.

## Maintenance

This catalog is solo-maintained today. Updates aim for ~weekly cadence on top vendors.

Anyone is welcome to open a PR adding a vendor or correcting a price — please cite a public source (the vendor's own pricing page is best). Changes ship on merge to `main`.

### Automated price-check helper

`scripts/refresh.py` uses Claude with web search to verify current list prices. Run it locally for a dry-run, or trigger the GitHub Actions workflow (manual by default — uncomment the `schedule:` block in `.github/workflows/refresh.yml` to enable a weekly cron). See [`scripts/README.md`](./scripts/README.md) for usage.

The workflow needs an `ANTHROPIC_API_KEY` repo secret and opens a PR when it finds proposed changes; nothing merges automatically.

## Hosting

Served via GitHub Pages from `main`. The canonical URL is:

```
https://mrandhawa14.github.io/subdrop-catalog/vendors.json
```

## Versioning

- **Schema version** (`schema`): incompatible structural changes only. Apps refuse newer schemas they don't understand.
- **Content version** (`version`): bumps every merge that changes vendor data. Used for cache invalidation.

## License

MIT — see [LICENSE](./LICENSE). Use this data for whatever you like; attribution appreciated, not required.
