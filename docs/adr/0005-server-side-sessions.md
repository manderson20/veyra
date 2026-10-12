# 0005: Server-side sessions instead of JWT

**Status:** Accepted

**Context:** A browser admin UI on the same origin as its API needs
revocable sessions. Deactivating a user or changing a password must take
effect immediately.

**Decision:** Opaque random session tokens in HttpOnly, Secure,
SameSite=Strict cookies. Only SHA-256 hashes are stored in `sessions`.
Absolute and idle timeouts apply. CSRF uses a double-submit token whose hash
is bound to the session. API tokens for integrations will be a separate,
scoped mechanism.

**Consequences:** Instant revocation, at the cost of a database lookup per
request (indexed and cheap). HA requires sessions in the replicated
database, which they already are.
