# Milestone 9b Report — Interface Rework

Branch `milestone-9b` (from `main` at 0.11.0). Design:
[INTERFACE_REWORK.md](../INTERFACE_REWORK.md). Status: **delivered,
awaiting the owner's browser check and approval.**

## 1. Scope (owner requests of 2026-10-14)

* A flyout menu like Infinite Campus: the main menu shows the categories
  only, never scrolls, and can take as many pages as later milestones add.
* Graphs of channels and of calls internal versus external, as separate
  items on the dashboard.

## 2. Results

* **Navigation rail**: six categories (Overview, Directory, Telephony,
  Provisioning, Modules, System) with an icon and a label each; the
  current page's category is highlighted. Clicking a category, or hovering
  it for 150 ms on a device with a pointer, opens a **flyout panel** with
  the category's title, a description and its pages (planned ones last
  with their badge). Escape, choosing a page, clicking the category again
  or clicking outside closes it. Enter on a category moves focus into the
  flyout; Arrow Up/Down move between pages; Escape returns focus to the
  rail. The collapse control keeps an icon-only rail where the flyout
  works the same.
* **Mobile drawer**: tapping a category expands its pages inline.
* **Breadcrumb** in the top bar: category › page.
* **Sampler**: the worker (now every 30 s) records channels (`Local/`
  legs excluded), external calls (trunk legs), the internal estimate and
  registered phones into `call_samples` (migration `0012`), pruned after
  14 days.
* **API**: `GET /system/metrics/calls?range=1h|6h|24h|7d` with
  server-side downsampling (maximum per bucket, at most 300 points) and a
  live `current` reading.
* **Dashboard**: two cards, **Channels** (area, with registered phones as
  a second line) and **Calls: internal vs external**, sharing a range
  picker and refreshing every 30 s; "Not available" when the engine does
  not report calls. The chart is a small SVG component of our own with a
  hover readout and a visually hidden table.

## 3. Testing (final tree, 2026-10-14)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (122 files) |
| Backend pytest | **294 passed** (new: classification of trunk, phone and `Local/` legs; record, prune, bucketed series and step sizes; the API's ranges, permission and the not-running engine) |
| `alembic check` | No drift (migration `0012`); downgrade `0011` / upgrade head clean |
| Frontend lint / typecheck / vitest | Clean (one pre-existing warning) / clean / **34 passed** (new: active location and rail icons; chart scales, axis maximum and tick labels) |
| Frontend `npm run build` | Passed |
| **Owner's `upgrade.sh` on dev1** | 0.11.0-b2315aff97 → 0.11.0-f79c739cf5 (2026-10-14 17:16 UTC): migration `0012` applied, all verify checks OK; the worker recorded its first `call_samples` row within a minute (channels 0, registrations 0 on an idle dev1); the metrics endpoint answers 401 without a session as expected |
| **Owner's browser check** | Flyouts look good (2026-10-14); Overview changed to a direct link; keyboard, collapsed rail, mobile drawer and the graphs with traffic still to be looked at |

The rendering of the rail and flyout was checked by reading the generated
markup and styles, not in a browser (no browser on the development host);
the owner's check in §6 is the visual verification.

## 4. Not verified

* Visual appearance in light and dark themes and on narrow screens.
* Graphs with real call volume (dev1 has no live traffic; the sampler
  records zeros until phones make calls).

## 5. Known limitations

* The internal-call figure is an estimate while a call is being set up
  (one leg exists before the second one answers).
* Samples are not per organization; per-tenant graphs come with
  multi-tenancy (Milestone 14).
* The flyout opens on hover only on devices that report a fine pointer.

## 6. Open items

* Owner: upgrade dev1 from `~/veyra` on `milestone-9b`, open the
  interface and check the items of §3's last row; report anything that
  looks wrong before approval.
* From Milestone 9: hardware checks with the VVX phones, the paging
  questions, and the handset checks of Milestones 5, 7 and 8.

## 7. Next milestone

9c — Paging and recordings (roadmap row 9c), then 9d — Firewall and phone
trust, per the owner's "continue in order".

## 8. Owner decisions

* 2026-10-14 browser check: "The flyouts look good, I think the Overview
  should just be a link to the dashboard and not really a menu flyout" →
  categories with one page are plain links in the rail.
* Approval: *pending*.
