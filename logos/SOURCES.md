# Logo asset provenance

Most files in this directory are the service's real App Store artwork fetched
through Apple's public iTunes Search API by `scripts/fetch-app-icons.py`.

The following services do not expose a canonical standalone App Store icon.
Their checked-in JPEGs use the closest official service or brand artwork and
are intentionally preserved during forced App Store refreshes:

| Catalog ID | Source | Treatment |
|---|---|---|
| `icloud_plus` | [Apple iCloud+ product artwork](https://www.apple.com/icloud/) | Official iCloud service icon, flattened to a 512 px JPEG. |
| `apple_arcade` | [Apple Arcade product identity](https://www.apple.com/apple-arcade/) and the Apple Arcade brand glyph | White Arcade glyph on a high-contrast square gradient for small-row legibility. |
| `cursor` | [Cursor brand guidelines](https://cursor.com/brand) | Official 2.5D light app icon from Cursor's downloadable brand kit. |
| `midjourney` | [Midjourney trademark policy](https://docs.midjourney.com/hc/en-us/articles/32084281102349-Midjourney-Trademark-Policy) | Official sailboat mark on a dark square field for small-row legibility. |

These marks identify third-party services in a reference catalog. Their owners
retain all trademark rights; inclusion does not imply endorsement or affiliation.
