# Report Builder (Milestone 10b)

Design for Milestone 10b (roadmap row 10b, 0.16.0). Owner request of
2026-10-15: "reports is more or less an overview dashboard; shouldn't I be
able to build a report using filters?", with scheduled email.

The data is the call history of Milestone 10 ([REPORTING.md](REPORTING.md)
§3). The fixed page stays as the **Overview** tab of Telephony → Reports;
the builder and the saved reports are new tabs.

## 1. A report definition

A report is a definition (JSON, validated by the API), run on demand or on
a schedule:

| Part | Choices |
|---|---|
| **Group by** (0-3) | `day`, `week`, `month`, `hour` (0-23), `weekday`, `direction`, `outcome`, `answered_by` (extension that answered), `called_extension`, `calling_extension`, `did`, `trunk`, `queue`, `ring_group`, `caller` (calling number) |
| **Measures** (1+) | `calls`, `answered`, `missed` (missed + abandoned), `voicemail`, `answer_rate` (%), `avg_ring`, `total_ring`, `avg_talk`, `total_talk`, `within_sl` (% of answered calls answered within `sl_seconds`, default 20) |
| **Filters** | period, organization, directions, outcomes, extensions (any side), DIDs, trunks, queues, ring groups, caller number contains, minimum talk seconds, **business hours** (inside or outside a time condition's ranges and holidays) |
| **Period** | relative: `today`, `yesterday`, `last_7_days`, `last_30_days`, `this_week`, `last_week`, `this_month`, `last_month`, `this_year`; or `custom` from/to dates. Relative periods are resolved in the organization's time zone when the report runs, so a scheduled "yesterday" is always the previous day there |
| **Show as** | `table`, `bars`, `line` (the table is always available) |
| **Sort and limit** | by any measure or the grouping, ascending or descending; top N (default 100, at most 5000 rows since 0.27.30, #139) |

Two groupings give a pivot-like table: for example *answered_by* × *week*
with *calls* and *avg_talk*.

### Queue and ring group of a call

Calls gain `queue` and `ring_group` (the slug, migration `0023`), set when
the legs are folded: a leg whose context is `veyra-queue-<slug>` or
`veyra-rg-<slug>` (or a Local channel into one) names it. Existing calls
are filled in by the migration from their legs.

## 2. Saved and shared reports

`saved_reports`: organization, name, description, definition, owner,
`shared` (visible to everyone in the organization with `reports.read`;
otherwise only the owner and administrators), and an optional schedule.

## 3. Scheduled email

A schedule says **when** (`daily` at an hour; `weekly` on a weekday at an
hour; `monthly` on day 1-31 at an hour (a shorter month sends on its last day; 0.27.30), all in the organization's time
zone) and **to whom** (up to 20 addresses). The worker checks every pass;
a due report is run, rendered as CSV (and a short plain-text summary of the
first rows in the message body) and queued as an email with the CSV
attached through the SMTP settings of M7. `last_sent_at`, `next_run_at`
and the last error are shown in the list. "Send now" sends one at once.

Recipients receive data about calls; the schedule editor says so and the
audit log records schedule changes and sends.

## 4. Permissions and API

* `reports.read`: run reports (Overview, builder), see shared reports.
* `reports.write` (new; organization administrators, site administrators):
  save, share and schedule reports.

```
POST /reports/run                    definition → {columns, rows, totals, period}
POST /reports/run.csv                the same as CSV
GET/POST /saved-reports              (?organization_id=)
GET/PATCH/DELETE /saved-reports/{id}
POST /saved-reports/{id}/run | /run.csv | /send
GET  /reports/options?organization_id=   the extensions, DIDs, trunks, queues, ring groups and time conditions to filter by
```

## 5. Interface

Telephony → Reports with tabs **Overview** (the 0.15.0 page), **Build**
(group by, measures, filters, period, show as; Run; result as a table and a
chart; Export CSV; Save), **Saved** (list with schedule state; open, run,
edit, send now, delete).

## 6. Testing

Unit: every grouping and measure against fixture calls (time zones, week
starts on Monday, empty groups), filters including business hours and
holidays, relative periods at month and year boundaries, sort and limit,
queue and ring group detection, schedule computation (daily, weekly,
monthly, DST changes), the email with its attachment, permissions and
sharing. Live: a saved report emailed to a local SMTP sink on dev1.

## 7. Decisions

* 2026-10-15: owner asked for a report builder with scheduled email, before
  module management (now 0.17.0).

*0.27.30 (issue #139):* up to three groupings (the chart uses the first for its axis and the second for its series), at most 5000 rows, the chart's measure is chosen under the chart, monthly schedules on any day.
