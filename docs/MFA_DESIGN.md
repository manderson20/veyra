# Multi-factor authentication: design

**Status:** Implemented in Milestone 4b (version 0.5.0) as designed, with
the implementation notes in §11 ([ADR 0012](adr/0012-mfa-approach.md)).
Passkeys (§2) remain scheduled for Milestone 17.

## 1. Goals

* A second factor for local accounts that works without any cloud service,
  phone network or email, because a Veyra server may be on an isolated
  network.
* Administrators can be required to use it; other users may be allowed or
  required per role.
* Recovery that never needs Veyra support: recovery codes for the user, and
  a server-console command for the administrator of last resort.
* No change to the session model ([ADR 0005](adr/0005-server-side-sessions.md)):
  a second factor is checked once at sign-in and the resulting session is an
  ordinary session.

## 2. Factors

| Factor | Phase | Why |
|---|---|---|
| **TOTP** (RFC 6238, 30 s period, 6 digits, SHA-1 for app compatibility) | first | Works offline with every authenticator app; nothing to buy. |
| **Recovery codes** (10 single-use codes, 10 characters from a 32-symbol alphabet) | first | Lets a user who lost their phone get back in without an administrator. |
| **Passkeys / WebAuthn** (platform and roaming authenticators) | second | Phishing-resistant; needs a stable HTTPS origin, which the installer's self-signed certificate does not give every browser. Delivered once TLS from a trusted CA is routine (Milestone 17). |

SMS and email codes are not planned: SMS is not available on isolated
networks and is weak; email codes would only be as strong as the mailbox.

## 3. Data model (migration in the implementing milestone)

```
mfa_methods
  id uuid pk
  user_id -> users (cascade)
  type           'totp' | 'webauthn'
  label          text              e.g. "Phone", "YubiKey 5"
  secret_ciphertext bytea          TOTP secret, encrypted (see §6)
  credential     jsonb             WebAuthn credential id, public key, sign count, transports
  created_at, last_used_at, confirmed_at (NULL until the first successful code)

mfa_recovery_codes
  id uuid pk
  user_id -> users (cascade)
  code_hash      text              Argon2id, like passwords
  used_at        timestamptz null

users (new columns)
  mfa_required_at   timestamptz null   set when policy starts requiring MFA for this user
  mfa_grace_until   timestamptz null   sign-ins allowed without MFA until then (enrolment window)

sessions (new column)
  mfa_verified_at   timestamptz null   NULL for the short-lived pre-auth session (§4)
```

The audit log records enrolment, removal, verification failures, recovery
code use and administrator resets; the secret and codes never appear in
details (the existing redaction covers `secret`, `code`, `token`).

## 4. Sign-in flow

1. `POST /auth/login` checks the password exactly as today. If the user has
   a confirmed factor (or MFA is required and not yet enrolled), the
   response is `202 {"mfa_required": true, "methods": ["totp"], "enrol": false}`
   and a **pre-authentication session** cookie is set: an ordinary row in
   `sessions` with `mfa_verified_at = NULL` and a 5-minute expiry. The
   principal dependency refuses every route except `/auth/mfa/*` and
   `/auth/logout` while `mfa_verified_at` is NULL (same mechanism as the
   forced password change delivered in Milestone 2).
2. `POST /auth/mfa/verify {method_id?, code}` checks a TOTP code (accepting
   one step of clock drift either way and rejecting a code that was already
   used in its window) or a recovery code. Success sets `mfa_verified_at`,
   extends the session to the normal lifetime, rotates the CSRF token and
   returns the usual session document. Five failures lock the pre-auth
   session; the per-IP limiter and account lockout apply as for passwords.
3. When MFA is required but nothing is enrolled, step 1 returns
   `enrol: true` and the UI runs enrolment (§5) inside the pre-auth session.
   `mfa_grace_until` lets an administrator give existing users a window
   during which sign-in without MFA still works and the UI nags.

"Remember this browser" was left out of the first phase because it weakens
the factor. *Built 0.27.8 (#137, migration `0059`), off by default:* policy
`trusted_browser_days` (0–90; 0 = off). After a successful code the user may
tick "Trust this browser"; Veyra sets the `__Host-veyra_trusted` cookie
(random token, HttpOnly, Secure, SameSite=Strict, the policy's lifetime) and
stores only its digest in `trusted_browsers` (at most 20 per user). At
sign-in a live token of the same user skips the code (audit `mfa:
trusted_browser`). `revoke_user_sessions` — password change and reset,
second-factor reset, "sign out of other sessions" — forgets them all; the
Account page lists and forgets them (`GET/DELETE /auth/trusted-browsers[/{id}]`).
The cookie is not bound to the device beyond the browser's cookie store.

## 5. Enrolment and management (account page)

* `POST /auth/mfa/totp/begin` returns a provisioning URI
  (`otpauth://totp/Veyra:<email>?secret=…&issuer=Veyra`) and an SVG QR code
  rendered server-side (no third-party image service). The secret is stored
  unconfirmed.
* `POST /auth/mfa/totp/confirm {code}` confirms it, generates the recovery
  codes and returns them **once**. The UI shows them with a download and a
  "I have saved these" confirmation before the method becomes active.
* `DELETE /auth/mfa/methods/{id}` removes a method; the current password is
  required again (re-authentication), and removal of the last method is
  refused while policy requires MFA for the user.
* `POST /auth/mfa/recovery-codes/regenerate` replaces the codes (password
  required).
* Administrators: `POST /users/{id}/mfa/reset` removes all factors so the
  user enrols again at the next sign-in (audited, users.write, with the
  platform-administrator guard). Server console: `veyra users mfa-reset
  <email>` for the recovery administrator.

## 6. Secret storage

TOTP secrets must be readable by the server, so they are encrypted at rest,
not hashed. Veyra uses the **installation key** introduced for SIP secrets
in Milestone 4 (`veyra.core.security.crypto`, [ADR 0014](adr/0014-installation-key.md):
a 256-bit key in `/etc/veyra/secrets/installation.key`, mode 0640
root:veyra, generated by the installer and backed up with `/etc/veyra`,
separately from the database dump). Encryption is AES-256-GCM with a random
96-bit nonce and the purpose string `user.totp_secret:<user id>` as
associated data. Recovery codes are hashed with
Argon2id like passwords, because they are only ever compared.

## 7. Policy

System setting `security.mfa` (platform administrators only):

```json
{"required_for": ["platform_admin", "org_admin"], "grace_days": 14, "allowed_methods": ["totp"]}
```

Requirement is evaluated from role assignments at sign-in. Changing the
policy sets `mfa_required_at` and `mfa_grace_until` on the affected users
and audits the change. The recovery administrator is **not** exempt; the
console command is the escape hatch, and using it is audited.

## 8. Interaction with SSO (later milestone)

Users whose `auth_source` is an external identity provider rely on that
provider's MFA; Veyra does not stack a second factor on top. The local
recovery administrator always uses local MFA.

## 9. Testing plan

Unit: TOTP vector tests from RFC 6238 Appendix B; drift window; replay
rejection; recovery code single use; encryption round trip and tamper
detection. API: pre-auth session cannot reach other routes; verify success
upgrades the session; lockout after failures; policy grace window; admin
reset; audit events. UI: enrolment with a real authenticator app on a
phone (manual, recorded in the milestone report).

## 10. Out of scope (unchanged)

Hardware OTP tokens (HOTP), push notifications, SMS and email codes. Each
can be added behind the same `mfa_methods` table. (Trusted browsers since
0.27.8, §4; step-up authentication since 0.27.15, below.)

*Step-up authentication, built 0.27.15 (#137, migration `0064`):* the
`recent_auth` dependency (`core/deps.py`) refuses with `403
reauth_required` when the session's last password entry (sign-in, code step
or `sessions.reauth_at`) is older than 15 minutes. `POST /auth/reauth`
`{password, code?}` sets `reauth_at` (the code is required when the account
has a second factor; rate limited, audited `auth.reauth`). Guarded: role
grants, password reset links, setting another user's password, second-factor
resets, the two-factor and single-sign-on policies, update approval,
integration create and rotate, HA enable, switchover, failover, resume and
node removal. Bearer tokens (whose scopes exclude these) and single-sign-on
accounts without a password are not asked. The web client shows a "Confirm it
is you" dialog on `reauth_required` and sends the request again.

## 11. Implementation notes (Milestone 4b)

* Code: `veyra/core/security/totp.py` (RFC 6238 with the standard library),
  `veyra/core/security/mfa.py` (policy, recovery codes, enrolment windows),
  `veyra/api/v1/auth_mfa.py` (routes), migration `0004`.
* Columns differ slightly from §3: `secret_ciphertext` is `text` (the
  installation-key token format), `mfa_methods.last_used_step` records the
  last accepted TOTP step for replay protection, and `sessions.mfa_failures`
  counts wrong codes (five lock the pre-auth session, which is revoked).
  Existing sessions were backfilled with `mfa_verified_at = created_at`.
* The pre-auth session can reach an explicit allow-list
  (`veyra.core.deps.PRE_AUTH_ALLOWED_PATHS`): challenge, verify, TOTP
  begin/confirm (the last two only while no factor is enrolled) and logout.
  `GET /auth/session` answers `403 mfa_required`, which the UI treats as
  "not signed in" and sends to the sign-in page, where the second step is
  resumed from `GET /auth/mfa/challenge`.
* Recovery codes may be entered with or without the dash and in any case.
  Entering a code that is not six digits is tried as a recovery code.
* The QR code is rendered server-side with `segno` as an SVG data URI; the
  device label can be set when confirming.
* Policy defaults: required for Platform Administrators and Organization
  Administrators, 14 days of grace, TOTP only. The first administrator's
  grace window starts at setup. Saving the policy re-evaluates every
  active local user (starts or clears their window) and is audited
  (`security.mfa_policy_update`).
* Audit actions: `auth.mfa_enrol_begin`, `auth.mfa_enrol_confirm`,
  `auth.mfa_verify` (with `method` and `recovery_codes_remaining`, or
  `failures`/`locked`), `auth.mfa_method_remove`,
  `auth.mfa_recovery_codes_regenerate`, `user.mfa_reset`; `auth.login`
  carries `mfa: none|grace|pending|enrol`.
* NGINX rate-limits `/api/v1/auth/mfa/verify` like sign-in; the API's
  per-address limiter is shared with sign-in.
