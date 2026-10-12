# 0008: Synchronous SQLAlchemy with psycopg 3 and peer authentication

**Status:** Accepted

**Context:** The API's workload is mostly small transactional queries.
Async database stacks add complexity, and the database password would be a
secret to manage.

**Decision:** Use SQLAlchemy 2.x in synchronous mode with psycopg 3.
FastAPI runs sync dependencies in a thread pool. The service connects over
the local Unix socket with PostgreSQL peer authentication (OS user `veyra` →
role `veyra`), so no password exists.

**Consequences:** Simpler code and fewer secrets. Very high concurrency
would need more workers or a later move to async. HA replication will use a
separate replication role with its own credential.
