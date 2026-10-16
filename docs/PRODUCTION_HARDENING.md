# Production Hardening (Milestone 17)

Design for Milestone 17 (roadmap row 17, 0.23.0): what has to be true before
a Veyra installation carries a district's telephones for years. Five areas:
**backups** (ARCHITECTURE.md §14 built), **encryption** (the known gaps of
SECURITY.md plus secure SIP), **retention** (one audited job for every data
class), a **security review** with its fixes, and **emergency calling
validation** (the open items of [EMERGENCY_CALLING.md](EMERGENCY_CALLING.md)).
Milestone 18 (public release) follows and does not repeat this work.

## 1. Principles

1. **Recoverable by a stranger.** A backup plus the installer must bring a
   fresh server back to the same state with a written procedure, tested here.
2. **Nothing secret in the clear at rest once it leaves the server.** A
   backup that leaves `/var/backups/veyra` is encrypted to a key the
   administrator holds; Veyra keeps no copy of that key.
3. **Every data class has an owner, a default and a job.** Retention is
   data (settings), applied by one audited job, visible on one page.
4. **Fix what the review finds, do not list it.** The review's open items
   become work in this milestone or an explicit, dated exception.
5. **Emergency calling is validated per site, by the operator, with the
   carrier.** Veyra computes readiness from the data and records the test
   calls; it never declares a site compliant by itself.
6. **Same build, HA-aware.** Backups and retention run on the primary; a
   standby does nothing but replicate.

## 2. Backups

### 2.1 What a backup holds

| Part | Source | Form |
|---|---|---|
| Database | `pg_dump -Fc veyra` as `postgres` | `db.dump` |
| Configuration and secrets | `/etc/veyra` (secrets, TLS incl. the CA key, trust keys, `veyra.env`, install state) | `etc.tar` |
| Generated engine configuration | `/etc/asterisk/veyra` and the Veyra-managed stubs | `engine.tar` |
| Data | `<data>/prompts`, `moh`, `firmware`, `provisioning/templates`, `modules`, `module-store` | `data.tar` |
| Voicemail | `/var/spool/asterisk/voicemail` | `voicemail.tar` |
| Call recordings | `<data>/recordings` | `recordings.tar`, only when the switch is on (large) |
| Manifest | versions, schema revision, host name, sizes, SHA-256 of every part, the installation's `instance_id`, HA role | `manifest.json` |

One backup is one directory `veyra-<YYYYMMDD-HHMMSS>` under the local
store, or one file `veyra-<stamp>.tar.age` when encryption is on (§3.2).
The database dump is what `upgrade.sh` already takes; the installer's
pre-upgrade backup becomes a backup like any other (kind `upgrade`).

### 2.2 Who runs it

A root unit `veyra-backup.service` (`veyra backup run`), started by the
worker through polkit (the pattern of `veyra-upgrade@`, UPDATE_MANAGEMENT.md
§3.2) at the scheduled time, by *Back up now* on the page, or by
`sudo veyra backup run` from the console. Root because the CA key, the
secrets and the voicemail spool are root- or asterisk-owned. Status in
`/var/lib/veyra-backup/status.json` (root-owned, readable by the `veyra`
group), history in `backups` (§8). On an HA standby the worker does not
start it; a running primary does.

### 2.3 Verification

Every backup is **verified before it is reported good**: the dump is
restored into a scratch database `veyra_restore_test` (dropped afterwards),
the schema revision is compared with the running one, the row counts of
the core tables are compared with the manifest, every tarball is listed,
and the SHA-256 of each part is recomputed. A backup that fails
verification is kept, marked `failed`, and raises the alert.

### 2.4 Retention and destinations

`backup.keep`: daily backups kept for N days (default 14), one per week
for M weeks (default 8), pre-upgrade backups kept for the last K releases
(default 3). Pruning runs after a successful backup; nothing is pruned
after a failed one.

Destinations: the local store (`/var/backups/veyra`, root 0700) always;
optionally a **copy directory** (`backup.copy_dir`, a path the operator
mounts, such as a NAS share over NFS or CIFS, written with the same
retention) and an **S3-compatible bucket** (`backup.s3`: endpoint, bucket,
prefix, access key, secret encrypted with the installation key, region;
SigV4 over `httpx`, no SDK; multipart for parts over 100 MB; lifecycle rules
stay the bucket's). A copy that fails does not fail the backup; it raises
the alert and is retried at the next run. Pulling backups from the server
over SSH remains the operator's option and needs nothing from Veyra.

### 2.5 Restore

`sudo veyra backup restore <file-or-directory> [--parts db,etc,…] [--yes]`
on a server where the same release is installed (a fresh `install.sh` is
fine): checks the manifest's version against the running one (same minor
or older; a newer dump is refused), decrypts with the administrator's
identity file (§3.2), stops the services, restores the database with
`pg_restore --clean --if-exists`, the configuration, the engine files, the
data, the voicemail and optionally the recordings, runs migrations when
the dump is older, restarts and verifies. The instance identity, keys and
certificates come back with `/etc/veyra`, so phones keep trusting the
server and a central console keeps recognising it. The procedure is
written in INSTALLATION.md and tested in §11. Restoring onto an HA node is
refused; an HA pair is rebuilt from a restored standalone.

### 2.6 Interface and alerts

System → **Backups**: schedule (time of day, keep policy, recordings
switch), encryption (§3.2), destinations, *Back up now*, the list of
backups (when, kind, size, parts, verified, encrypted, copies), *Verify
again*, *Delete*, and the restore procedure. Dashboard: last good backup.
Alert rules (`ensure_rules`): `backup_failed` and `backup_stale` (no good
backup for 2 days, the rule REPORTING.md deferred). Central management:
a `backups` policy section (schedule and keep policy) in a later milestone.

## 3. Encryption

### 3.1 Installation key rotation

`sudo veyra installation-key rotate` (console only: the key file is
root's, and a rotation is rare enough not to need a page; the Settings
page shows the fingerprint, the rotation date and the command): a new key
is generated, every ciphertext
bound to the old key is re-encrypted in one transaction (SIP secrets,
revision artifacts, MFA secrets, organization provisioning secrets, module
configuration, SMTP password, SSO client secret, webhook secrets, firewall
feed credentials, the central private key, the update source token, the
fencing token; the registry of purposes lives in one place so a new
purpose cannot be forgotten), the old key file is kept as
`installation.key.previous` (0600) until the next rotation, the new key is
written, the services restart. An HA pair rotates on the primary; the
standby receives the new key through the file sync (the ciphertexts come
through replication). Audited; `verify.sh` checks that every ciphertext
decrypts with the current key (`installation-key check` already exists).

### 3.2 Backup encryption

Backups are encrypted with **age** (X25519, the `age` package) to one or
more **recipients** the administrator enters on the Backups page (an age
public key `age1…`, or an SSH public key, which age also accepts). Veyra
never holds a private key for them. The page shows how to create an
identity (`age-keygen`) and where to keep it (not on this server). The
local store may keep backups in the clear when no recipient is set, root
0600; a copy destination or a bucket **requires** a recipient. Decryption
at restore uses the administrator's identity file.

### 3.3 Secure SIP (TLS and SRTP)

Phones talk SIP over TLS and media over SRTP when their device profile says
so: a `transport-tls` on 5061 with the server certificate issued by the
Veyra CA (phones already install the CA through the provisioning
bootstrap, DEVICE_PROVISIONING.md §6), `media_encryption=sdes` with
`media_encryption_optimistic` per endpoint; the provisioning templates for
the supported families get `sip_transport` and `srtp` facts. The firewall
opens 5061 like 5060. Trunks are unchanged (a carrier's TLS trunk is a
trunk setting that exists). This is the largest item of the milestone; if
time is short it becomes 17b (§12 question 4).

### 3.4 Smaller items

* `/etc/veyra/secrets` entries are reviewed for mode and owner; the ARI
  password moves to 0600 root:veyra only if NGINX/Asterisk needs are
  unchanged (today 0640 is required by the API; stays, documented).
* The database stays on peer authentication; `ssl` on the local socket is
  moot. The HA replication connection is TLS already.

## 4. Retention

One settings document `retention` (System → Settings → **Retention**) with
a row per data class, its default, its unit and who may change it; one
daily job in the worker applies it and writes one audit entry per class
with the count removed. Today's constants become these settings:

| Class | Default | Today |
|---|---|---|
| Audit log | 730 days, platform administrators only; the append-only trigger stays, the job sets `veyra.audit_retention = 'on'` for its transaction | never pruned |
| Call history (calls, legs, queue events) | 400 days | `calls.retention_days` |
| Call recordings | per recording policy (90 days default), legal hold exempt | as today |
| Voicemail messages | off by default; optional N days per organization (Asterisk `maxmsg` stays the size cap) | `maxmsg` only |
| Alerts history | 365 days | never pruned |
| Update history, cluster events | 730 days | never pruned |
| Firewall events and expired bans | 90 days | rolling |
| Provisioning request log | 30 days | 30 |
| Page log, bell rings | 90 days | 90 |
| Engine metrics samples | 14 days | 14 |
| Central samples | 30 days | 30 |
| Sessions and reset tokens after expiry | 30 days | 30 |
| Backups | §2.4 | — |

A **data inventory** on the same page shows rows and bytes per class and
the oldest record, so a retention change is made with the numbers in
view. Shortening a class below 30 days needs a typed confirmation; the
audit log cannot go below 365 days.

## 5. Security review

A written review of the running system against SECURITY.md and
ARCHITECTURE.md §6, with every finding either fixed in this milestone or
recorded as an exception with a date. The known items that become work:

* **CSP without `'unsafe-inline'` for scripts:** the frontend build writes
  the SHA-256 of every inline script Next.js emits into
  `frontend/out/csp-hashes.txt`; the installer renders them into the
  NGINX header. Styles keep `'unsafe-inline'` until the UI's inline styles
  are gone (an exception).
* **Asterisk from `universe`:** `preflight.sh` and `verify.sh` check that
  Ubuntu Pro `esm-apps` is attached and warn when it is not; INSTALLATION.md
  says why.
* **The HA agent's unit** (root) gets the sandboxing the other units have
  where it still works (`ProtectSystem=strict` with the paths it writes,
  `CapabilityBoundingSet` to what `ip`, `arping`, `pg_ctlcluster` and
  `systemctl` need), reviewed against the live test.
* **Rate limiting per process** is accepted (one API process per node);
  the login limiter also counts per account.
* **Session cookie** gets the `__Host-` prefix; `Permissions-Policy` and
  `Cross-Origin-Opener-Policy` headers are added; HSTS stays off until a
  public certificate is in use (it would lock out a self-signed site).
* **Dependency and image hygiene:** `pip-audit` and `npm audit` already run
  in CI; the review adds a scheduled run and a documented response time.
* **Secrets in logs and audit details** are re-checked with a test that
  greps the journal of a full test run for every generated secret.
* **The peer channel and the join bundle** (HIGH_AVAILABILITY.md) are
  reviewed as new attack surface: token entropy and single use, bundle
  authentication, nonce windows, what `run` accepts.

The review itself (method, scope, findings, exceptions) is
`docs/SECURITY_REVIEW_2026.md`, and SECURITY.md's gap list is rewritten
from it.

## 6. Emergency calling validation

The open items of EMERGENCY_CALLING.md, built so that a site can be
validated step by step:

* **Dispatchable location:** `buildings` get a civic address (street,
  city, region, postal code, country; inherited from the site when empty);
  `extensions` and `devices` get `location` (floor, room, "near the main
  entrance") and a building. The location of a call is the device's, else
  the extension's, else the site's address.
* **Per-site emergency routing:** an emergency route may be bound to a
  site (NULL = every site); the generator evaluates the caller's site's
  route first and the installation-wide one second, with the site's
  emergency caller ID (ELIN or registered DID), then the extension's own
  when it has one (today's rule). A site without a reachable emergency
  route is *not ready*.
* **On-site notification (Kari's Law):** the emergency route's dialplan
  raises `UserEvent(VeyraEmergency)` with extension, name, location and the
  number dialled; the API's event listener turns it into
  `emergency.call` on the call event bus and the notification recipients
  of the site are told at once: email (the mail queue), a page to a paging
  zone or Poly group (the pager), a desk phone ring through a notification
  extension, an outgoing webhook (INTEGRATIONS.md), and the Companion
  pop-up for signed-in responders. Delivery is recorded per recipient.
* **Callback:** `emergency_calls` records every call (site, extension,
  device, location, number, trunk, time); an inbound call to a site's ELIN
  within the callback window (default 30 minutes, per site) rings the
  extension that placed the last emergency call, else the site's responder
  destination; the inbound route for the ELIN is generated, not typed.
* **Test calls:** *Record a test call* on the site's readiness page (933
  where the carrier offers it, or a coordinated 911 test) with date,
  result and the location the PSAP read back; the last test's age counts
  toward readiness (default: within 365 days).
* **Readiness** per site, computed: an enabled emergency route reaches the
  site; the site has an ELIN or DID and a civic address the administrator
  has **attested** (a checkbox with name and date: "this address is
  registered with the carrier's E911 service"); every fixed extension of
  the site has a location; notification recipients are set and the last
  notification test succeeded; the last test call is within the window.
  System → **Emergency calling** lists sites with what is missing; the
  dashboard tile says "N of M sites ready"; `verify.sh` warns when any
  site with extensions is not ready. The disclaimer stays: Veyra reports
  readiness against these checks, the operator validates with the carrier
  and the regulations that apply.

## 7. API

| Route | Who | What |
|---|---|---|
| `/backups` (GET list), `POST /backups/run`, `GET /backups/{id}`, `POST /backups/{id}/verify`, `DELETE /backups/{id}`, `GET /backups/settings`, `PUT /backups/settings`, `GET /backups/status` | `backups.read` / `backups.manage` (platform) | §2 |
| `POST /system/installation-key/rotate` | `system.settings.write`, platform | §3.1 |
| `GET /retention`, `PUT /retention`, `GET /retention/inventory`, `POST /retention/run` | `system.settings.read/write`, platform | §4 |
| `GET /emergency/sites`, `GET /emergency/sites/{id}`, `PUT /emergency/sites/{id}` (ELIN, attestation, responder, callback window, recipients), `POST /emergency/sites/{id}/test-call`, `POST /emergency/sites/{id}/test-notification`, `GET /emergency/calls` | `emergency.read` (org admins) / `emergency.manage` | §6 |
| `/buildings`, `/extensions`, `/devices` | existing | + address and location fields |
| `/routing/outbound` | existing | + `site_id` on emergency routes |

## 8. Data (migrations 0030–0033)

* `backups`: id, kind (`scheduled`, `manual`, `upgrade`), started_at,
  finished_at, state (`running`, `verified`, `failed`, `deleted`), path,
  encrypted, recipients (fingerprints), parts (JSONB: name, bytes, sha256),
  copies (JSONB per destination: state, at, error), verify (JSONB),
  error, created_by. `system_settings`: `backup.schedule`, `backup.keep`,
  `backup.encryption`, `backup.copy_dir`, `backup.s3` (secret encrypted).
* `system_settings`: `retention` (§4); `installation.key_rotated_at`.
* `buildings`: + street, city, region, postal_code, country;
  `extensions`: + building_id, location; `devices`: + building_id, location.
* `outbound_routes`: + site_id (nullable). `sites`: + emergency_attested_by,
  emergency_attested_at, emergency_responder (destination), callback_minutes,
  emergency_recipients (JSONB), last_emergency_test_at, last_emergency_test_result.
* `emergency_calls`: id, occurred_at, organization_id, site_id, extension_id,
  device_id, number, location (text snapshot), trunk, call_id, notifications
  (JSONB per recipient), callback_until.
* `device_profiles`: + sip_transport (`udp`, `tcp`, `tls`), srtp (bool) (§3.3).

## 9. Interface

System → Backups (§2.6); Settings → Security → *Rotate the installation
key*; Settings → Retention with the inventory (§4); System → Emergency
calling (sites, readiness, test calls, recent emergency calls); dashboard
tiles for the last good backup and emergency readiness; Buildings, Sites,
Extensions and Devices get the address and location fields; the Outbound
Routes page gets the site binding on emergency routes; Device profiles get
the transport and SRTP switches.

## 10. Installer and operations

`age` and `ubuntu-pro-client` checks; `veyra-backup.service` and its
polkit rule; `/var/lib/veyra-backup`; `verify.sh` adds `backup-last`,
`csp-hashes`, `esm-apps`, `emergency-readiness`; `upgrade.sh` records its
pre-upgrade backup in `backups`; INSTALLATION.md gets *Backups and
restore* and *Emergency calling* sections; a `docs/RUNBOOK.md` with the
restore, key rotation, failover (from HIGH_AVAILABILITY.md) and emergency
test procedures in operator form.

## 11. Testing

* Unit: manifest and pruning policy, age encryption round trip (with a
  test identity), the restore test's comparisons, the purpose registry and
  rotation (every purpose re-encrypts, the old key decrypts nothing after),
  the retention job per class with the audit trigger, readiness computation
  per site, the callback window, CSP hash extraction.
* API: backups settings and run (runner mocked), restore refusal rules,
  rotation endpoint, retention settings and inventory, emergency site
  settings, test calls, the `emergency.call` event to each recipient kind
  (mail queue, pager, webhook, Companion stream).
* Installer: `test_lib.sh` for the unit, the CSP rendering and the new
  verify checks.
* Live on dev1: a scheduled backup, encrypted, copied to a directory,
  verified; **a restore into the LXD container from that backup** (fresh
  install, restore, verify, the container answers as a copy of dev1,
  then the container is wiped); key rotation on dev1 with every secret
  checked before and after; the retention job with the inventory before
  and after; an emergency route bound to a site with a test number,
  notification to email and a page, the callback window with
  `tools/fakephone.py`; the security review's checks against the live
  system (headers, CSP, cookies, exposure, journal grep).

## 12. Open questions for the owner

1. **Backup destination:** a NAS share mounted on the server (copy
   directory), an S3-compatible bucket (which provider?), both, or local
   only with pulls over SSH?
2. **Backup encryption:** who holds the age identity, and should there be
   two recipients (the district's IT lead and an escrow)?
3. **Retention defaults** in §4, especially the audit log (730 days) and
   voicemail (off).
4. **Secure SIP in this milestone** (§3.3) or as 17b after the rest ships?
5. **Emergency calling:** the sites' ELINs/DIDs and whether the carrier
   offers 933 test calls; the on-site notification recipients per site
   (front office phone, email, a paging zone).
6. **Ubuntu Pro:** dev1 has `esm-apps` attached; will the production hosts?

## 13. Out of scope

Off-site replication of the database (that is HA), backup to tape or
Windows shares by Veyra itself (mount them), WebAuthn and SSO (own
milestones), a vulnerability disclosure programme and release signing
infrastructure (M18), E911 location services beyond the carrier's
registration (NG911 PIDF-LO), mass notification.

## 14. Implementation notes (build, 2026-10-16)

Where the build departs from the sections above:

* **Backups:** the S3 destination (§2.4) waits for the owner's answer to
  question 1; local store and copy directory are built. Pre-upgrade backups
  stay `upgrade.sh`'s own dump and tarball (recorded in the update history,
  not in `backups`), because the runner is part of the release being
  replaced. Backups and deletions run as `veyra-backup@run|run-manual|delete-<id>`.
* **Key rotation** is console-only (`sudo veyra installation-key rotate`,
  the wrapper does the root part); the Settings page item of §3.1 is not
  built. Every ciphertext purpose is listed in
  `veyra/core/security/rotation.py`, and a test fails when an encrypted
  column is missing from it.
* **Retention:** voicemail messages are not pruned by Veyra (Asterisk owns
  the spool, 0750 `asterisk`); the inventory shows the spool's size. The
  Milestone 10 `calls.retention_days` setting is kept in step with the
  retention document's `calls` row.
* **Emergency calling:** no Buildings API yet (the address and location
  columns exist; addresses are entered on the site, locations on the
  extension and the phone); no Companion pop-up; the responder's phone
  hears the extension number read out (`veyra-emergency-notify`) rather
  than a prompt; the ELIN callback uses Asterisk's own database
  (`DB(veyra_ecb/<elin>)`), written by the emergency route itself, so it
  works with the API down.
* **Security review:** `ProtectSystem=strict` for the HA agent is an
  exception until stage 2 of the HA plan; the rest of §5 is built.
* **Secure SIP (§3.3)** is not built in this milestone (question 4).

