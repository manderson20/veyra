# Integrations (Milestone 13)

Design for Milestone 13 (roadmap row 13, 0.19.0). Integrations connect
Veyra to the systems around it, in three directions:

* **People sign in with the identity they already have**: single sign-on
  through OpenID Connect (Google Workspace first, Microsoft Entra ID and any
  standards-compliant provider), in the web interface **and in the
  Companion extension**. On a managed Chromebook or Chrome profile, the
  Companion can sign in with no clicks at all (owner goal, M6b).
* **Other systems call Veyra**: integration tokens, which are API tokens
  that belong to an organization rather than a person. Examples are a door
  controller that triggers a page when a door stays open (PAGING_RECORDINGS.md
  §2.6) and a script that reads the call history.
* **Veyra tells other systems what happens**: outgoing webhooks with signed
  JSON events, for example a call answered, a voicemail left, a page sent, a
  bell rung or an alert raised.

It also lists ring groups and queues in the Companion directory, which
RING_GROUPS_QUEUES.md §1 promised for this milestone.

## 1. Single sign-on (OpenID Connect)

### 1.1 Providers

An administrator adds an **identity provider** under System → Sign-in:

| Field | Notes |
|---|---|
| Kind | `google`, `microsoft` or `oidc`. The first two are presets that fill the issuer and set the right claims. |
| Name | Shown on the sign-in button ("Sign in with Google"). |
| Issuer | `https://accounts.google.com`, `https://login.microsoftonline.com/<tenant>/v2.0`, or any issuer. Veyra reads `<issuer>/.well-known/openid-configuration`. |
| Client ID / secret | From the provider's console. The secret is stored encrypted with the installation key (purpose `sso:client-secret`) and is never shown again. |
| Allowed domains | E-mail domains accepted from this provider, for example `example.org`. For Google, Veyra also checks the `hd` (hosted domain) claim, so personal Gmail accounts are refused. **Required**: an empty list is not accepted. |
| Organization | Where new accounts land (just-in-time creation, §1.3). |
| Create accounts | Off by default. When on, a person with an allowed domain who has no account yet gets one, with the default role. |
| Default role | The role given to accounts created here, scoped to the organization (default: User). |
| Enabled | The provider stays saved while it is off. |

The redirect URI that the administrator enters in the provider's console is
the same for every provider and is shown in the *Add provider* dialog before
anything is saved: `https://<host>/api/v1/auth/sso/callback` (the state
names the attempt and therefore the provider). `<host>` is
`VEYRA_PUBLIC_HOST` when it is set, otherwise the address the browser used.

Several providers can be enabled at once, each with its own button. SAML is
out of scope: Google and Microsoft both speak OpenID Connect.

### 1.2 Web sign-in flow

This is the authorization code flow with PKCE, `state` and `nonce`.

1. The sign-in page lists the enabled providers. "Sign in with Google" goes
   to `GET /api/v1/auth/sso/<id>/start?next=/…`.
2. Veyra creates a short-lived **SSO request** containing state, nonce, the
   PKCE verifier, the client (`web` or `companion`) and `next`. It is stored
   in the database for 10 minutes, can be used once, and is bound to a
   cookie for the web client. Veyra then redirects to the provider's
   authorization endpoint with `scope=openid email profile`, adding
   `hd=<domain>` for Google when there is a single allowed domain, and
   `login_hint` when it is known.
3. The provider redirects back to `/callback?code&state`. Veyra checks the
   state and the cookie, then exchanges the code at the token endpoint
   (client secret plus PKCE verifier, over HTTPS).
4. Veyra verifies the ID token:
   * the signature against the provider's JWKS (RS256 or ES256, with the
     keys cached and refetched when an unknown `kid` appears);
   * `iss`, `aud` (equal to the client ID, and `azp` when present), `exp`
     and `iat` (with 5 minutes of clock skew), and `nonce`;
   * `email_verified` is true, and the e-mail domain (and `hd` for Google)
     is in the allowed list.
5. Veyra finds the account (§1.3) and creates a normal session. For web
   sign-in this means the same cookies and CSRF as a password sign-in. It
   redirects to `next`, which must be a local path.

Failures send the person back to the sign-in page with a plain message,
such as "This Google account is not allowed to sign in" or "No Veyra account
for this address; ask an administrator". Every success and failure is
audited (`auth.sso.login`, `auth.sso.failed` with the reason, no tokens),
and `/start` has its own sign-in rate limit (the callback needs none: its
state is single-use and unguessable). The callback answers with a small
page that continues to `next`, so the strict session cookie is sent with
the next navigation even though the provider's redirect was cross-site;
the cookie binding the attempt to the browser is `SameSite=Lax` for the
same reason.

### 1.3 Matching accounts

* The **link** is the pair (provider, `sub`), stored in a new
  `user_identities` table. After the first sign-in Veyra matches on `sub`
  only, so a later change of e-mail address at the provider does not break
  sign-in.
* On the first sign-in through a provider, Veyra links an **existing
  account** with the same (verified, allowed-domain) e-mail address. This
  is how current users move to SSO without any administrator work.
* If no account exists and "Create accounts" is on, Veyra creates one:
  `auth_source=<provider kind>`, no password, the display name from the
  `name` claim, home organization and default role from the provider.
  Otherwise sign-in is refused (the default).
* A deactivated account stays deactivated. SSO never re-enables it.
* The **recovery administrator** never signs in through SSO
  (ARCHITECTURE.md): the link is refused for that account.

### 1.4 Password policy with SSO

Installation setting **"Require single sign-on"** (System → Sign-in, off by
default; providers are installation-wide too until multi-tenancy): when it
is on, accounts with an SSO link can no longer sign in with a password (the
password form says "Use Sign in with Google"), and password reset links are
not issued for them. The recovery administrator is always exempt. Accounts
without a link keep their passwords.

An administrator can unlink an identity from a user (Users → user →
Sign-in), for example after a provider change.

### 1.5 MFA

MFA_DESIGN.md §8 applies: a session created through SSO counts as fully
verified (`mfa_verified_at` is set), and the provider's own MFA applies.
Veyra's MFA policy keeps applying to password sign-ins. If the provider
reports `amr`, it is stored in the session for the audit log.

### 1.6 Companion sign-in through SSO

The Companion extension (COMPANION.md) signs in today with an e-mail
address, a password and the MFA code. M13 adds "Sign in with Google" there
as well:

1. The extension calls `chrome.identity.launchWebAuthFlow` with
   `https://<host>/api/v1/auth/sso/<id>/start?client=companion&redirect_uri=https://<extension id>.chromiumapp.org/sso&code_challenge=…`.
   The extension ID must be the ID of the extension Veyra packages and signs
   (COMPANION.md §5); any other redirect is refused.
2. After the provider step (§1.2), Veyra does not create a cookie session.
   It redirects to `https://<extension id>.chromiumapp.org/sso?code=<one-time code>`.
   The code is valid for 60 seconds, can be used once, and is bound to the
   extension's own PKCE challenge.
3. The extension posts the code and its verifier to
   `POST /api/v1/auth/companion/sso` and receives a normal Companion token
   (ADR 0015: same scopes, same expiry, listed under Connected apps).

**No clicks:** with the policy key `ssoProvider` (managed storage, set in the
Google Admin console alongside `serverUrl`), the extension first tries the
flow silently (`interactive: false`, which adds `prompt=none`), at start-up
and at most once an hour while signed out. The extension needs only the
`identity` permission, which shows no warning; it does not read the
profile's address (`identity.email` would add a warning), so Google uses
the account the browser is signed in to. On a managed Chromebook, where
the person is already signed in to Google, the extension then signs in by
itself on first start, listed as "Managed browser" under Connected apps. If the provider needs interaction (first
consent, or a different account), the silent attempt fails quietly and the
popup shows the "Sign in with Google" button.

For the silent flow to work without a consent screen, the Workspace
administrator marks the Veyra OAuth client as **trusted** in the Admin
console (Security → API controls → App access control). INSTALLATION.md
gets the steps.

### 1.7 What is stored

`identity_providers` (configuration, encrypted secret, discovery cache),
`user_identities` (provider, subject, e-mail at link time, last used), and
`sso_requests` (state, nonce, verifier, client, redirect, expiry, used).
The worker removes expired requests. Provider access and refresh tokens are
**not** kept: Veyra only needs the identity, once.

## 2. Integration tokens

### 2.1 The object

An **integration** belongs to an organization, not to a person:

| Field | Notes |
|---|---|
| Name | "Door controller, main entrance" |
| Scopes | Chosen from a fixed list (§2.2). |
| Allowed addresses | Optional list of addresses or networks (CIDR). When set, the token is refused from anywhere else. |
| Expires | Never (default) or a date. |
| Token | `vyi_` plus 32 random bytes, shown **once** when created or rotated; only its SHA-256 digest is stored. |
| Last used | Time and address. |

Internally an integration is a **service account**: a `users` row with
`auth_source=integration`, no password and no way to sign in, holding one
role assignment in the organization with the chosen permissions, and one
`api_tokens` row (`kind=integration`, prefix `vyi_`, no idle expiry). This
reuses the existing bearer-token path (ADR 0015, `current_principal`), so
the permission checks are the same as for everything else, and the audit
log shows the integration's name as the actor. Service accounts are hidden
from Users, cannot be given roles there, and do not count as people
anywhere (directory, reports).

### 2.2 Scopes

| Scope | Allows |
|---|---|
| `paging.send` | `POST /pages/{id}/send` (the door-alert case) |
| `calls.read` | Active calls |
| `calls.originate` | Click-to-dial for a given extension |
| `calls.history.read` | The call history |
| `calls.history.export` | The call history as CSV |
| `directory.read` | The directory (extensions, ring groups, queues) |
| `reports.read` | Saved reports and their results |
| `bells.write` | Ring a bell schedule now |

Administrative scopes (users, trunks, deployments) are deliberately not
offered: an integration that can change the system is a person's job.

### 2.3 Use

```
curl -X POST https://<host>/api/v1/pages/<page id>/send \
     -H "Authorization: Bearer vyi_…"
```

Rotation creates a new token and invalidates the old one immediately.
Deleting an integration removes its service account and token. Every use
updates "last used" (at most once a minute), and failures are rate-limited
like sign-ins.

## 3. Outgoing webhooks

### 3.1 The object

| Field | Notes |
|---|---|
| Name | "Front office screen pop" |
| URL | HTTPS by default. Plain HTTP only when "Allow unencrypted HTTP" is ticked, which is meant for devices on the local network. |
| Events | Chosen from the catalog (§3.2), with a wildcard per group (`call.*`). |
| Secret | Generated, shown once, rotatable; used to sign every delivery (§3.4). Stored encrypted (purpose `webhooks:secret`). |
| Enabled | Turned off automatically after 3 days of continuous failure, with an alert. |

Webhooks belong to an organization and see only that organization's events.

### 3.2 Event catalog

| Event | When | Payload (besides the envelope) |
|---|---|---|
| `call.ringing` | An extension starts ringing | extension number and name, caller number and name, call id |
| `call.answered` | An extension answers | as above |
| `call.ended` | A call record is written (from the call history import) | direction, from, to, extension(s), DID, trunk, queue/ring group, started, answered, ended, ring and talk seconds, outcome |
| `voicemail.message` | A new voicemail message is left | box number and name, new, old and urgent message counts (from Asterisk's `externnotify`), and since 0.27.24 `message`: the newest message's `msg_id`, `caller_number`, `caller_name`, `received_at`, `duration_seconds`, `urgent` (read through the voicemail store helper; left out when it is not running; never the audio) |
| `page.sent` | Veyra starts a recorded page | page name and number, zones, recording, how it was started (`ui`, `api`, `bell`) and by whom; pages dialled from a phone are not reported |
| `bell.rang` | A bell schedule rings | schedule, calendar event title, page |
| `alert.raised` / `alert.resolved` | A monitoring alert changes state (M10) | rule, title, subject, message, details |
| `registration.changed` | A phone registers or unregisters | extension, registered, `address` (where the registration came from, public behind NAT), `contact_address` (the phone's own), `nat`, user agent (M18, [CALL_FEATURES.md](CALL_FEATURES.md) §2.1) |
| `deployment.finished` | A configuration deployment ends | revision, result |
| `webhook.test` | "Send test" on the page | none |

Alerts and deployments belong to the installation, not an organization:
every organization with a webhook subscribed to them gets the event.
Modules can declare more events in their manifest (`events.publishes`,
M11). An administrator can subscribe to them once the module is enabled;
the event goes to the organization named by `organization_id` in its
payload, or to every subscribed organization without one.

### 3.3 Envelope

```json
{
  "id": "6b1e…",              // delivery id, unique, stable across retries
  "event": "call.answered",
  "occurred_at": "2026-10-15T14:43:39Z",
  "organization": {"id": "…", "slug": "…"},
  "data": { … }
}
```

Times are UTC (ISO 8601). Numbers are E.164 when Veyra knows them,
otherwise as dialled.

### 3.4 Signature

Each request carries:

```
Content-Type: application/json
User-Agent: Veyra-Webhooks/0.19.0
Veyra-Event: call.answered
Veyra-Delivery: 6b1e…
Veyra-Signature: t=1792161819,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>
```

Receivers check the HMAC and reject a `t` older than 5 minutes. During a
secret rotation, deliveries carry two `v1=` values (old and new secret) for
24 hours. The documentation includes a 10-line Python and Node example.

### 3.5 Delivery

* Publishing never waits on the network. The process that sees the event
  (API for the live call events, worker for call records, bells, alerts and
  voicemail) writes one **delivery** row per matching webhook in the same
  database (an outbox). The worker sends them.
* Each attempt has a 10-second timeout. Any 2xx is success. Redirects are
  not followed.
* Retries come after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours,
  then the delivery is `failed`. Live call events (`call.ringing`,
  `call.answered`) are only useful for a few seconds, so they get no
  retries.
* Order is kept per webhook on a best-effort basis; receivers deduplicate
  on `id`.
* Delivery history is kept for 7 days, and the last 100 deliveries per
  webhook (status, code, duration, error, payload) are visible, with
  "Redeliver".

### 3.6 Safety

Webhook URLs come from administrators, but the requests come from the
server, so Veyra refuses destinations that would reach inside the server
itself:

* loopback, link-local (including `169.254.169.254`), multicast,
  unspecified and reserved addresses, and the addresses the server's own
  name resolves to, are refused, after DNS resolution, for every attempt
  (the resolved address is pinned for the connection, so DNS rebinding
  does not help). This protects what listens on loopback only (the API,
  PostgreSQL, ARI); the server's LAN address is treated like any host on
  the network, because what listens there is reachable from it anyway;
* private networks (RFC 1918, ULA) **are allowed**, because local door
  controllers and screens are the point;
* the response body is read up to 4 KB, only for the delivery log;
* the URL (with its query) and the secret are never written to the log
  files.

### 3.8 Automation rules (issue #117, 0.27.27)

"When X happens, do Y", per organization: **System → Automation**.

* **When**: an event of the webhook catalogue (§3.2: `call.ended`,
  `voicemail.message`, `alert.raised`…), or **a request to the rule's own
  address** (`hook`): `POST /api/v1/automation/hooks/<token>` with an
  optional JSON body, for devices that can only call a URL (a door
  controller, a fire panel, a script). The token (32 random bytes, stored
  as SHA-256) is shown once and can be replaced ("New address").
* **Only if**: conditions on the event's fields (dotted paths such as
  `from.number`; *is* or *contains*, case-insensitive); all must hold.
* **Then**: email addresses (the event's fields in the body, through the
  mail queue) and/or start a recorded page (the page's recording or
  another). A page action needs `paging.send` of the rule's author.
* **Quiet time** (cooldown, default 60 s): after firing, the rule waits.
  Events caused by a rule's own actions (its page's `page.sent`) never fire
  rules, so rules cannot loop.
* **How it runs**: `webhooks.emit` (and `emit_all` for alerts) queue an
  `automation_runs` row in the emitter's transaction when a rule matches;
  the worker runs pending runs on its short tick (`automation.process`) and
  records each action's result; runs are kept 30 days. Tables
  `automation_rules`, `automation_runs` (migration `0066`).
* **API** (`webhooks.read` / `webhooks.write`, audited `automation.*`):
  `GET /automation/triggers`, `GET/POST /automation/rules`,
  `PATCH/DELETE /automation/rules/{id}`, `POST …/{id}/rotate-hook`,
  `POST …/{id}/test` (runs the actions with test data), `GET …/{id}/runs`.
* Not yet: actions that call a phone or post a webhook, conditions with
  numbers (greater/less), schedules ("only during school hours").

## 4. Directory

`GET /directory` (the Companion directory, `directory.read`) also lists
**ring groups and queues** (number, name, kind), and the Companion shows
them with a small badge. The phone directory for provisioned phones stays
out of scope (open question §9).

## 5. Permissions and API

New permission keys: `sso.read` and `sso.write` (identity providers,
installation-wide administrators), `integrations.read` and
`integrations.write` (organization), `webhooks.read` and `webhooks.write`
(organization). Platform administrators hold all of them; the Organization
Administrator role gets the integration and webhook keys.

```
GET  /auth/sso/providers                     public: enabled providers for the sign-in page
GET  /auth/sso/{id}/start                    begins the flow (web or companion)
GET  /auth/sso/callback                      provider redirect (one address for all)
POST /auth/companion/sso                     one-time code + verifier -> Companion token

GET/POST          /identity-providers
GET/PUT/DELETE    /identity-providers/{id}
GET               /identity-providers/redirect-uri   the address for the provider's console
GET/PUT           /identity-providers/policy         require_sso
POST              /identity-providers/{id}/test      discovery + JWKS reachable
GET/DELETE        /users/{id}/identities[/{identity id}]

GET/POST          /integrations
GET               /integrations/scopes
GET/PUT/DELETE    /integrations/{id}
POST              /integrations/{id}/rotate          returns the new token once

GET/POST          /webhooks
GET/PUT/DELETE    /webhooks/{id}
POST              /webhooks/{id}/test
POST              /webhooks/{id}/rotate-secret
GET               /webhooks/{id}/deliveries
POST              /webhooks/{id}/deliveries/{delivery id}/redeliver
GET               /webhooks/events                    the catalog, including module events
```

## 6. Interface

* **Sign-in page**: one button per enabled provider above the password
  form, and the provider's or Veyra's reason when a sign-in is refused.
* **System → Sign-in** (new): the providers with the redirect URI to copy,
  a "Test" button, the "Require single sign-on" policy and the setup steps
  for Google and Microsoft.
* **Users → user**: a "Sign-in" card with linked identities and "Unlink".
* **System → Integrations** (new page): two tabs.
  * **Tokens**: list (name, scopes, last used, expires), create dialog with
    scopes and allowed addresses, token shown once with a copy button and a
    curl example.
  * **Webhooks**: list (name, URL host, events, last delivery status), edit
    dialog with event checkboxes grouped as in §3.2, the secret shown once,
    "Send test", and a deliveries drawer with redeliver.
* **Companion**: "Sign in with Google" in the popup, and silent sign-in when
  managed storage sets `ssoProvider`. The Companion deployment card
  (Settings) shows the new policy key.

## 7. Installer

Nothing new to install: the OIDC client uses `httpx` and the ID token check
uses `cryptography`, which are both already in requirements. No new
services, ports or units. NGINX already proxies `/api/`.

## 8. Testing

* **Unit**: ID token verification (RS256 and ES256 against generated keys:
  good token; wrong `aud`, `iss`, `nonce`, expiry, `kid`, algorithm `none`
  and HS256 confusion, wrong `hd`, unverified e-mail); the PKCE pair;
  webhook signing; SSRF rules (loopback, link-local, private allowed,
  rebinding pinned); retry schedule.
* **API**: a fake OpenID provider in the test suite (discovery, JWKS,
  token endpoint, through an `httpx` mock transport). Covered: the full
  web flow (link existing account, refused unknown, JIT creation with
  role, deactivated user, recovery admin refused, replayed state, open
  redirect in `next`); the Companion flow (wrong redirect, replayed or
  expired code, wrong verifier); "Require SSO" blocking passwords and
  resets; integration tokens (scopes, allowed addresses, rotation, audit
  actor, no administrative routes); webhooks (CRUD, outbox from events,
  delivery with signature against a local receiver, retries, auto-disable,
  redeliver).
* **Frontend**: the provider form and the token-shown-once dialog
  (vitest).
* **Live on dev1**: a webhook to a local receiver for call, page and bell
  events; an integration token sending a page; SSO against a local test
  provider. A real Google sign-in needs a Google Cloud OAuth client from
  the owner (open question §9), and silent Companion sign-in needs a
  managed Chrome profile, so both are owner checks.

## 9. Open questions for the owner

1. **Google OAuth client**: will you create the OAuth client in your Google
   Cloud console (Web application, redirect URI from System → Sign-in), or
   should the documentation walk you through it at the time? Nothing is
   committed to the repository either way.
2. **Account creation**: should people with a district address who have no
   Veyra account be created automatically on first sign-in (with the User
   role), or only existing accounts may sign in (proposed default)?
3. **Require SSO**: turn it on for your organization once Google sign-in
   works, so staff cannot use passwords any more?
4. **Phone directory**: do you want Veyra to publish a directory to the
   Poly/Yealink phones (extensions, groups and shared external contacts
   such as the district office)? It fits provisioning better than this
   milestone; proposed as a follow-up.

## 10. Out of scope

SAML, SCIM and directory sync (Google Workspace user import; JIT creation
covers the need for now), group-to-role mapping from provider claims, OAuth
for third-party apps ("Sign in with Veyra"), incoming webhooks in other
formats (integrations use the normal API with a token), CRM connectors and
screen pops into other applications, and Microsoft Teams or Slack
notifications (a webhook covers them for now).
