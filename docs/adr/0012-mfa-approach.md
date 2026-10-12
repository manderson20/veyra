# 0012: Multi-factor authentication with TOTP first, passkeys second

**Status:** Accepted design (2026-10-12); implementation scheduled on the
roadmap, not in Milestone 2.

**Context:** Administrative access to a telephony platform must be able to
require a second factor, and the server may have no internet, phone or
email access. See [MFA_DESIGN.md](../MFA_DESIGN.md) for the full design.

**Decision:** TOTP (RFC 6238) with single-use recovery codes is the first
factor type; WebAuthn passkeys follow once trusted TLS is routine. A second
factor is verified once at sign-in through a short-lived pre-authentication
session that can reach only the MFA routes; the resulting session is an
ordinary one. TOTP secrets are encrypted at rest with the installation key;
recovery codes are hashed. Policy is per role with an enrolment grace
window; the recovery administrator is not exempt and is reset from the
server console. No SMS, email codes or "remember this browser".

**Consequences:** No external service is needed. Users need an
authenticator app. The installation key becomes a critical secret that
backups must include separately from the database. The pre-auth session
reuses the route restriction introduced for forced password changes, so the
session model does not change.
