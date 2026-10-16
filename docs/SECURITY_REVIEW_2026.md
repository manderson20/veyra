# Security Review 2026 (Milestone 17)

A review of the running system against [SECURITY.md](../SECURITY.md) and
[ARCHITECTURE.md §6](ARCHITECTURE.md), done on the Milestone 17 branch
(2026-10-16). Method: read every entry of the security model against the
code that implements it, walk the new attack surface of Milestones 11 to 16
(module catalog, updates, firewall, integrations, central management, HA),
and check the live system on dev1 (headers, cookies, exposure, journal).
Every finding is fixed in this milestone or recorded as an exception with
a date.

## 1. Findings fixed

| Area | Finding | Fix |
|---|---|---|
| Content Security Policy | `script-src 'unsafe-inline'` because the static export inlines Next.js bootstrap scripts | The build writes the SHA-256 of every inline script to `frontend/out/csp-hashes.txt`; the installer renders them into `script-src 'self' 'sha256-…'`; `'unsafe-inline'` only when the file is missing; `verify.sh` `csp-hashes` |
| Headers | No `Permissions-Policy`, no `Cross-Origin-Opener-Policy` | Both added in NGINX and the API |
| Session cookie | No `__Host-` prefix | `__Host-veyra_session` (HTTPS only, this host only, no Domain) |
| Sign-in brute force | Rate limit per address only | Also per account (same limit), so a distributed guess at one account is slowed |
| Asterisk from `universe` | No check that `esm-apps` covers it | `preflight.sh` and `verify.sh` warn when Ubuntu Pro `esm-apps` is not attached |
| HA agent (root) | No capability bound | `CapabilityBoundingSet` limited to what `ip`, `arping`, `runuser`, `pg_ctlcluster`, `chown` and `systemctl` need |
| Secrets in logs | Not tested | `tests/test_secrets_in_logs.py`: a generated SIP secret never appears in the log output or in audit details |
| Dependencies | Audits only on push | Weekly scheduled `pip-audit` and `npm audit` run in CI; findings triaged within a week |
| Installation key | No rotation | `sudo veyra installation-key rotate` (§3.1 of PRODUCTION_HARDENING.md) |

## 2. New surface reviewed

* **Peer channel (HA):** Ed25519-signed requests and answers, timestamps
  within five minutes, single-use nonces (database, or memory when the
  database is stopped), the caller resolved from the node row or
  `node.json`, `run` limited to a fixed list of verbs, rate limited. The
  join request is the one unverified-TLS call: the new node has no CA yet,
  and the bundle is AES-256-GCM under a key derived from the single-use
  token (24 h); the token travels only in the operator's command.
* **Backups:** root runner, store 0700, parts 0600; `age` to recipients the
  administrator holds; copies and buckets refuse to run unencrypted; the
  restore refuses newer dumps and HA roles; the runner never reads
  database credentials (peer authentication).
* **Updates and modules:** unchanged from their reviews (signed metadata
  with expiry; Ed25519 module signatures; polkit limited to Veyra's units).
* **Emergency calling:** notifications carry locations and extension
  numbers to configured recipients only; webhooks keep their HMAC secret;
  the callback uses Asterisk's own database, no network input.

## 3. Exceptions (dated)

| Item | Why | Review by |
|---|---|---|
| `style-src 'unsafe-inline'` | The interface still sets a few inline styles; hashing styles is not worth it until they are gone | 2027-04 |
| HSTS off | A self-signed site would lock the browser out; on with a public certificate (M18 packaging) | M18 |
| Rate limiter per process | One API process per node; the HA standby answers only reads | — |
| `ProtectSystem=strict` on the HA agent | The agent writes to `/etc`, `/var/lib/postgresql` and `/run`; a full sandbox must be tested in stage 2 of the HA plan | M16 stage 2 |
| The ARI password is 0640 root:veyra | The API reads it; a socket-authenticated ARI does not exist | — |

## 4. Live checks on dev1

To be run after the 0.23.0 upgrade (recorded in the Milestone 17 report):
response headers, the CSP in a browser (the interface must load without
console violations), `Set-Cookie` attributes, `verify.sh` exposure checks,
and a journal search for every generated secret of a test session.
