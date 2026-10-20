# Reporting and Monitoring (Milestone 10)

Design for Milestone 10 (roadmap row 10, 0.15.0): call history, call
recording, reports and dashboards, and monitoring. The interface has shown
"Call History" and "Call Recording" as coming later since Milestone 4;
this milestone delivers them.

Sections marked *(spike)* need a measurement on dev1 before the code is
final; the rest can be built from this document.

## 1. What exists today

* Asterisk's CDR engine runs in **simple mode** with `cdr_csv` writing
  `/var/log/asterisk/cdr-csv/Master.csv`; **unanswered calls are not
  logged**; `cdr_pgsql` and the others are not configured. Veyra reads none
  of it.
* `call_samples` (9b): every worker pass stores the number of channels,
  internal and external calls and registered phones; the dashboard graphs
  them over 1 h to 7 days.
* `queue_log` (Asterisk's queue event file) is written but not read.
* The generated dialplan already marks calls with inherited variables
  (`VEYRA_ROUTE`, `VEYRA_DID`, `VEYRA_EMERGENCY`, depth counters).
* Nothing is recorded; there is no `MixMonitor` anywhere.

## 2. Objects

| Object | Table | Purpose |
|---|---|---|
| **Call** | `calls` | One row per call as a person sees it (one Asterisk `linkedid`): organization, direction, from, to, the DID or route, start, answer, end, talk and ring time, outcome, who answered, recording |
| **Call leg** | `call_legs` | The CDR rows behind a call (a ring group rings five phones: five legs, one answered), kept for troubleshooting and the detail view |
| **Recording** | `call_recordings` | A recorded call: file, format, size, duration, policy that recorded it, retention date, deleted flag |
| **Recording policy** | `recording_policies` | What to record in an organization: direction, scope (everyone, chosen extensions, queues, ring groups, routes), announcement, retention |
| **Queue event** | `queue_events` | Parsed `queue_log` lines for queue reports (wait time, abandoned, answered by) |
| **Alert rule** | `alert_rules` | Monitoring: a condition (trunk down, engine down, disk, backups, certificate, firewall bans spike) and who is told |
| **Alert** | `alerts` | Raised and cleared alerts with times, shown on the dashboard and sent by email |

## 3. Call history

### 3.1 Getting the records out of Asterisk

Veyra adds a managed `cdr_custom.conf` that writes **one CSV line per
CDR** to `/var/log/asterisk/cdr-custom/veyra.csv` (the module's fixed
directory): a format tag first, then the standard CDR fields and Veyra's
own variables, every field through `CSV_QUOTE` so caller names with commas
or quotes cannot break a line:

```
veyra.csv => "v2",${CSV_QUOTE(${CDR(uniqueid)})},${CSV_QUOTE(${CDR(linkedid)})},
  ${CSV_QUOTE(${CDR(start)})},${CSV_QUOTE(${CDR(answer)})},${CSV_QUOTE(${CDR(end)})},
  ${CSV_QUOTE(${CDR(duration)})},${CSV_QUOTE(${CDR(billsec)})},
  ${CSV_QUOTE(${CDR(disposition)})},${CSV_QUOTE(${CDR(src)})},${CSV_QUOTE(${CDR(clid)})},
  ${CSV_QUOTE(${CDR(dst)})},${CSV_QUOTE(${CDR(dcontext)})},${CSV_QUOTE(${CDR(channel)})},
  ${CSV_QUOTE(${CDR(dstchannel)})},${CSV_QUOTE(${CDR(lastapp)})},
  ${CSV_QUOTE(${CDR(veyra_rec)})},${CSV_QUOTE(${CDR(veyra_flag)})}
```

Checked on dev1 (Asterisk 22.5, 2026-10-15): `CSV_QUOTE` and `FILTER`
exist, there is no JSON encoding function (only `JSON_DECODE`), so CSV it
is; the tag lets the format change without misreading old lines. `v2`
(0.27.9, #135) adds `veyra_flag`, set by the dialplan when Veyra refuses a
call (`blocked`: caller block list, `denied`: class of service); the call's
outcome is then `blocked` or `denied`. `v1` lines are still read.

Measured on dev1 with a temporary mapping and a runtime test context
(both removed afterwards): `cdr_custom` does **not** see channel variables
(`${VEYRA_ORG}` was empty on every leg), only **CDR variables**, and a CDR
variable appears only on the CDR of the channel that set it (and the
bridge CDR forked from it). Every leg carries the same `linkedid`. Hence
§3.2.

Why a file and not `cdr_pgsql`: Asterisk would need a database password,
and CDRs written while PostgreSQL is down (an upgrade, a restart) would be
lost. The file survives both; the worker reads it like the firewall reads
the security log (inode and offset kept in the database, rotation
followed), so nothing is read twice and nothing is missed. `cdr.conf`
becomes a managed stub with `unanswered = yes` so missed calls appear, and
`cdr_csv` stays loaded: changing `modules.conf` makes the installer restart
Asterisk, which drops calls, and its `Master.csv` is harmless (rotated with
the other Asterisk logs).

### 3.2 Organization and direction

Rather than marking every Veyra context (only CDR variables reach the
file, §3.1), the worker **resolves calls from the channel names** each CDR
carries: `PJSIP/<endpoint>-<n>` where the endpoint is either an
extension's endpoint name (Veyra knows its organization) or
`trunk-<slug>`; `Local/…` legs of ring groups and queues are grouped with
the rest by `linkedid`.

* **direction**: a trunk on the calling side → `inbound`; a trunk on the
  called side → `outbound`; phones only → `internal` (a phone call
  forwarded out through a trunk counts as outbound).
* **organization**: the calling phone's, else the called phone's, else
  the inbound route matching the dialled DID.
* The only mark in the dialplan is the recording: the recording
  subroutine sets `CDR(veyra_rec)` (§4.2), which the CSV carries.

So the mapping of §3.1 needs only `${CDR(veyra_rec)}` beyond the standard
fields; the `veyra_org`/`veyra_dir`/`veyra_route`/`veyra_did` columns are
dropped from it.

### 3.3 From legs to calls

Every worker pass reads the new lines, stores them as `call_legs` and
folds them into `calls` by `linkedid`:

* **from**: the first leg's caller ID; **to**: the dialled number
  (`dst` of the first leg), and for inbound calls the DID.
* **started / answered / ended**: earliest start, earliest answer, latest
  end; **ring time** = answered − started, **talk time** = ended −
  answered.
* **outcome**: `answered`, `missed` (rang, nobody answered), `busy`,
  `failed` (congestion, no route), `voicemail` (ended in VoiceMail),
  `abandoned` (queue caller hung up waiting).
* **answered by**: the extension of the answered leg's `dstchannel`
  (endpoint name → extension).
* A call is final once no leg has been added for 60 seconds after its
  latest end; until then it is shown as "in progress" or updated.

Endpoint names carry the organization's prefix; numbers and names shown in
the interface are the extension numbers and display names, never the
endpoint names.

### 3.4 Retention

Call history is kept **400 days** by default (a school year plus a margin),
configurable per installation (System → Settings, 30 to 3650 days); the
worker deletes older calls and legs nightly. Exports are not tracked once
downloaded.

### 3.5 Who sees what

* `calls.history.read` (organization administrator, site administrator,
  technician, read-only): the call history of the organizations they
  manage, scoped like everything else.
* **Every user** sees their own calls (any extension assigned to them) at
  `/me/calls`, on their account page and in the Companion extension
  ("Recent calls", click to call back).
* `calls.history.export`: CSV export (organization administrators).

### 3.6 Search and export

Filters: date range (default today), organization, direction, outcome,
number or name (matches from, to, DID and answered by), extension, queue,
ring group, minimum duration, recorded. Sort by start, newest first. CSV
export streams the same query, capped at 100 000 rows, with the columns of
the table plus the legs as a count.

## 4. Call recording

### 4.1 Policies

Recording is **off** until a policy enables it. A policy belongs to an
organization and says:

* **What**: direction (inbound, outbound, internal, any) and scope:
  everyone, chosen extensions, chosen queues, chosen ring groups, chosen
  inbound routes.
* **Announcement**: an audio library recording played to the caller
  before the call connects (default for inbound: on, the shipped "This call
  may be recorded" prompt); the administrator decides what the law and the
  district require.
* **Retention**: days to keep the files (default 90), then deleted by the
  worker; a recording can be **held** (exempt from deletion) by someone
  with `recordings.manage`, for example for a records request.
* **On demand** *(later in the milestone if time allows)*: a feature code
  during a call (`*1`, Asterisk's `automixmon`) for users allowed by the
  policy.

### 4.2 How a call is recorded

The generator evaluates policies into the dialplan: where a matching call
is about to be bridged (extension dial, ring group, queue, outbound route),
it calls a `veyra-record` subroutine that plays the announcement once, sets
`__VEYRA_CALLREC` to a new identifier (the channel's `UNIQUEID`), copies it
into `CDR(veyra_rec)` so the call record names the file, and starts
`MixMonitor(<data>/recordings/<org>/<yyyy>/<mm>/<dd>/<id>.wav,b)` (`b`:
only the bridged part, no ringing or hold music). Only one recording per
call: the subroutine returns if `VEYRA_CALLREC` is already set (not `VEYRA_REC`, which the `*95` prompt recording already uses) (a transfer
keeps recording into the same file).

After the call the worker finds the file through the call's `rec` field,
converts it to **Opus** (or MP3 when the browser needs it, *spike*) with
`ffmpeg` at about 16 kbit/s mono (≈ 7 MB per hour instead of 57 MB), checks
it, records size and duration in `call_recordings` and deletes the WAV.

Directories: `<data>/recordings` 2770 `veyra:asterisk` (Asterisk writes,
Veyra converts and deletes), like the prompts directory. Disk use appears
on the System → Health page; a monitoring rule warns before the disk fills
(§6).

### 4.3 Listening and downloading

* `recordings.read`: listen in the browser (streamed, byte ranges) and
  download; **every playback and download is written to the audit log**
  (who, which call, when).
* `recordings.manage`: hold, release, delete before retention.
* Neither is granted to standard users by default; an organization can
  give its staff `recordings.read` for their own calls only
  (`recordings.read_own`).

### 4.4 Privacy

Recordings never leave the server except by a user's download; they are
not attached to emails. Since 0.27.4 (#122, migration `0057`) every
recording is encrypted at rest: the worker seals the converted file with
its own AES-256-GCM key (`<ref>.ogg.enc`) and stores that key wrapped by
the installation key in `call_recordings.key_ciphertext` (purpose
`recording.key:<id>`, in the rotation registry, so a key rotation re-wraps
keys and never rewrites audio). Playback decrypts in memory and serves byte
ranges. Recordings stored before are encrypted by the worker, twenty per
pass. Voicemail messages stay in Asterisk's spool, unencrypted (Asterisk
must read them).

## 5. Reports and dashboards

### 5.1 Reports page (Telephony → Reports)

For a chosen organization and period (today, 7 days, 30 days, a custom
range):

* **Calls per day** by direction (stacked bars) and **answered vs missed**.
* **Busiest hours**: a weekday × hour grid of call counts.
* **Average ring time and talk time**, inbound answered within 20 s.
* **Top extensions** by calls and talk time; **missed calls by
  extension**.
* **Trunk usage**: calls, talk time and the most calls up at once per trunk
  (a sweep over the calls table's start and end times; 0.27.2, #121).
* **Queues** (from `queue_events`): calls offered, answered, abandoned,
  average wait, answered within the service level, per agent answered.
* **Ring groups**: answered by whom, missed.

Every chart has a table view and a CSV download, as the dashboard charts
already have hidden tables (now clipped correctly, 0.13.2).

### 5.2 Dashboard additions

The dashboard (Overview) gains a **"Calls today"** item (total, answered,
missed, by direction, compared with the same weekday last week) and an
**"Alerts"** item (§6). Existing graphs stay.

## 6. Monitoring

### 6.1 Alerts

The worker evaluates alert rules every minute; an alert is **raised** when
its condition holds for its delay and **cleared** when it no longer does.
Built-in rules (each can be switched off or tuned):

| Rule | Condition (default) |
|---|---|
| Telephony engine down | Asterisk or ARI unreachable for 2 minutes |
| Trunk down | A registration trunk unregistered, or an IP trunk not answering OPTIONS, for 5 minutes |
| Veyra service down | api, worker, deployer, pager or firewall not running (from the services' heartbeats) for 2 minutes |
| Disk space | Less than 10 % free on the data or log volume |
| Certificate | The HTTPS certificate expires within 21 days |
| Firewall | More than 20 bans in an hour (an attack under way) |
| Phones | More than 20 % of provisioned phones unregistered for 15 minutes |

Alerts appear on the dashboard and on System → Alerts (history, who was
told). Notification by **email** through the SMTP settings of M7 to a list
of addresses per rule; a repeat reminder every 24 hours while raised; one
message when cleared.

### 6.2 Metrics for outside tools

`GET /api/v1/metrics` in the Prometheus text format, for a bearer token
with `metrics.read` (platform administrators hold it too), for districts that
run Prometheus or Grafana: `veyra_up`, `veyra_engine_up`, `veyra_channels`,
`veyra_calls{direction}`, `veyra_registered_phones`, `veyra_trunk_up{trunk}`,
`veyra_alert{rule,subject}`, `veyra_alerts_raised`,
`veyra_firewall_bans_active`, `veyra_disk_free_ratio{volume}`.

## 7. Permissions and API

New permissions: `calls.history.read`, `calls.history.export`,
`recordings.read`, `recordings.read_own`, `recordings.manage`,
`recording_policies.read/write`, `reports.read`, `alerts.read`,
`alerts.write` (platform), `metrics.read` (token scope only).

```
GET  /calls/history?from=&to=&organization_id=&direction=&outcome=&q=&extension_id=&recorded=
GET  /calls/history/{id}                 (legs, recording, queue events)
GET  /calls/history/export.csv?…
GET  /me/calls
GET  /recordings/{id}/audio              (byte ranges; audited)
POST /recordings/{id}/hold | /release, DELETE /recordings/{id}
GET/POST/PATCH/DELETE /recording-policies[/{id}]
GET  /reports/calls?organization_id=&from=&to=&group=day|hour|weekday_hour
GET  /reports/extensions | /trunks | /queues | /ring-groups
GET  /alerts?state=, GET/PATCH /alert-rules[/{key}]
GET  /metrics                            (Prometheus, metrics.read token)
```

## 8. Interface

* **Telephony → Call History**: the search, a table (time, direction
  icon, from, to, answered by, ring and talk time, outcome, recording
  icon), a detail drawer (legs as a timeline, recording player, queue
  events), CSV export.
* **Telephony → Recording**: policies (what, announcement, retention),
  and the recordings list with player, hold and delete.
* **Telephony → Reports**: §5.1.
* **System → Alerts**: rules and history.
* **Account page**: "My calls"; **Companion**: "Recent calls".
* The two "coming later" items (Call History, Call Recording) become real
  pages.

## 9. Installer

* Managed `cdr.conf` (simple mode, `unanswered = yes`, the package's CSV
  settings kept) and `cdr_custom.conf` (the Veyra mapping), both reloaded
  without a restart; `modules.conf` is not touched (see §3.1).
* `<data>/recordings` and `<data>/recordings/incoming` (2770
  `veyra:asterisk`): Asterisk writes only into `incoming/`, whose
  permissions the installer controls; the worker creates the
  `<org>/<yyyy>/<mm>/` folders itself.
* `logrotate` for `veyra.csv` (`copytruncate` is not used: Asterisk
  reopens the file per record, so rename rotation is safe; the worker
  follows the inode).
* No NGINX change: metrics are served by the API at `/api/v1/metrics`.
* `verify.sh`: `cdr-custom` (the mapping is loaded: `cdr show status`
  lists `cdr_custom`), `recordings-dir`, `cdr-file` (readable by veyra).

## 10. Testing

Unit: the CSV line parser with real lines from dev1, folding legs
into calls (internal, inbound to a ring group with one answer, outbound,
transfer, voicemail, queue abandon), retention, search scoping per
organization, CSV export, the recording subroutine in generated dialplan,
policy matching, conversion, audit of playback, report queries on fixture
data, alert evaluation and clearing, the metrics text format. Live on dev1
with `tools/fakephone.py`: internal call, missed call, call to a ring group
and a queue, a recorded call, then the history, the recording player and
the reports. Owner: a real inbound and outbound call through a trunk.

## 11. Out of scope

Billing and rating, wallboards for queue agents (a later module), speech
analytics and transcription (discussed 2026-10-15 as a separate optional
module), SMS/Teams/Slack notifications
(email only), long-term metrics storage (Prometheus does that).

## 12. Open questions for the owner

1. **Recording**: does the district want any calls recorded at all? If
   so, which (front offices, specific lines, queues), and with which
   announcement?
2. **Retention**: how long to keep call history (default 400 days) and
   recordings (default 90 days)? Any records-retention rule we should
   follow?
3. **Who may listen** to recordings, and should staff see their own call
   history in their account and in the Companion?
4. **Alerts**: who should get them (addresses), and is anything missing
   from the list in §6.1?
5. Is **Prometheus or Grafana** used anywhere, or is the built-in
   dashboard enough?
6. Which **reports** matter most (missed calls by office, queue service
   level, trunk usage)?

## 13. Decisions

* 2026-10-15 (build): the backup rule waits for scheduled backups
  (M12/M17); queue reports come from `queue_log` read like the CDR file;
  alerts are evaluated on the worker's 30-second pass and emailed through
  the mail queue; recordings are Ogg Opus at 16 kbit/s (`libopus`).
* 2026-10-15: milestone started on the owner's "proceed" after 0.14.0;
  scope from roadmap row 10 and the two "coming later" pages. CDRs reach
  Veyra as a CSV file written by `cdr_custom` (no database password for
  Asterisk, survives database outages); no JSON encoder exists in
  Asterisk 22.
