# Milestone 4b: Completion Report

**Milestone:** 4b — Multi-factor authentication (TOTP, recovery codes, per-role policy)
**Date:** 2026-10-12
**Branch:** `milestone-4b` (pushed to `manderson20/veyra`; not merged to `main`)
**Version:** 0.5.0-dev (becomes 0.5.0 on approval)
**Status:** Implementation complete and tested. Pending: the dev1 upgrade and an enrolment with a real authenticator app by the owner (§3, §4).

## 1. Scope (approved 2026-10-12)

Per the Milestone 4 report §8: TOTP enrolment and verification with a
pre-authentication session at sign-in, recovery codes, per-role policy with a
grace period, administrator reset, console reset for the recovery
administrator; TOTP secrets encrypted with the installation key. Design:
[MFA_DESIGN.md](../MFA_DESIGN.md), [ADR 0012](../adr/0012-mfa-approach.md).

## 2. Results

| Task | Result | Where |
|---|---|---|
| TOTP | Done. RFC 6238 (30 s, 6 digits, SHA-1) with the standard library; verified against the RFC test vectors; one step of drift; a step at or before the last accepted one is refused (replay). | `backend/veyra/core/security/totp.py` |
| Pre-authentication session | Done. Password accepted → 202 with the challenge and a 5-minute session that can reach only challenge, verify, TOTP begin/confirm (only while nothing is enrolled) and logout; everything else answers `403 mfa_required`. Verification extends the session to the normal lifetime and rotates the CSRF token. Five wrong codes revoke it. Existing sessions on upgrade stay valid (migration backfill). | `backend/veyra/core/deps.py`, `core/security/sessions.py`, `api/v1/auth.py`, migration `0004` |
| Enrolment | Done. `POST /auth/mfa/totp/begin` (server-rendered SVG QR code via `segno`, manual key, device label) and `/totp/confirm` (first code; generates the ten recovery codes on the first device and returns them once; completes a pre-auth sign-in). | `backend/veyra/api/v1/auth_mfa.py`, `frontend/src/components/account/TotpEnrolment.tsx` |
| Recovery codes | Done. Ten codes of ten characters from a 32-symbol alphabet, Argon2id-hashed, single use, accepted with or without the dash; regeneration behind the password; remaining count shown on the account page. | `backend/veyra/core/security/mfa.py` |
| Management | Done. Account page card: status, devices with last use, add a device, remove (password; the last device cannot be removed while policy requires it), new recovery codes. | `frontend/src/components/account/TwoFactorCard.tsx` |
| Policy | Done. `security.mfa`: roles that must enrol (Platform and Organization Administrators by default), grace days (14), allowed methods. Evaluated from role assignments at sign-in; saving re-evaluates every active local user and is audited. Settings → Two-factor policy card. The first administrator's grace window starts at setup. Grace notice in the shell. | `backend/veyra/core/security/mfa.py`, `frontend/src/components/account/MfaPolicyCard.tsx`, `frontend/src/components/shell/MfaNag.tsx` |
| Resets | Done. `POST /users/{id}/mfa/reset` (users.write, platform-administrator guard, not on oneself) and `veyra users mfa-reset <email>`: remove devices and codes, sign out everywhere, start a fresh grace window; "Reset" button on the user page. | `backend/veyra/api/v1/users.py`, `cli/main.py`, `frontend/src/app/(app)/users/view/page.tsx` |
| Sign-in UI | Done. Second step with authenticator code or recovery code, "start over", and inline enrolment when policy requires it; a reload during the second step resumes it. | `frontend/src/app/(public)/login/page.tsx` |
| Hardening | Done. Secrets encrypted with the installation key and bound to the user id; per-address limiter shared with sign-in and an NGINX rate limit on `/auth/mfa/verify`; audit of every step without secrets or codes. | `installer/templates/nginx/veyra.conf.in` |
| Documentation | MFA design marked implemented with notes (§11); security, architecture, API, schema, installation, development, changelog updated. | `docs/` |

Also in this branch, at the owner's request: the **Deploy changes** button
now appears after any save that may affect the engine and stays until a
deployment runs (sticky flag `telephony.pending_change`), not only when the
generated files differ; the roadmap gained the click-to-dial API (Milestone
5) and the Veyra Companion browser extension (Milestone 6b).

## 3. Testing (veyra-dev1, 2026-10-12, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (84 files) |
| Backend pytest against PostgreSQL 18.6 | **193 passed** (18 new: TOTP vectors, drift and replay, recovery code helpers, policy validation; grace then forced enrolment; sign-in with code, replay, recovery code, lockout; removal and regeneration rules; policy per role and audit; administrator and console resets; missing key; secret bound to the user) |
| `alembic check` | No drift |
| Frontend lint / typecheck / vitest | Clean / clean / **22 passed** (new: redirect on `403 mfa_required`) |
| Frontend `npm run build` | Passed |
| **Owner's `upgrade.sh` to this milestone on dev1** | *Pending* |
| **Enrolment with a real authenticator app on a phone, sign-in with a code, sign-in with a recovery code** | *Pending the owner* |

## 4. Not verified

* The UI flow with a real phone and authenticator app (no browser or phone
  on the server). The API flow is covered by tests with generated codes.
* Clock drift larger than 30 seconds between the server and a phone is not
  tolerated by design; the server clock is synchronized (preflight checks
  it).

## 5. Known limitations

* Passkeys/WebAuthn, "remember this browser", SMS and email codes are out of
  scope (design §2, §10).
* Recovery codes are verified by Argon2id comparison against each unused
  code (at most ten), so a recovery sign-in takes up to about half a second.
* The per-address limiter is per API process (as for sign-in); NGINX
  enforces the same limit in front.
* Policy applies to local accounts; SSO accounts (later) rely on the
  provider's MFA.

## 6. Open items

* The first platform administrator on dev1 is inside the 14-day grace
  window; the account page and the shell remind them to enrol.
* veyra-dev2 is not provisioned (deferred).

## 7. Proposed Milestone 5 (for approval)

SIP registration and internal calling: live registration status per
extension (ARI endpoint events), active calls view, a first phone registered
and an internal call between two extensions on dev1, the click-to-dial API
(originate from a user's extension), and the deploy-mode drop-down on the
Deploy changes button (deploy now, or wait until no calls are active).
