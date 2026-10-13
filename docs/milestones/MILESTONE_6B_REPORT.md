# Milestone 6b: Completion Report (draft)

**Milestone:** 6b — Veyra Companion browser extension (sign in with Veyra credentials including the second factor, click-to-dial, directory lookup, incoming caller-ID pop-up, personal speed dials) and the server pieces it needs
**Date:** 2026-10-13 (in progress)
**Branch:** `milestone-6b` (pushed to `manderson20/veyra`; not merged to `main`)
**Version:** 0.8.0-dev
**Status:** Software in progress; see §3.

## 1. Scope (approved 2026-10-13)

Per the Milestone 6 report §7 and the owner's request of 2026-10-12: a
Chrome/Edge extension replacing a vendor desktop dialler, with Veyra sign-in
(MFA included), click-to-dial any number so the desk phone rings first and
the call is then placed through the Milestone 5 originate API and the
Milestone 6 routes, directory lookup, an incoming caller-ID pop-up fed by a
server push channel, and speed dials stored in the user's Veyra profile.
Design and reference: [COMPANION.md](../COMPANION.md); decision record:
[ADR 0015](../adr/0015-bearer-tokens.md).

## 2. Results

| Task | Result | Where |
|---|---|---|
| Sign-in without cookies | Done. `POST /auth/companion/login` and `/verify` reuse the web flow's password check, lockout, rate limit, MFA policy and code verification (extracted into `check_credentials`, `mfa_decision`, `attempt_second_factor`) and issue a `vyc_…` bearer token; users who still have to enrol a second factor are sent to the web interface (`403 mfa_enrolment_required`); temporary passwords block tokens. | `backend/veyra/api/v1/auth_companion.py`, `auth.py`, `auth_mfa.py` |
| Scoped bearer tokens | Done. `api_tokens` (SHA-256 digest, device label, addresses, idle expiry 30 days extended on use, hard maximum 180 days, both configurable); `Authorization: Bearer` resolution ignores cookies and the CSRF and fetch-metadata checks; `Principal.token_scopes` intersects the user's grants (an administrator's token cannot administer); listing and revocation for the user (`/auth/tokens`), administrators (`/users/{id}/tokens`) and the console (`veyra sessions revoke`); the worker purges expired tokens. | `core/security/api_tokens.py`, `core/deps.py`, `core/security/principal.py`, migration `0007` |
| Own extensions and preferences | Done. `GET /me/extensions` with registration state; `GET/PUT /me/preferences` with a validated `companion` section (speed dials, dial prefix, default extension, notification toggles, `tel:` handling). | `api/v1/me.py`, `user_preferences` |
| Directory | Done. `GET /directory?q=` lists enabled extensions and their people in the caller's organizations; new permission `directory.read` for every role including standard users. | `api/v1/directory.py` |
| Call events | Done. One ARI event WebSocket per API process (`websockets`), channel events normalised into `call.ringing`, `call.dialing`, `call.answered`, `call.ended` for phone endpoints; `POST /events/ticket` and `WS /events/calls` deliver a user's own events with pings, pong timeout and token/session re-checks; engine status reports the listener; NGINX proxies the path with the `Upgrade` headers. | `telephony/asterisk/events.py`, `core/callevents.py`, `api/v1/events.py`, `installer/templates/nginx/veyra.conf.in` |
| Account page | Done. "Connected apps" card (own tokens, revoke one or all) on the account page; administrators see and revoke a user's tokens on the user page. | `frontend/src/components/account/ConnectedAppsCard.tsx` |
| Browser extension | *In progress.* Manifest V3, TypeScript, Vite build under `companion/`: popup (sign-in with second factor, dial, speed dials, directory, recent calls), options (preferences synced to the server), service worker (token, event stream with reconnect, notifications with "Call back", context menu), optional `tel:` link handling. | `companion/` |
| Documentation | `COMPANION.md`, ADR 0015, API, schema, networking and engine docs, changelog. | `docs/` |

## 3. Testing (veyra-dev1, 2026-10-13, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (95 files) |
| Backend pytest against PostgreSQL 18.6 | **237 passed** (8 new: Companion login and scoped token use incl. hostile fetch metadata, error parity with the web flow and temporary passwords, second factor by recovery code and TOTP with challenge expiry and lockout and enrolment-required, token expiry/revocation/admin view/disabled user, administrator tokens are scoped too, preferences validation and directory scoping, event ticket and WebSocket delivery and filtering, ARI event translation) |
| `alembic check` | No drift (migration `0007`) |
| Frontend lint / typecheck / vitest | Clean / clean / **28 passed** |
| Frontend `npm run build` | *Pending* |
| Extension typecheck / vitest / build | *Pending* |
| **Owner's `upgrade.sh` to this milestone on dev1** | *Pending* |
| **Live on dev1: Companion-style client signs in, opens the stream, sees `call.ringing`/`call.answered`/`call.ended` for an inbound call to its extension and `call.dialing` for click-to-dial** | *Pending* |
| **Owner loads the extension unpacked in Chrome or Edge on site: sign-in with the second factor, dial from the popup, caller-ID pop-up on an incoming call** | *Pending the owner* |

## 4. Not verified

* The extension in a real browser by the owner (§3).
* Edge specifically (same engine as Chrome; the manifest targets both).

## 5. Known limitations

* The event listener runs in the API process; with more than one API
  worker each would hold its own ARI socket (the service runs one process).
* The service worker is kept alive by the WebSocket and a one-minute alarm;
  a browser that suspends extensions aggressively may miss a pop-up by a few
  seconds after a long idle.
* Caller-ID pop-ups show what Asterisk knows at ring time; name lookup
  against external sources is not attempted.
* The server certificate must be trusted by the browser's operating system
  (the installer's self-signed certificate needs importing until Milestone
  17 covers certificates).
* One extension per browser profile signs in as one user; switching users
  means signing out first.

## 6. Open items

* Owner's on-site checks (§3).
* Store publication (Chrome Web Store, Edge Add-ons) is a later step; the
  build produces a zip for sideloading and enterprise policy deployment.

## 7. Proposed Milestone 7 (for approval)

Voicemail and IVR (roadmap row 7, 0.9.0): voicemail boxes per extension
with PIN, greeting and voicemail-to-email, message waiting indication,
voicemail as an inbound and after-hours destination; IVR menus with
recorded or synthesised prompts, key mapping to extensions, ring groups
(later), other IVRs and voicemail, timeout and invalid handling, direct
extension dialling; prompt recording from a phone and upload from the
browser; generated dialplan contexts and `voicemail.conf`.
