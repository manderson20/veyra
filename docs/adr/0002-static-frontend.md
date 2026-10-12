# 0002: Static Next.js export served by NGINX

**Status:** Accepted

**Context:** The admin UI must be modern (Next.js, React, TypeScript), but
every extra long-running service adds attack surface, memory use and HA
complexity.

**Decision:** Build the UI with `output: "export"` into static files served
by NGINX. All data comes from the same-origin `/api/v1`. Node.js is needed
only to build the UI, never at runtime. Routes use query parameters instead
of dynamic segments.

**Consequences:** No Node.js process in production, and the UI is served
even while the API restarts. Server-side rendering and Next.js middleware
are unavailable, so authorization is enforced entirely by the API, as it
must be anyway. The CSP currently needs `'unsafe-inline'` for scripts
because of inlined bootstrap scripts.
