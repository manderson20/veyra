# Milestone 13 Report — Integrations

Branch `milestone-13` (from `milestone-12` at 0.18.0). Design:
[INTEGRATIONS.md](../INTEGRATIONS.md). Status: **approved 2026-10-15, released as 0.19.0.**

## 1. Scope (roadmap row 13)

Connect Veyra to the systems around it: single sign-on, tokens for systems
that call Veyra, webhooks for systems Veyra tells about events, and the
ring groups and queues in the Companion directory promised in M8.

## 2. Results

* **Single sign-on** (System → Sign-in). OpenID Connect providers:
  * Google Workspace, Microsoft Entra ID or any compliant provider.
  * Authorization code flow with PKCE, `state` and `nonce`.
  * The ID token's signature is checked against the provider's keys (RS256 or ES256 only; `none` and HMAC are refused). The keys are refetched when an unknown key id appears.
  * `iss`, `aud`/`azp`, `exp`/`iat` (5 minutes of skew), a verified e-mail address and the allowed domains are checked. For Google, the Workspace domain (`hd`) is checked too, so personal Gmail accounts are refused.
  * One redirect address for every provider (`/api/v1/auth/sso/callback`), shown before anything is saved.
* **Accounts and SSO:**
  * Existing accounts are linked by e-mail address on first use, then matched by the provider's subject.
  * Optional account creation with a chosen role.
  * Deactivated accounts stay out. The recovery administrator is never linked.
  * "Require single sign-on" turns off the password and reset links for linked accounts.
  * The user page shows linked identities, with "Unlink".
  * Every sign-in and refusal is audited with its reason.
* **Companion:**
  * "Sign in with Google" (or any provider) in the popup, through `chrome.identity.launchWebAuthFlow`.
  * The extension keeps its own PKCE pair. The server hands a 60-second, single-use code only to the packaged extension's `chromiumapp.org` address.
  * With the new policy key `ssoProvider`, the extension signs in silently (`prompt=none`) at start-up, at most hourly while signed out. On a managed Chromebook this is the "no clicks" sign-in asked for in M6b.
  * Only the `identity` permission was added, which shows no install warning.
* **Integration tokens** (System → Integrations):
  * Organization tokens (`vyi_…`) with scopes from a fixed list: paging, bells, active calls, click-to-dial, call history, directory, reports.
  * Optional allowed addresses and expiry; rotation and revocation.
  * Each is held by a hidden service account, so the existing bearer path and the audit log work unchanged. The actor shows as "Integration: <name>".
* **Outgoing webhooks:**
  * Events: `call.ringing`, `call.answered`, `call.ended`, `voicemail.message`, `page.sent`, `bell.rang`, `alert.raised`/`alert.resolved`, `registration.changed`, `deployment.finished` and module events.
  * Sources write an outbox row in the database, and the worker delivers every 5 seconds.
  * Signed with HMAC-SHA256 (`Veyra-Signature: t=…,v1=…`). During a secret rotation, both signatures are sent for a day.
  * Retries after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours. Live call events get one attempt only.
  * A webhook turns itself off after three days of failures.
  * Delivery log (7 days, last 100) with redeliver, a test button, and a Python check example on the page.
  * Destinations are resolved and pinned for each attempt; loopback, link-local, multicast and reserved addresses are refused.
* **Voicemail notifications:** Asterisk's `externnotify` now calls the new `installer/bin/veyra-vmnotify`. It drops a count file in the mail queue directory, and the worker turns a rising count of new messages into `voicemail.message`.
* **Directory:** ring groups and queues are listed; the Companion marks them.
* **Migration `0026`:** `identity_providers`, `user_identities`, `sso_requests`, `integrations`, `webhooks` and `webhook_deliveries`.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (177 files) |
| Backend pytest | **391 passed**. M13 added 12 tests: ID token rules (wrong audience, issuer, nonce, expiry and key; `none` and HS256; tampering; `hd`); ES256; the web flow against a fake provider (linking, PKCE and secret sent, replayed state, Require SSO with reset links and passwords refused, the recovery administrator still signing in); refusals (no account, recovery administrator, other Workspace, missing browser cookie, `login_required`); account creation with role and the `next` open-redirect fix; the Companion flow (foreign redirect, wrong verifier, spent code, `interaction_required`); provider administration; integration tokens (scopes, administrative scopes refused, allowed addresses, rotation, audit actor, hidden service accounts); webhook rules (http, loopback, metadata address, credentials in the URL, unknown events, rebinding); delivery with signature, pinned address and SNI, retry, auto-off, re-enable, test, rotation with two signatures, redeliver, prune; live call events, voicemail counts and registrations; directory groups; `externnotify` in `voicemail.conf` |
| `alembic check` | No drift (migration `0026`, downgrade and upgrade again) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **43 passed** / passed |
| Companion typecheck / vitest / build | Clean / **29 passed** (PKCE, start address, redirect parsing) / passed; `background.js` still one file |
| Installer library tests | **52 passed**; `veyra-vmnotify` refuses arguments with other characters |
| **Owner's `upgrade.sh` on dev1** | 0.18.0-25aadce9f5 → **0.18.0-6769850bf8** (15:15 UTC: schema `0026`, `vmnotify-command` OK, all checks OK) |

### Live check on dev1 (15:16 UTC)

A small receiver ran on dev1's LAN address. The test webhook and integration token were created as the service account, then removed.

| Check | Result |
|---|---|
| Test delivery | `webhook.test` delivered by the worker in 29 ms, HTTP 200, signature valid with the webhook's secret |
| Voicemail | A count file for box 22215 (as `veyra-vmnotify` writes it) became `voicemail.message`, delivered within 5 s with a valid signature: box number and name, 1 new, 0 old |
| Integration token, `directory.read` | `GET /directory` 200 (extensions listed), `GET /users` 403, `GET /pages` 403; an unknown `vyi_` token 401 |
| Sign-in providers | `GET /auth/sso/providers` (public) 200 `[]` |
| Cleanup | Webhook, integration and service account removed (0 left); receiver stopped; no count files left |

## 4. Not verified

* **A real Google sign-in**, in the browser and in the Companion, needs an OAuth client in your Google Cloud console (§9 question 1). Silent sign-in also needs a managed Chrome profile and the client marked as trusted. These are your checks; the flow is covered against a fake provider in the tests.
* **`externnotify` in Asterisk**: the generated `voicemail.conf` has the line, but dev1 gets it only with its next configuration deployment. Until then Asterisk does not call the script. The live check fed the count file by hand.
* **Live call events and `call.ended`**: no calls were placed (no handset test).
* `registration.changed` and `deployment.finished` were tested in the suite only.
* **Browser checks:** System → Sign-in, System → Integrations, the sign-in page buttons, and the user's Sign-in card.

## 5. Known limitations

* Providers and "Require single sign-on" apply to the whole installation until multi-tenancy (M14).
* `voicemail.message` carries counts, not the caller: Asterisk's `externnotify` passes nothing else.
* `page.sent` covers pages Veyra starts (interface, bell, integration), not pages dialled from a phone.
* The silent Companion sign-in uses the account the browser is signed in to. It does not read the profile's address, which would need a permission with an install warning.
* SAML, SCIM and directory sync, group-to-role mapping, and a phone directory for provisioned phones are out of scope (INTEGRATIONS.md §10).

## 6. Open items

* INTEGRATIONS.md §9:
  1. Who creates the Google OAuth client?
  2. Should accounts be created automatically on first sign-in?
  3. Turn on "Require single sign-on"?
  4. Do you want a phone directory for the Poly and Yealink phones?
* Earlier open items are unchanged; see the M12 report §6.

## 7. Next milestone

Roadmap row 14: multi-tenancy (telephony isolation and tests before
activation, 0.20.0). The alternative is 11b, the module service runtime, if
community modules come first.

## 8. Owner decisions

* 2026-10-15: milestone started ("go ahead with M13"); built with the
  proposed defaults while the §9 questions are open.
* 2026-10-15: approved ("M13 approved, go ahead with 0.19.0"); the §9
  questions remain open.

## Addendum (2026-10-15 15:19 UTC): 0.19.0 on dev1

The owner upgraded dev1 from the M13 test build (0.18.0-6769850bf8) to the
release build **0.19.0-203f47f524** from `~/veyra-release` (dry run first,
then the real run): backups taken, schema current (`0026`), all verify
checks OK including `vmnotify-command` (`catalog-trust` warns, as expected
without a catalog key).
