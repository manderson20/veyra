# Milestone 17 Report — Production Hardening

Branch `milestone-17` (from `main` at 0.22.0). Design:
[PRODUCTION_HARDENING.md](../PRODUCTION_HARDENING.md). Status: **built,
awaiting the live checks on dev1 and approval → 0.23.0.**

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
| Installer `test_lib.sh` | 65 passed (backup unit, polkit instances, CSP rendering, Permissions-Policy) |
| `upgrade.sh --dry-run` on dev1 | OK (esm-apps attached) |

### Live checks on dev1

Pending the owner's upgrade from `~/veyra`: a backup (verified, then
encrypted to a test identity, copied to a directory), a restore of it into
a fresh LXD container, key rotation with `--ciphertexts` before and after,
retention applied with the inventory before and after, an emergency
notification test for a site with an ELIN, the CSP and headers in a
browser, `verify.sh`.

## 4. Not verified

The live checks above; `pg_rewind` (carried over from Milestone 16);
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
