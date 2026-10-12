# Milestone 2: Completion Report

**Milestone:** 2 — Backend, frontend, database and authentication (hardening, password reset, sessions UI, MFA design)
**Date:** 2026-10-12
**Branch:** `milestone-2` (pushed to `manderson20/veyra`; not merged to `main`)
**Status:** Complete. Awaiting the project owner's review.

## 1. Scope (approved 2026-10-12 with "proceed with the project")

Harden authentication and sessions, give users and administrators a way to
reset passwords without email delivery, add a sessions UI, and design
multi-factor authentication for a later milestone.

## 2. Results

| Task | Result | Where |
|---|---|---|
| Sessions API and UI | Done. Users list and end their own sessions and sign out everywhere else; administrators list and end a user's sessions. Device, address, sign-in, last-activity and expiry are shown; idle-expired sessions are not listed as active. | `backend/veyra/api/v1/auth.py`, `users.py`; `frontend/src/app/(app)/account/`, `users/view/` |
| Password reset | Done, without email ([ADR 0011](../adr/0011-password-reset-links.md)): administrator-issued and console-issued one-time links (hashed, 24 h, single use, replaced by a newer link, generic failure, rate limited), a public `/reset-password/` page, and account unlock. The user chooses the password; all sessions end. | `backend/veyra/core/security/password_reset.py`, `cli/main.py`; `frontend/src/app/(public)/reset-password/` |
| Forced password change | Done. Passwords set by an administrator are temporary unless they opt out; the user can reach only the authentication routes until they choose a password, and the UI takes them to the account page. | `backend/veyra/core/deps.py`, `frontend/src/components/shell/AppShell.tsx` |
| Password policy | Done: minimum distinct characters, weak-word check however padded, no personal information, new password must differ. Documented limits: no breached-password service (would need a network call). | `backend/veyra/core/security/passwords.py` |
| Hardening | Done: fetch-metadata rejection of cross-site mutations (defence in depth behind the CSRF token), `Clear-Site-Data` on sign-out, NGINX rate limit extended to the reset endpoints, lockout visible to administrators only, hourly purge of expired sessions and used tokens with a 30-day retention, `veyra sessions purge/revoke`. | `backend/veyra/main.py`, `installer/templates/nginx/veyra.conf.in` |
| Database | Migration `0002`: `password_reset_tokens`, `users.password_changed_at`, `users.must_change_password`. `alembic check` passes; upgrade → downgrade → upgrade verified on a fresh database. | `backend/veyra/migrations/versions/0002_password_reset_and_sessions.py` |
| MFA design | Done, not implemented: TOTP with recovery codes first, passkeys second, pre-auth session at sign-in reusing the forced-change route restriction, encrypted secrets with the installation key, per-role policy with a grace window, console reset. | [MFA_DESIGN.md](../MFA_DESIGN.md), [ADR 0012](../adr/0012-mfa-approach.md) |
| Documentation | API, architecture §6, database schema, SECURITY.md, installation (console recovery), changelog, ADR index. | `docs/` |
| Branding (left over from Milestone 0) | Done: the owner's approved artwork is installed; see the branding commit and `frontend/public/branding/README.md`. | — |

## 3. Testing (veyra-dev1, 2026-10-12, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (72 files) |
| Backend pytest against PostgreSQL 18.6 | **131 passed** (23 new, in `test_api_sessions_and_reset.py` and `test_security_units.py`) |
| Alembic `0002`: upgrade, `alembic check`, downgrade to `0001`, upgrade | Passed on a fresh database |
| Frontend lint / typecheck / vitest | Clean / clean / **21 passed** (new: user-agent description, lockout helper) |
| Frontend `npm run build` | Passed; `/account` and `/reset-password` exported |
| ShellCheck; installer helper tests | Clean; **29 passed** |
| Rendered NGINX template with the new regex location | `nginx -t` syntax ok |
| API boot on the development database after migration; new endpoints in OpenAPI; cross-site mutation refused; bad reset token answered generically; `veyra db upgrade`, `users unlock`, `users reset-password`, `sessions purge` | Passed (manual, curl) |

What the new tests cover: listing own sessions with the current one
marked; revoking one session signs that browser out; the current session
cannot be revoked through the list; sign out everywhere else; users cannot
see or end each other's sessions; administrators list and end a user's
sessions; organization administrators cannot touch platform
administrators' sessions, links or lockouts; a temporary password blocks
every non-auth route until changed and the same password is refused;
administrators may hand out a permanent password explicitly; the reset link
flow end to end (hashed storage, check, policy, single use, old sessions
revoked, audit, no sign-in on reset); a newer link replaces the older one;
expired links and disabled accounts are refused generically; the reset
check is rate limited; lockout and unlock through the API and the CLI;
purge keeps live sessions; `Sec-Fetch-Site: cross-site` mutations are
refused while reads and same-origin pass; `Clear-Site-Data` on sign-out;
the stronger password policy with personal-information and weak-word
cases.

Not tested: the UI in a browser (no browser on the server; the pages
type-check, lint and build); the installed instance on dev1 has not been
upgraded to this revision (that is an `upgrade.sh` run for the owner, as
in Milestone 1).

## 4. Decisions made (for the owner to confirm)

1. **Reset links instead of email** for this milestone (ADR 0011); the
   self-service "forgot password" flow waits for email delivery (M7) and
   reuses the same tokens.
2. **Administrator-set passwords are temporary by default.** An
   administrator can untick "require change" when creating a user or
   setting a password (for example for a service account).
3. **Lockout details are visible to administrators** (`locked_until`),
   never on the sign-in form.
4. **MFA is designed but not built** in this milestone, as the roadmap
   says. The design proposes TOTP first and passkeys after trusted TLS. A
   natural slot is a short milestone right after this one or inside
   Milestone 17 (production hardening); the owner decides.

## 5. Known limitations

* The sessions list is only as precise as the `User-Agent` header; the UI
  says "Unknown device" rather than guessing.
* The fetch-metadata check depends on the browser sending
  `Sec-Fetch-Site`; the CSRF token remains the primary control.
* Rate limits are still per API process (as documented since Milestone 0).
* Reset links are shown once; if the administrator loses one, they issue
  another, which invalidates the first.
* No "remember this device", no re-authentication for sensitive actions
  other than the password change (which needs the current password).

## 6. Blocked and open items

* veyra-dev2 (from Milestone 1) still unreachable.
* License choice (from Milestone 0).
* The installed instance on dev1 can be upgraded to this revision with
  `sudo installer/upgrade.sh --yes` to see the new pages in a browser.

## 7. Proposed Milestone 3 (for approval)

Telephony engine integration per the roadmap: the deployer service,
configuration generation from the database, ARI status, reload and
rollback, against Asterisk 22 on dev1 and 20 in the 24.04 container.
