# Bulk import and export (CSV)

Issue #41 (FreePBX gap analysis §3.1, 3.3, 3.11). Built 2026-10-20 (0.27.20; ring groups and FreePBX in 0.27.29).

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
| `ring_groups` | `number` | name, description, strategy (ringall/sequential), ring_seconds, ring_busy_members, members (extension numbers in ringing order — the full list), external_members, caller_id_prefix, failover (`type:target` or `hangup`), enabled |
| `queues` | `number` | name, description, strategy (ringall, rrmemory, leastrecent, fewestcalls, random, linear), member_timeout, wrapup_seconds, max_wait_seconds, join_when_empty, announce_position, members (static), dynamic_members (log in with the code), failover, enabled |
| `ivr_menus` | `name` | description, prompt (a recording of the audio library, by name; a missing one is a note, not an error), timeout_seconds, max_retries, allow_direct_dial, keys (`1=extension:1001; 2=ring_group:6000; *=hangup`, the full list), timeout and invalid (`type:target`), enabled |
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

Devices and contacts; a module hook so modules add
kinds; editing rows in the page before importing.

## 5. From FreePBX (issue #42, 0.27.29)

**System → Import and Export → From FreePBX** reads a database dump of the
FreePBX server (`mysqldump asterisk > asterisk.sql`; `.sql`, `.sql.gz`, or
a FreePBX 14 backup tarball that holds one — FreePBX 15+ backups keep the
modules as JSON and are refused with the command to run) and makes the
files of the extensions, ring groups and inbound routes
(`POST /bulk/freepbx/convert`, `extensions.write`; nothing is saved). Each
then goes through **Check the file** and **Import** in that order.

* Tables read: `users`, `devices`, `sip` (caller ID name), `ringgroups`,
  `incoming`, `ivr_details` and `announcement` (names of destinations).
* Extensions: number, name, caller ID name, outbound and emergency caller
  ID, voicemail yes/no. SIP passwords are **not** carried over.
* Ring groups: `hunt` strategies become *sequential*, the others *ring
  all*; members ending in `#` are outside numbers; `grppre` is the caller
  ID prefix; the failover destination is mapped.
* Destinations: `from-did-direct`/`ext-local` → extension, `vmu`/`vmb` →
  voicemail, `ext-group` → ring group, `ext-queues` → queue, `ivr-N` and
  `app-announcement-N` → by name, `ext-meetme` → conference,
  `app-blackhole` → hang up. Anything else (time conditions, day/night,
  misc applications) is a warning to set by hand, as are catch-all routes
  and caller-ID matches.
* FreePBX sites often use 3-digit extensions: widen the numbering plan
  before checking the extensions, or the check reports every row.
* Queues (0.27.31): `queues_config` and `queues_details` — strategy
  (`rrordered` → round robin with memory, `wrandom` → random), ring time,
  wrap-up, maximum wait, join when empty, announce position, static members
  (`Local/<ext>@from-queue` or `PJSIP/<ext>`), failover. Dynamic agents live
  in FreePBX's AstDB, not in the dump: add them on the queue's page.
* IVR menus (0.27.32): `ivr_details`, `ivr_entries` (single-key options;
  longer ones are warnings) and `recordings` (the announcement's name);
  timeout and invalid destinations. The audio is not in the dump: upload
  the recordings under the same names first.
* Not yet: time conditions, voicemail settings from
  `voicemail.conf`, recordings and music on hold.
