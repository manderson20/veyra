# Veyra Companion

A browser extension (Chrome and Edge, Manifest V3) that puts the phone
system next to the user's browser: sign in with Veyra credentials, dial any
number so the desk phone rings first and then places the call, look people
up, see who is calling, and keep personal speed dials. It replaces a
vendor desktop dialler. Delivered in Milestone 6b together with the server
pieces it needs: scoped bearer tokens, a call-event stream, a directory
endpoint and per-user preferences.

## 1. Goals

* Works with a standard user account: no administrator permissions, no
  extension management rights.
* The same security model as the web interface: password, second factor
  when the policy or the user's enrolment requires it, lockout, audit.
* Nothing the extension holds can be used for more than it needs. A stolen
  token can dial from the user's own phones and read the directory; it
  cannot change configuration or read other people's data.
* No new network exposure: the extension talks to the same HTTPS port as
  the browser, and Asterisk stays on loopback.
* Everything personal lives on the server (speed dials, dial prefix,
  notification choices), so it follows the user to another browser.

## 2. Architecture

```
Browser ─ extension ──HTTPS /api/v1/… (Bearer token)──▶ NGINX ─▶ veyra-api
                   ──WSS /api/v1/events/calls?ticket=…──▶ NGINX ─▶ veyra-api ◀── ARI events ── Asterisk
```

* **Bearer tokens** (`api_tokens`, [ADR 0015](adr/0015-bearer-tokens.md)):
  issued by a login flow designed for clients without cookies, scoped to a
  fixed permission set, revocable from the account page.
* **Call events**: the API process keeps one WebSocket to Asterisk's ARI
  event stream (`/ari/events?app=veyra&subscribeAll=true`), normalises
  channel events into call events and fans them out to connected clients,
  each seeing only the calls of their own extensions. Clients connect with
  a one-time ticket because browsers cannot set headers on WebSockets.
* **Directory**: one endpoint listing the extensions (and the people they
  belong to) in the organizations the user belongs to.
* **Preferences**: a JSON document per user, validated server-side.
* **Click-to-dial**: the existing `POST /calls/originate` (Milestone 5);
  the Milestone 6 outbound routes carry the call to the carrier.

The `websockets` package is added for both the server side (uvicorn uses
it automatically) and the ARI client. NGINX gets a `location` for the
event stream with the `Upgrade` headers and a long read timeout.

## 3. Sign-in and tokens

### 3.1 Login flow (no cookies)

```
POST /auth/companion/login    {email, password, device}
   200 {token, token_id, expires_at, user, permissions, extensions, installation_name, version}
   202 {challenge, enrol, methods (count), expires_at}  second factor pending
   401 invalid_credentials | 423 account_locked | 429 rate_limited
   403 mfa_enrolment_required                         must enrol in the web interface first
POST /auth/companion/verify   {challenge, code, device}
   200 (same body as a successful login)
   401 invalid_code | 401 mfa_locked | 410 challenge_expired
POST /auth/companion/logout   (Bearer)  -> 204, revokes this token
```

The flow reuses the web login's checks (password hashing, lockout counters,
rate limiter, MFA policy) and the web verify logic (TOTP with drift and
replay guard, recovery codes, five failures lock the attempt). The
`challenge` is the raw token of a five-minute pre-authentication session,
the same object the web interface uses, so the limits and the audit trail
are shared. `device` is a label the extension builds from the browser and
OS (`Chrome on Windows`), stored with the token.

A user who must enrol a second factor (policy requires it, grace period
over, nothing enrolled) is sent to the web interface: enrolment stays a
browser-page flow with the QR code and recovery codes.

### 3.2 Tokens

| | |
|---|---|
| Table | `api_tokens`: `id`, `user_id`, `kind` (`companion`), `label`, `token_hash` (SHA-256), `scopes` (JSONB list of permission keys), `created_at`, `created_ip`, `expires_at`, `last_used_at`, `last_used_ip`, `revoked_at` |
| Format | `vyc_` + 43 URL-safe characters (32 random bytes); the prefix makes a leaked token recognisable in logs and scanners |
| Lifetime | Expires `companion_token_idle_days` (30) after its last use and never later than `companion_token_max_days` (180) after creation; `last_used_at` is written at most once a minute |
| Scopes | Companion tokens carry exactly `calls.originate`, `calls.read`, `directory.read`, `me` (own extensions, preferences, token management). A permission the user does not hold is not granted by the token: the effective set is the intersection |
| Resolution | `Authorization: Bearer <token>` is checked before the session cookie; when the header is present cookies are ignored, the CSRF and `Sec-Fetch-Site` checks do not apply (a bearer token is not an ambient credential), and a pre-authentication state cannot exist |
| Management | `GET /auth/tokens` (own), `DELETE /auth/tokens/{id}`, `POST /auth/tokens/revoke-all`; administrators: `GET /users/{id}/tokens`, `DELETE /users/{id}/tokens/{token_id}`; a disabled user's tokens stop working at once; `veyra sessions revoke` also revokes tokens |
| Account page | "Connected apps" card: device label, created, last used (with address), revoke |
| Audit | `auth.companion_login`, `auth.token_issue`, `auth.token_revoke`, plus the usual `auth.login` and `auth.mfa_verify` outcomes |

## 4. Server endpoints

```
GET  /me/extensions                 the caller's own extensions with registration state
GET  /me/preferences                {companion: {...}}
PUT  /me/preferences                validated document, replaces the companion section
GET  /directory?q=                  {results: [{type: "extension", id, number, name, organization, user_display_name, user_email, registered}], total}
POST /events/ticket                 {ticket, expires_in, url}  (one-time, 60 s)
WS   /events/calls?ticket=…         call events for the caller's extensions
POST /calls/originate               (existing) {extension_id, number}
```

**Preferences** (`user_preferences`: `user_id` PK, `data` JSONB,
`updated_at`). The `companion` section: `speed_dials` (up to 50 of
`{label, number}`), `dial_prefix` (digits, at most 8; prepended to external
numbers), `default_extension_id`, `notify_incoming`, `notify_missed`,
`handle_tel_links`. Unknown keys are rejected; other sections are reserved
for later features.

**Directory** needs the new permission `directory.read`, granted to every
role including standard users. It lists enabled extensions of active
organizations the caller has that permission in, joined with their users,
with a case-insensitive search over number, display name, user name and
email, at most 50 rows.

**Events.** The ticket is a random token stored in memory with the user id
and a 60-second expiry; it is consumed on connect. Messages are JSON:

| Type | When | Fields |
|---|---|---|
| `hello` | On connect | `extensions: [{id, number, name}]`, `server_time` |
| `call.ringing` | One of the user's phones starts ringing | `channel_id`, `extension_id`, `extension_number`, `remote_number`, `remote_name`, `direction: "in"`, `at` |
| `call.dialing` | One of the user's phones places a call | same, `direction: "out"`, `remote_number` = dialled number |
| `call.answered` | The call is up | `channel_id`, `extension_id`, `at` |
| `call.ended` | The channel is gone | `channel_id`, `extension_id`, `answered: bool`, `cause`, `at` |
| `ping` | Every 20 s | clients answer `pong`; silence for 60 s closes the socket |

Events come from ARI `ChannelCreated`, `ChannelStateChange`,
`ChannelCallerId` and `ChannelDestroyed` for channels named
`PJSIP/<endpoint>-…`; the listener keeps a small per-channel state (who the
remote party is, whether it was answered) and drops channels that belong to
trunks or to other users. The listener reconnects with backoff when
Asterisk restarts and the engine page reports its state (`events:
connected | reconnecting | disabled`). Only the API process connects to
ARI events; the deployer and worker do not.

## 5. The extension

Directory `companion/` (TypeScript, built with Vite into `companion/dist`;
store publication is a later step). The installer packages the build as
`veyra-companion.zip`, served by NGINX at `/downloads/veyra-companion.zip`;
the account page's *Connected apps* card links to it with the load-unpacked
steps, so users never need the source tree. `companion/README.md` has the
developer build steps.

| Part | Role |
|---|---|
| Service worker (`background.ts`) | Holds the token in `chrome.storage.local`; keeps the event WebSocket open (reconnect with backoff; a `chrome.alarms` tick every minute as the safety net); shows notifications for ringing and missed calls with a "Call back" button; registers the context menu "Call … with Veyra" on selected text; answers messages from the popup, options page and content script |
| Popup (`popup.html`) | Sign-in (server address, email, password, second-factor code); dial field with the user's extensions and a Call button; speed-dial buttons; directory search with one-click dial; recent calls from the event stream; connection status |
| Options page | Dial prefix, notification toggles, "handle tel: links", speed-dial editor; all saved to the server through `/me/preferences` |
| Content script (optional) | When enabled, intercepts clicks on `tel:` links and dials through Veyra instead of the operating system; registered at run time with the `scripting` API after the user grants the site permission |

Permissions requested: `storage`, `notifications`, `contextMenus`,
`alarms`, optional `scripting`; host permission for the server origin is
requested at sign-in (`optional_host_permissions`), so the extension
touches no site it was not told about. With the host permission granted
the browser exempts the extension's requests from CORS, so the API needs
no CORS headers.

Number handling in the extension: digits, `*`, `#` and a leading `+` are
kept; a number longer than the installation's extension length gets the
user's dial prefix unless it already starts with it; `+1` becomes the
prefix followed by `1` for North American numbers. The server validates
again and the outbound routes decide what is dialable.

The server's certificate must be trusted by the browser's operating system
(an extension cannot click through a certificate warning). Installations
with the installer's self-signed certificate need it imported, or a
certificate from the organization's CA (Milestone 17 covers certificate
management).

### 5.1 Deployment to managed browsers

Chrome and Edge install extensions with one click only from their stores;
anything else is either *load unpacked* (developer mode) or an install
pushed by browser policy. Veyra supports the policy route out of the box:

* The installer signs the build into `veyra-companion.crx` with an RSA key
  kept in `/etc/veyra/secrets/companion-signing.key` (created on first
  packaging, never regenerated), so the **extension ID** stays the same
  across releases. The packaged copy declares the server
  (`https://<server name>/*`, the name from `VEYRA_PUBLIC_HOST` in
  `/etc/veyra/installer.conf`, else `hostname -f`) as a *required* host permission, which
  policy-installed extensions receive without asking; the loose zip keeps it
  optional for hand installs.
* NGINX serves `/downloads/veyra-companion.crx` and the API serves the
  Omaha-style update manifest at `/api/v1/companion/update.xml`, built from
  the request's host name, so managed browsers fetch new versions after
  every Veyra upgrade.
* Settings → *Companion extension deployment* (platform administrators)
  shows the extension ID, the update URL, the install-source pattern and
  the policy JSON, with the Google Admin Console steps: Devices → Chrome →
  Apps & extensions → Users & browsers → add by ID *from a custom URL* →
  **Force install**; under *Policy for extensions* the JSON
  `{"serverUrl": "https://<server>"}` preloads and locks the server
  address (the extension reads `chrome.storage.managed`, schema in
  `managed-schema.json`; `dialPrefix` can be preset too). Users then only
  sign in.
* The account page's *Add to Chrome* button links to the signed package; it
  works when the Admin Console lists the server under *Extension install
  sources* (`ExtensionInstallSources`), otherwise the browser refuses
  off-store installs and the zip steps apply.
* `GET /api/v1/companion/info` (signed-in users) reports what is available.

Publishing to the Chrome Web Store (unlisted) remains an option for a
later milestone; it would make the button work without policy.

## 6. Security notes

* Tokens are hashed at rest like session tokens; the clear value is shown
  to the client once.
* Bearer requests cannot carry a pre-authentication state, so the second
  factor is always complete before a token exists.
* The permission intersection means a token never outgrows its user, and
  a role change takes effect on the next request.
* The event stream only ever sends events for extensions assigned to the
  token's user; administrators get the same filter (platform-wide call
  monitoring is Milestone 10).
* Tickets are single-use and expire in 60 seconds; the WebSocket closes
  when the token is revoked or expires (checked every ping).
* Lockout and the login rate limit apply to the companion flow exactly as
  to the web flow, and the same audit actions are written.

## 7. Testing plan

* Unit: token issue/resolve/expiry/revocation; permission intersection;
  companion login with and without MFA, lockout, enrolment-required;
  preferences validation; directory scoping; ticket lifecycle; event
  normalisation from recorded ARI payloads; WebSocket hello and filtering
  with the test client.
* Live on dev1: software phone registered as 22214, an inbound call from
  the software carrier produces `call.ringing`, `call.answered` and
  `call.ended` on the stream; click-to-dial from the stream's owner
  produces `call.dialing`.
* Extension: unit tests for number normalisation and the event-to-
  notification mapping (vitest); manual load-unpacked check by the owner on
  site (`companion/README.md`).

## 8. Out of scope (later)

Firefox and Safari builds, store publication, presence and BLF, call
control (answer/hang up from the browser), screen pops into other web
applications, SSO sign-in (Milestone 13).
