# Multi-factor authentication: design

**Status:** Design accepted for implementation in a later milestone (see
[ADR 0012](adr/0012-mfa-approach.md)). Nothing in this document is
implemented yet; the UI says so on the account page.

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

"Remember this browser" is deliberately **not** offered in the first phase:
it weakens the factor and needs a device-binding design of its own.

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
not hashed. Veyra will use the **installation key** planned for SIP secrets
in Milestone 4 (a 256-bit key in `/etc/veyra/secrets/installation.key`,
mode 0640 root:veyra, generated by the installer and included in backups
separately from the database dump). Encryption is AES-256-GCM with a random
96-bit nonce and the user id as associated data, via the `cryptography`
package already in the dependencies. Recovery codes are hashed with
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

## 10. Out of scope

Hardware OTP tokens (HOTP), push notifications, SMS, email codes, trusted
devices, and step-up authentication for individual actions. Each can be
added behind the same `mfa_methods` table.
