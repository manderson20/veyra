# Milestone 15 Report — Centralized Instance Management

Branch `milestone-15` (from `milestone-14` at 0.20.0). Design:
[CENTRAL_MANAGEMENT.md](../CENTRAL_MANAGEMENT.md). Status: **approved 2026-10-15, released as 0.21.0.**

## 1. Scope (roadmap row 15)

A central console (any Veyra installation) that other installations enroll
with; signed check-ins every minute from the instance, so the console never
connects in; health, counts, alerts and update state per instance; policies
the local administrator may accept or refuse; a fixed list of commands.

## 2. Results

* **Protocol** (`central/protocol.py`): Ed25519 keys on both sides (the
  installation key signs nothing itself; each side has its own central key
  pair). Every request and answer is signed over the body, a timestamp and
  a nonce; the console refuses old timestamps and replayed nonces, and rate
  limits the two unauthenticated endpoints. The instance pins the console's
  fingerprint at enrollment and may carry the console's CA certificate for
  a self-signed console.
* **Enrollment** (`/central/enroll`): one-time tokens (shown once, a day's
  validity, optional policy; otherwise the default policy). The instance
  sends its public key and identity; the console answers with its name and
  key.
* **Check-in** (`/central/check-in`, the worker every 60 seconds, or
  "Check in now"): the report carries identity, version, health, telephony
  counts, open alerts, modules, update state, the accepted sections and the
  applied policy version. The answer carries the policy when it changed,
  pending commands, the next interval, or "revoked".
* **Policies** (`central/policy.py`, migration `0028`): four sections,
  `updates` (policy, window, optional source and recipients),
  `firewall_allow` (rows tagged `central`), `alert_recipients`, `notice`.
  The instance applies what it accepts per section and reports `applied`,
  `unchanged`, `refused`, `not set` or `error: …`. Refusing `firewall_allow`
  or `notice` withdraws what the console put there; leaving removes both.
  Recipients and the update policy stay as the instance's own values.
* **Commands** (`central/console.py`): `check_updates`, `download_update`,
  `approve_update`, `refresh_catalogs`, for one instance or several; they
  wait for the next check-in, run through the instance's own update rules,
  expire after a day, and report an outcome and message.
* **Console** (`/system/central/`): instances with status, version, update,
  phones, calls and alerts; an instance page with the last report, 30-day
  samples, open alerts, modules and the command history; policies and
  tokens; label, revoke, then remove. Alert rules `instance_offline`
  (threshold `offline_minutes`, 10 by default) and `instance_failed`.
  Permissions `central.read`/`central.write`.
* **Instance** (`/system/membership/`): enroll, check in now, leave; a
  switch per section and for commands; the applied policy and the log.
  The console's notice is a banner on every page (`CentralNotice` in the
  shell); the Updates page says when the console manages the update policy.
* **Documentation:** API, DATABASE_SCHEMA (`0028`), ARCHITECTURE mode D,
  INSTALLATION "Central management", CHANGELOG 0.21.0 (unreleased).

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (188 files) |
| Backend pytest | **415 passed**. `tests/test_central.py` (6): signatures, replay and clock skew refused; policy validation; enroll with a bad token, a used token, a wrong fingerprint, success; check-in, report stored, all four sections applied, a section refused and withdrawn; commands delivered once with results; revoke and leave; the console offline (settings kept, `instance_offline` raised); permissions and bulk commands |
| `alembic check` | No drift (migration `0028`) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **48 passed** / passed |
| **Owner's `upgrade.sh` on dev1** | 0.20.0-80aec092b7 → **0.20.0-1b62de19a6** (19:42 UTC: schema `0028`, all verify checks OK; `catalog-trust` warns as before) |

### Live checks on dev1 (19:44–19:50 UTC)

dev1 is both the console and its own instance. The API was driven in
process as the service account with a platform administrator principal;
the instance's HTTP client was pointed at `http://127.0.0.1:8100` so the
console's self-issued certificate did not get in the way.

| Step | Result |
|---|---|
| Console on (`offline_minutes` 5 for the test) | Fingerprint `cdfd-0fe7-…`, address `https://veyra-dev1` |
| Policy with a notice; token bound to it; enroll | Enrolled as instance `bf7f…`, console "District Phone System", audit rows written |
| Check in now | Policy applied: `notice: applied`, the others `not set`. `/central/notice` returned the text; the console listed the instance as `ok`, version 0.20.0, 2 extensions, policy `pending` until the next report |
| Check-ins by the worker | On its own 63 s after enrollment and every minute after (the report's `policy_state` turned `applied`) |
| `check_updates` command | Queued 19:44:51, delivered in the same second by a forced check-in, outcome at the worker's next check-in: **failed, "No update source is configured"** — correct for dev1, which has none; shown in the console's command history and the instance's log |
| Revoke | The instance's next check-in recorded "Revoked by the central console."; membership shows revoked |
| Leave | Membership empty, notice cleared |
| Second pass, default policy with notice + `firewall_allow` 10.227.92.0/24 + `alert_recipients`, token without a policy | Default policy applied: one `central` firewall row, recipients set on all nine alert rules |
| Switch `firewall_allow` off, check in | `firewall_allow: refused`, the row removed, the other sections `unchanged`; the console shows `partly refused` |
| Leave | Notice cleared, no `central` firewall rows left. Recipients stay (by design) and were put back to empty by hand |
| Remove the instance | `409 not_revoked` while it was only gone; `204` after revoking. Tokens, policies removed; console off, threshold back to 10; no central alerts, no rows left |

**Bug found and fixed** (this branch, after the upgrade): `/central/notice`
reported every accepted section as managed, so the Updates page would have
said "Managed by the central console" on an instance whose policy set only
a notice. Now a section is managed only when the policy sets it and the
instance accepts it; the test asserts `managed == {"notice": true}` for a
notice-only policy. dev1 runs the build from before this fix.

## 4. Not verified

* Two real servers: a console on one machine, an instance on another over
  HTTPS with the console's CA certificate. dev1 is the only server.
* The commands `download_update`, `approve_update` and `refresh_catalogs`,
  and a policy's `updates` section, live: dev1 has no update source or
  catalog. Their paths are the same as the Updates and Module Manager pages
  use, and the tests cover them.
* The `instance_offline` alert live (the console was switched off before
  the threshold passed; covered by a test).
* Browser checks: System → Central console (instances, the instance page
  with graphs, policies, tokens), System → Central management, the notice
  banner, the Updates page callout.

## 5. Known limitations

* Leaving does not tell the console: the instance stays listed until the
  console revokes and removes it, and raises `instance_offline` after the
  threshold. The design keeps the instance from making any call the console
  did not ask for except enroll and check-in.
* Recipients and the update policy set by the console remain the instance's
  own values after a section is refused or the instance leaves; only
  firewall rows and the notice are withdrawn.
* The console is one installation; there is no console of consoles, and no
  high availability for it (Milestone 16).

## 6. Open items

* CENTRAL_MANAGEMENT.md §11:
  1. One or more Veyra servers, and which would be the console?
  2. Which settings should the console manage first (built: update policy
     and window, firewall allow-list, alert recipients, notice)?
  3. Should approving updates from the console be allowed (built: yes,
     refusable per instance)?
  4. Default for new instances: accept everything (built) or opt in?
* Earlier open items are unchanged: MULTI_TENANCY.md §10 and the live
  two-organization test (M14 report §4, §6).

## 7. Next milestone

Roadmap row 16: high availability.

## 8. Owner decisions

* 2026-10-15: milestone started with the proposed defaults while the §11
  questions are open.
* 2026-10-15: approved ("M15 approved, go ahead with 0.21.0"); the §11
  questions, the browser checks and the two-organization test remain open.

## Addendum (2026-10-15 19:52 UTC): 0.21.0 on dev1

The owner upgraded dev1 from the M15 test build (0.20.0-1b62de19a6) to the
release build **0.21.0-e5a12c6466** from `~/veyra-release` (dry run first,
then the real run): backups taken, schema current (`0028`), all verify
checks OK (`catalog-trust` warns, as expected without a catalog key). The
central console is off; dev1 is not enrolled anywhere. This build includes
the `/central/notice` fix from §3.
