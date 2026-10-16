# Milestone 17 Report — Production Hardening

Branch `milestone-17` (from `main` at 0.22.0). Design:
[PRODUCTION_HARDENING.md](../PRODUCTION_HARDENING.md). Status: **built and
live-checked on dev1 (2026-10-16), awaiting approval → 0.23.0.**

## 1. Scope (roadmap row 17)

Backups, encryption, retention, a security review with its fixes, and
emergency calling validation.

## 2. Results

* **Backups** (§2): a root runner takes the database dump, `/etc/veyra`,
  `/etc/asterisk`, the data directories, voicemail and optionally
  recordings; restores the dump into a scratch database and compares
  schema, row counts and checksums before the backup counts; encrypts to
  the administrator's `age` recipients (Veyra holds no private key); copies
  to a mounted directory; prunes by a daily/weekly/pre-upgrade keep policy.
  Scheduled by the worker through a polkit-started unit, or *Back up now*,
  or `sudo veyra backup run`. `sudo veyra backup restore` brings a server
  back (refuses newer dumps and HA roles, runs migrations, restarts).
  System → Backups, a dashboard tile, alert rules `backup_failed` and
  `backup_stale`, `verify.sh` `backup-unit` and `backup-last`; migration 0030.
* **Installation key rotation** (§3.1): a registry of every ciphertext
  purpose (16 kinds across columns, JSON documents and settings),
  re-encryption in one transaction, `sudo veyra installation-key rotate`
  (the wrapper generates and installs the key, keeps the previous one and
  restarts the services), `installation-key check --ciphertexts` in
  `verify.sh`. A test fails when a new encrypted column is not in the registry.
* **Retention** (§4): ten data classes with defaults and minimums (the
  audit log never below a year, under 30 days needs a typed confirmation),
  one daily job with an audit entry per class that lost rows (the audit
  log's own pruning goes through the append-only trigger's gate), an
  inventory of rows, bytes and the oldest record plus recordings, backups,
  sessions and the voicemail spool; Settings → Retention. The worker's old
  fixed-day pruning now goes through the job.
* **Security review** (§5, [SECURITY_REVIEW_2026.md](../SECURITY_REVIEW_2026.md)):
  scripts allowed by hash in the CSP (the build writes `csp-hashes.txt`,
  the installer renders it, `'unsafe-inline'` only as the fallback),
  `Permissions-Policy` and `Cross-Origin-Opener-Policy`, the `__Host-`
  session cookie, sign-in limits per account, Ubuntu Pro `esm-apps` checks,
  a capability bound on the HA agent, a weekly dependency audit, a test that
  generated secrets never reach logs or audit details; five dated exceptions.
* **Emergency calling validation** (§6): locations on extensions and
  devices, site-bound emergency routes chaining to the installation-wide
  one, `UserEvent(VeyraEmergency)` from every emergency call turned into an
  `emergency_calls` record and the site's on-site notification (email, a
  recorded page, responder phones that hear the extension, an
  `emergency.call` webhook), the PSAP callback to the ELIN through
  Asterisk's own database (window per site, then the responder), carrier
  test call records, readiness per site with the address attestation,
  System → Emergency calling, a dashboard tile; migration 0031. Veyra
  reports readiness against its own checks only.

Not built (PRODUCTION_HARDENING.md §14): the S3 destination (owner
question 1), secure SIP (question 4), a Buildings API, the Companion
pop-up, voicemail pruning.

## 3. Testing (final tree, 2026-10-16)

| Suite | Result |
|---|---|
| Backend `pytest` | 472 passed, 1 skipped (`age` not installed on the development host); new: `test_backups.py` 9 (keep policy, schedule, the runner against a fake system incl. a failed restore test and pruning, age round trip when `age` is installed, restore checks, settings, rows, summary, tick, API, alerts), `test_rotation.py` 2, `test_retention.py` 3, `test_emergency.py` 4 (generator site routes, event and callback; event detection; service record/notify/readiness; API), `test_secrets_in_logs.py` 1 |
| Frontend `vitest`, `tsc`, `eslint`, `next build` | 51 passed, clean; the build writes 66 script hashes |
| Installer `test_lib.sh` | 68 passed (backup unit, polkit instances, security headers file, every location re-includes it) |
| `upgrade.sh --dry-run` on dev1 | OK (esm-apps attached) |

### Live checks on dev1 (2026-10-16, releases 7bfe514 → e7df5a5)

The owner upgraded dev1 twice (the second time after the fixes below).
Every check passed on the final tree:

| Check | Result |
|---|---|
| `upgrade.sh` + `verify.sh` | clean; `csp-hashes` pass, `installation-key-ciphertexts` 66 readable, `backup-unit` pass |
| Headers | every response (page, API, `/_next/static/`, downloads) carries HSTS, CSP, `Permissions-Policy`, COOP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, each exactly once; the three inline scripts of `/` hash to entries of the served CSP |
| Backup, plain | `sudo veyra backup run` and the page's unit (`veyra-backup@run-manual`): verified in 5 s (restore test, schema, counts, checksums) |
| Backup, encrypted + copy | recipients set to a test `age` identity, copy directory `/srv/…`: `.tar.age` in the store, copy `ok`, decrypts with the identity. A copy directory under `/tmp` is reported as "not a directory" (the unit has `PrivateTmp`) |
| Restore on a new server | fresh LXD container (Ubuntu 26.04, `install.sh`), the dev1 backup restored from the directory and again from the `.tar.age` with `--identity`: same installation key fingerprint, 66 ciphertexts readable, `verify.sh` clean, 1 user / 2 extensions / 36 revisions as on dev1 |
| Key rotation | `sudo veyra installation-key rotate`: 66 rotated, `b18fd7d3…` → `f1234c3a…`, check clean, services restarted, a backup verified afterwards |
| Retention | inventory read (10 classes), applied: nothing older than the limits |
| Emergency | a site with address and ELIN, attested, callback 30 min: readiness shows the missing route; the notification test records a test call and queues the webhook |
| Browser | the CSP by hash is still to be seen by a real browser (owner) |

Defects found by the live checks, all fixed on `milestone-17`:

1. **Installer** (7bfe514): the CSP hash list was passed to the success
   message instead of `render_template`; every install and upgrade died on
   `@CSP_SCRIPT_SRC@`.
2. **Wrapper** (e7df5a5): `sudo veyra installation-key rotate --help`
   installed a new key without re-encrypting (the inner command answered
   the help and exited 0). dev1's secrets were unreadable until the owner
   copied `installation.key.previous` back. The wrapper now accepts only
   `--force`, answers help itself and installs the key only on a reported
   `{"rotated": n}`.
3. **Backups** (e7df5a5, 2a14a7e, 5981d86, e28e601): the restore test ran
   `pg_restore` as `postgres` on a root-only file (first scheduled backup
   failed); `sudo veyra backup run|restore` ran as the service account;
   the worker's pending row was never matched by the runner's report and
   stayed "running"; restored tables belonged to `postgres`
   (`--role veyra` now); a partial `PUT /backups/settings` dropped the
   recipients; the delete unit opened the database as root.
4. **NGINX** (722ff67, e7df5a5): a pre-M17 `Permissions-Policy` line was
   sent next to the new one; locations with their own `add_header`
   (firmware, downloads, `/_next/static/`) had lost HSTS and the CSP; the
   API's copies of the same headers were sent twice on proxied responses.
   The headers now live in `/etc/veyra/nginx-security-headers.conf`.
5. **verify.sh** (52c1852): the ciphertext check printed an empty message.

## 4. Not verified

The CSP by hash in a real browser; `pg_rewind` (carried over from Milestone 16);
Proxmox fencing; a real S3 bucket; real emergency calls with a carrier.

## 5. Known limitations

* Backups are only as safe as the age identity the administrator keeps;
  an unencrypted local store is root-only but on the same disk.
* Retention of voicemail messages stays Asterisk's `maxmsg`.
* The CSP hash list is per build: an interface served from a different
  build than the installed hashes shows a blank page (the installer always
  renders the installed build's hashes).
* Emergency calling readiness is a checklist, not a certification.

## 6. Open items

The six owner questions of PRODUCTION_HARDENING.md §12.

## 7. Next milestone

Milestone 18, public release preparation, or 17b (secure SIP) if chosen;
Milestone 16 stage 2 when veyra-dev2 exists.

## 8. Owner decisions

* 2026-10-16: "Go ahead with M17, design doc first."
