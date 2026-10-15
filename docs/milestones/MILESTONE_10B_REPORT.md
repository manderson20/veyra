# Milestone 10b Report — Report Builder

Branch `milestone-10b` (from `main` at 0.15.0). Design:
[REPORT_BUILDER.md](../REPORT_BUILDER.md). Status: **built and checked live
on dev1, awaiting the owner's approval** (to be released as 0.16.0).

## 1. Scope (owner request of 2026-10-15)

"Reports is more or less an overview dashboard; shouldn't I be able to
build a report using filters?", with scheduled email. Placed before module
management, which moves to 0.17.0.

## 2. Results

* **Telephony → Reports** has three tabs: **Overview** (the 0.15.0 page),
  **Build**, **Saved**.
* **Build**: group calls by one or two of day, week, month, hour, weekday,
  direction, outcome, who answered, the called or calling extension, the
  number dialled, trunk, queue, ring group or caller; measure calls,
  answered, missed, voicemail, answer rate, average and total ring and talk
  time, and the share answered within a service level; filter by period,
  direction, outcome, extensions, numbers, trunks, queues, ring groups,
  caller, talk time and **business hours** (inside or outside a time
  condition, holidays included). Relative periods ("yesterday", "last
  week", "this month") are worked out in the organization's time zone.
  Results as a table, bars or a line (two groupings: the three largest
  values of the second, the rest as "Other"), CSV export.
* **Saved**: reports shared with the organization or private, reopened in
  the builder; **emailed** daily, weekly or monthly at a local hour (it
  follows daylight saving) with a summary in the message and the CSV
  attached; "Send now"; the last error is shown.
* Calls record the **queue** and **ring group** they went through (migration
  `0023`, filled in for existing calls from their legs).
* Permission `reports.write` (organization and site administrators) to
  save, share and schedule.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (162 files) |
| Backend pytest | **360 passed** (10b added 4 test functions: periods at month and year boundaries in local time, schedules including the November daylight-saving change, every grouping kind with measures and filters incl. business hours against fixture calls, queue detection, validation, CSV with units, options, saved reports, the emailed CSV attachment, the worker's due run and an error when email is off) |
| `alembic check` | No drift (migration `0023` incl. backfill, upgrade and downgrade) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **39 passed** (chart grouping with "Other", measure formatting) / passed |
| **Owner's `upgrade.sh` on dev1** | 0.15.0-9c90a914c0 → **0.15.0-53f7b1b4dd** (04:09 UTC): schema `0023`, all verify checks OK |

### Live check on dev1 (2026-10-15 04:12-04:16 UTC)

| Check | Result |
|---|---|
| Scheduled email | Temporary email settings pointing at a local test receiver on 127.0.0.1:2525 and a saved report due one minute ago: the worker ran it on its next pass, queued the message, the mail queue delivered it. Subject `[District Phone System] M10b live test: 2026-09-15 to 2026-10-14`, the period resolved in America/Chicago, a summary in the body and `m10b-live-test-20261015.csv` attached; the next run moved to 07:00 local (12:00 UTC) |
| Found | The CSV headers lacked units ("Average talk" with `7.0`): fixed in the final tree (`Average talk (seconds)`, `Answer rate (%)`) |
| Setup mistake | A first attempt used `veyra@veyra-dev1` as sender; Veyra rejected it (no domain), correctly |
| Cleanup | Test report and email settings removed (dev1 has no email settings, as before), receiver stopped |

## 4. Not verified

* The builder in a browser (no browser on the server).
* Reports over real queue and ring group traffic (dev1 has none yet).
* Email through the district's real mail server.

## 5. Known limitations

* At most two groupings and 1000 rows per report; the chart shows the first
  measure.
* Monthly schedules run on days 1-28 only (every month has them).
* A scheduled report runs with the organization's full data; recipients are
  whoever the report's editor names (the schedule editor warns).

## 6. Open items

* **Owner: try Reports → Build and Saved** in the browser; set up email
  (System → Settings) to receive scheduled reports.
* Everything open from Milestone 10 (the §12 questions of REPORTING.md) and
  earlier milestones.

## 7. Next milestone

Milestone 11 — module management and independent updates with the online
module catalog (0.17.0).

## 8. Owner decisions

* 2026-10-15: report builder with scheduled email requested and placed
  before Milestone 11.
* Approval: *pending*.
