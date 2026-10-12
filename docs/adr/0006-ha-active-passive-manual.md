# 0006: Active/passive HA with manual failover first

**Status:** Accepted

**Context:** The two-node requirement brings split-brain risk. The
development VMs share one physical host. Calls in progress cannot be
migrated with Asterisk.

**Decision:** Active/passive pairs with PostgreSQL streaming replication,
Asterisk running only on the primary, a floating service IP, roles stored as
data, and manual, audited switchover. Automatic failover stays disabled
until fencing (for example the Proxmox API) and quorum (a witness) are
implemented and pass the test plan in
[HA_ARCHITECTURE.md](../HA_ARCHITECTURE.md).

**Consequences:** Predictable, safe behaviour with operator-driven recovery.
RTO includes human response time until automatic failover is approved.
