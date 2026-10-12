# 0003: Database-authoritative configuration and a separate deployer

**Status:** Accepted

**Context:** Hand-edited files drift. Writing engine files from HTTP request
handlers is risky: it requires privileges, can interrupt calls and cannot be
rolled back. Telephone service must also survive the web application being
down.

**Decision:** The database is the source of truth. Requests create draft
`config_revisions`. A separate deployer service generates files through the
adapter, validates and diffs them, writes them atomically to
`/etc/asterisk/veyra/`, performs targeted reloads, verifies the result and
records the outcome, restoring the previous files on failure. Asterisk reads
only static files, not Realtime, at call time.

**Consequences:** Rollback and audit are straightforward. Asterisk keeps
working when Veyra or PostgreSQL are down, and HA promotion simply
regenerates configuration. Changes take effect after deployment rather than
instantly. Implementation is in M3.
