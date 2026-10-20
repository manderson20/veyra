# Bulk import and export (CSV)

Issue #41 (FreePBX gap analysis §3.1, 3.3, 3.11). Built 2026-10-20 (0.27.20).

**System → Import and Export** exports extensions, users, inbound routes or
shared voicemail inboxes of one organization as CSV, gives a blank
template, checks a file (dry run) and imports it.

## 1. The file

* The first line names the columns. Every export column is importable, so
  an export edited in a spreadsheet is a valid import; unknown columns are
  refused before any row is read.
* The first column is the key: rows are matched on it (`number`, `email`,
  `did`, `number`). A match is **updated in place**, otherwise the row is
  **created**.
* An **empty cell keeps** the current value; a **dash (`-`) clears** it.
  Yes/no cells take `yes`/`no` (also `true`/`false`, `1`/`0`). Lists
  (`pickup_groups`, `members`, `roles`) are separated by `;`.
* At most 5,000 rows and 5 MB per file; a key appearing twice is an error.

| Kind | Key | Columns |
|---|---|---|
| `extensions` | `number` | display_name, user_email, caller_id_name, caller_id_number, outbound_caller_id_number, outbound_caller_id_name, emergency_caller_id_number, intercom (default/allow/deny), class_of_service, site, building, location, department (by name), max_registrations, enabled, voicemail (yes creates the box with a random PIN; no never deletes one), voicemail_email, voicemail_attach_audio, voicemail_delete_after_email, voicemail_ring_seconds, pickup_groups (the full list: the extension leaves groups not named) |
| `users` | `email` | display_name, enabled, roles (organization-scope role keys, added, never removed), password (temporary; empty for a new user: they set one with "Forgot password") |
| `inbound_routes` | `did` (with `trunk` when given) | trunk (by name), description, destination and after_hours as `type:target` — `extension:1001`, `voicemail:1001`, `voicemail_box:1900`, `ivr:<name>`, `ring_group:<number or name>`, `queue:…`, `announcement:…`, `conference:…`, `call_flow:…`, `fax:…`, `directory` — time_condition (by name), caller_id_prefix, enabled |
| `shared_inboxes` | `number` | name, members (extension numbers), email, attach_audio, delete_after_email, ring_seconds, enabled |

Import users before the extensions that name them.

## 2. How a row is applied

Each row runs through the **same API handlers as the web pages** (their
checks — numbering plan, caller ID rights, classes of service —, audit
entries and events), in one database transaction with a savepoint per row:

* a row that fails is rolled back alone and listed with the reason;
* **Check the file** (`dry_run=true`, the default) rolls the whole
  transaction back and drops the events, so it reports exactly what an
  import would do;
* **Import** commits the rows without errors, then delivers their events
  (webhooks, pending deployment) and records `bulk.import` with the counts.

The handlers' `commit()` is a flush inside the import (`_BulkSession`), and
`bus.hold()` collects events per request context.

## 3. API

```
GET  /bulk/kinds                                       kinds, keys and columns
GET  /bulk/{kind}/export.csv?organization_id=&template=  CSV (read permission of the kind)
POST /bulk/{kind}/import?organization_id=&dry_run=      {csv} → {dry_run, counts, rows[{row, key, action, message, notes}]}
```

Permissions: the kind's write permission in the organization
(`extensions.write`, `users.write`, `routing.write`, `voicemail.write`);
importing users (role grants) asks for a recent sign-in (§ step-up, #137).

## 4. Not yet

Ring groups, queues, IVR menus, devices and contacts; a module hook so
modules add kinds; editing rows in the page before importing.
