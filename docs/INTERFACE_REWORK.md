# Interface Rework (Milestone 9b)

Design for Milestone 9b (roadmap row 9b, 0.12.0): flyout navigation and
dashboard graphs. Owner requests of 2026-10-14:

* "Instead of having all the submenu items underneath each category on
  the left, let's have a flyout menu with all the options. That way the
  main menu won't have any scrolling and we can add as many submenu items
  as we want."
* "A graph of channels, calls internal vs external, which can be separate
  items on the main dashboard."

## 1. Navigation

### 1.1 Today

The sidebar lists every item of every section (Overview, Directory,
Telephony, Provisioning, Modules, System). Telephony alone has fourteen
items plus the planned ones, so the list scrolls on most screens and grows
with every milestone.

### 1.2 Rail and flyout

* The sidebar becomes a **rail of categories** only: one row per section
  with an icon and a label (Overview, Directory, Telephony, Provisioning,
  Modules, System). Six rows never scroll.
* **Clicking** a category opens a **flyout panel** to the right of the
  rail with the category's title, a one-line description and its items in
  the order of `NAV`, planned items last with their "coming later" badge.
  Clicking the same category again, pressing Escape, choosing an item or
  clicking outside closes it. On devices with a pointer, **hovering** a
  category for 150 ms opens its flyout too; moving the pointer into the
  panel keeps it open; leaving both closes it after 250 ms.
* The category of the current page is highlighted in the rail; the current
  item is highlighted in the flyout.
* A category with a single page (Overview → Dashboard) is a plain link in
  the rail, no flyout (owner's browser check, 2026-10-14).
* **Keyboard**: the rail is a vertical list of buttons; Enter or Space
  opens the flyout and moves focus to its first item; Arrow Up/Down move
  within the flyout, Escape returns focus to the category; Tab leaves the
  panel and closes it.
* The **collapse** control stays: collapsed, the rail shows icons only
  (as today) and the flyout works the same, so the collapsed state is now
  as useful as the expanded one.
* **Mobile** (the drawer): the same rail; tapping a category expands its
  items inline under it (accordion) instead of a flyout, because there is
  no room to the right.
* The **top bar** gains a breadcrumb: category › page (for example
  "Telephony › Ring Groups"), so the current place stays visible when the
  flyout is closed.
* Module navigation items (`moduleNavItems`) stay under Modules; the
  category is hidden when a user has no module items and no module
  permission.

### 1.3 Data

`NAV` sections gain `icon` and `description`. Items keep their fields.
`buildNav` and `canSee` are unchanged; the rail hides categories whose
items are all hidden. The planned list and the `/planned/` pages remain.

### 1.4 Tests

Vitest for `nav.ts` (category visibility, active category from a path);
a rendering test of the rail with the testing library is added if the
project already has one, otherwise the keyboard behaviour is checked by
hand and recorded in the report.

## 2. Dashboard graphs

### 2.1 What is measured

Every 30 seconds the worker samples the engine:

| Column | Meaning |
|---|---|
| `channels` | Channels in the engine (`Local/` channels excluded) |
| `calls_external` | Channels on trunk endpoints (`trunk-<slug>`): each outside call has exactly one trunk leg, so this is the number of external calls |
| `calls_internal` | `max(0, (channels − 2 × calls_external) / 2)`: the remaining channels paired up; an estimate while a call is being set up |
| `registrations` | Registered extensions |

Rows go into `call_samples` (migration `0012`: `at` indexed, four
integers). The worker keeps 14 days (about 40,000 rows) and prunes older
rows hourly. When the engine is unavailable the sample is skipped, which
shows as a gap in the graphs rather than zeros.

### 2.2 API

`GET /system/metrics/calls?range=1h|6h|24h|7d` (permission
`system.health.read`) returns `{range, step_seconds, points: [{at,
channels, calls_internal, calls_external, registrations}], current: {…}}`,
downsampled on the server to at most 300 points per series (the maximum
within each bucket, so peaks are not averaged away). `current` is a live
reading from the engine for the headline numbers.

### 2.3 Dashboard

Two new cards on the dashboard, each a separate item as requested:

* **Channels** — an area chart of `channels` with the live number as the
  headline and `registrations` as a thin second line.
* **Calls: internal vs external** — two lines (internal, external) with
  the live numbers as headlines.

Both share a range selector (1 h, 6 h, 24 h, 7 d; default 1 h), refresh
every 30 seconds while the page is open, and show "Not available" when the
engine does not report calls. The existing "Calls and registrations" card
keeps the counts of trunks and extensions.

Charts are a small SVG component of our own (`components/common/Chart.tsx`:
axes, grid, up to three series, hover tooltip with the time and values, a
visually hidden table for screen readers) so no chart library is added to
the bundle.

### 2.4 Tests

Backend: sampler classification (internal, external, Local channels
ignored), retention, API downsampling and range validation, permission.
Frontend: chart scaling and bucket formatting in vitest.

## 3. Out of scope

Call history and reports (Milestone 10) and per-organization graphs
(multi-tenancy, Milestone 14).

## 4. Decisions

* 2026-10-14: owner chose to continue in roadmap order, so 9b follows 9
  directly.
* 2026-10-14 (implementation): the worker's default interval changed from
  60 to 30 seconds so the sampler matches §2.1 without a second loop; the
  external-call count is the number of trunk legs, the internal count the
  paired remainder; the flyout is a fixed panel beside the rail, hidden on
  narrow screens where the drawer expands the category inline; the open
  category is remembered together with the route it was opened on, so a
  navigation closes it without an effect.
