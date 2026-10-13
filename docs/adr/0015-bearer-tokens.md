# 0015: Scoped bearer tokens for companion clients

**Status:** Accepted (2026-10-13).

**Context:** The Veyra Companion browser extension (Milestone 6b) must call
the API from a context that is not the web interface's origin. The web
interface uses server-side sessions in HttpOnly cookies with a double-submit
CSRF token and a `Sec-Fetch-Site` check ([ADR 0005](0005-server-side-sessions.md)).
Browser extensions handle cookies for a foreign origin poorly (cookie jars
differ between the extension and the site, `SameSite=Strict` cookies are not
sent, and the fetch-metadata check would have to be relaxed for cookie-bearing
requests, which weakens the protection the check exists for). Options
considered: relaxing the cookie model for extension origins; OAuth 2 with
PKCE against Veyra as an authorization server (correct in principle, but a
whole subsystem for one first-party client); and scoped bearer tokens issued
by a cookie-less login flow that reuses the existing password, lockout, rate
limit and second-factor logic.

**Decision:** Scoped bearer tokens. `POST /auth/companion/login` and
`/verify` run the same checks as the web login and, once the second factor
is complete, issue an opaque token (`vyc_` prefix, 32 random bytes) whose
SHA-256 digest is stored in `api_tokens` with the issuing device label,
addresses, timestamps and a fixed list of permission keys (the *scope*).
A request with `Authorization: Bearer` is authenticated by the token alone:
cookies are ignored, the CSRF and fetch-metadata checks do not apply, and
the principal's permissions are the intersection of the user's grants and
the token's scope. Tokens expire 30 days after their last use and 180 days
after creation (configurable), can be revoked by the user (account page) and
by administrators, and die with the user account. The same table and
resolution path will serve integration tokens later with different scopes.

**Consequences:** One more credential type to audit, list and revoke, with
its own retention. The permission model gains a scope layer on `Principal`,
which every permission check already goes through. Bearer requests are not
protected by the fetch-metadata check, which is acceptable because a bearer
token is never attached automatically by the browser. OAuth 2 remains the
path for third-party clients if they ever appear; this ADR does not
preclude it.
