# Changelog

## v14 - 2026-08-31

Expanded verified country pricing for Canada and the United States.

- Added current US plans for Netflix, Spotify, Disney+, Apple TV+, Apple Music, iCloud+, and Apple Arcade.
- Updated current Canadian Apple Music Individual and Family pricing.
- Added current 6 TB and 12 TB iCloud+ plans for Canada and the US.
- Preserved Apple Music's previous Canadian prices as closed historical windows.
- Added a dated source register so each edited price can be rechecked against the vendor's own page.

No price was created from currency conversion. Missing regional coverage still means unknown.

## v13 — 2026-08-30

Added a six-service professional and creator expansion, bringing the catalog to 42 vendors.

- **Notion**: Plus and Business plans.
- **Cursor**: Pro, Pro+, and Ultra plans.
- **Figma**: Professional Full, Dev, and Collab seats.
- **Midjourney**: Basic, Standard, Pro, and Mega plans.
- **LinkedIn Premium**: Premium Career monthly and yearly plans in Canada and the US.
- **Linear**: Basic and Business annual plans.

Prices were checked against each vendor's official pricing pages on 2026-08-30. Each service includes aliases, category metadata, and a cancellation playbook.

## v12 — 2026-08-30

Refined cancellation guidance to remove em dashes from all catalog copy, keeping the hosted catalog aligned with DueLume's launch UI style. Refreshed the 30-currency exchange-rate snapshot and published the 15-country tax manifest used by the app. No vendor prices, tiers, or cancellation behavior changed.

## v11 — 2026-06-04

Added 6 services (web-search verified prices), and a new **Education** category.

- **Perplexity Pro** (Productivity / AI) — US: $20/mo, $200/yr.
- **Google Gemini** (Productivity / AI) — CA: Google AI Plus $10.99, Pro $26.99, Ultra $139.99 (per gemini.google/ca).
- **Amazon Music Unlimited** (Entertainment) — CA Individual $9.99/mo.
- **Canva** (Productivity) — CA Pro $12.99/mo, $119.99/yr.
- **Duolingo** (Education) — CA Super $17.49/mo, $119.99/yr; Super Family $149.99/yr.
- **Kindle Unlimited** (News & Reading) — CA $11.99/mo (post-Aug-2025 increase).

Each ships with a cancellation playbook. Duolingo monthly and the Canva/Duolingo aggregator-sourced figures are medium-confidence — worth a recheck against the vendor's own page before relying on them.

## v10 — 2026-06-04

Price refresh (web-search verified, CA region).

- **Netflix Standard** (monthly): $30.99 → **$18.99**. Corrects a value left over from the Phase-1 test spikes (v6–v9); $18.99 is the real post-Jan-2025 Canadian list price.
- **Apple Music Individual** (monthly): $11.99 → **$10.99** (per apple.com/ca/apple-music).
- **Apple Music Family** (monthly): $17.99 → **$16.99** (per apple.com/ca/apple-music).

Verified unchanged this pass: Spotify (already reflects the May 2026 CA hike), Disney+, Apple TV+. YouTube Premium left as-is pending a reliable source (aggregator data conflicted with a reported increase).

Tooling: `scripts/refresh.py` no longer depends on a third-party model/API key — price discovery is now done by an agent (or human) with web search, and the script reconciles the resulting plans file against the catalog.

## v1 — 2026-04-25

Initial catalog. 30 vendors seeded from SubDrop's bundled `PopularServices.json`.

- Coverage: Entertainment, Productivity, Gaming, Health & Fitness, News & Reading, Cloud & Dev, Communication, Shopping, Security.
- Regions: CA (full), US (partial — added where prices are well-documented).
- Cancellation playbooks: filled for top 15 vendors with publicly-documented cancel flows. Others have `method: "unknown"` until verified.
- Price history: empty for v1. Will be populated retroactively as price changes are confirmed.
