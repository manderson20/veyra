# Veyra branding assets

Approved artwork, supplied by the project owner on 2026-10-12 as raster
exports (PNG/ICO) of the complete standalone Veyra logo. There is no vector
source, so there are no SVG files; larger sizes do not add detail.

The UI references these files only through `src/components/Brand.tsx` and
`src/app/layout.tsx` (favicons, manifest). The CLI and installer wordmark is
a separate ASCII treatment in `backend/veyra/cli/` (see below).

## Files

| File | Canvas | Use |
| --- | --- | --- |
| `logo-light.png` | 2200 × 700 | Complete logo + tagline, dark wordmark, for light backgrounds; transparent |
| `logo-dark.png` | 2200 × 700 | Complete logo + tagline, white wordmark, for dark backgrounds; transparent |
| `logo-compact-light.png` | 2200 × 620 | Icon + wordmark without tagline, for light-background navigation |
| `logo-compact-dark.png` | 2200 × 620 | Icon + wordmark without tagline, for dark-background navigation |
| `icon.png` | 1024 × 1024 | The V emblem, transparent, with padding |
| `icon-512.png`, `icon-256.png`, `icon-128.png` | as named | Smaller emblem exports (derived) |
| `app-icon.png` | 1024 × 1024 | Emblem on a rounded navy tile; outside the tile is transparent |
| `app-icon-512.png`, `app-icon-192.png` | as named | Web-manifest icons (derived) |
| `apple-touch-icon.png` | 180 × 180 | Opaque navy square for touch icons (derived) |
| `favicon.ico` | 16–256 px | Seven embedded sizes |
| `favicon-16.png`, `favicon-32.png`, `favicon-48.png` | as named | PNG browser icons (derived) |

The `light` and `dark` suffixes describe the intended **background**, not
the lettering colour.

"Derived" files were resized from the supplied 1024 px `icon.png` and
`app-icon.png` with Pillow (Lanczos) on 2026-10-12; regenerate them from
those two files if the originals change. The owner's branding board and the
supplied CLI text treatments are kept in `docs/branding/`.

Not supplied and not needed by the UI: wordmark-only and monochrome emblem
exports.

## Usage rules

* Keep the native aspect ratio: set the height (or width) and let the other
  dimension follow. Never `object-fit: cover` a logo.
* Never put a wide logo in a clipped square container; use `icon.png` there.
* Use the compact logos in navigation and the full logo with tagline only at
  larger sizes.
* On a dark surface use the `-dark` file; on a light surface the `-light`
  file. `BrandLogo` chooses by theme unless `onDark` is set.

## Colours

Dark Navy `#071629`, Electric Blue `#008CFF`, Teal `#00D4B4`, White `#FFFFFF`.
