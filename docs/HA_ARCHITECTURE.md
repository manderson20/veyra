# High Availability Architecture

**Status:** Architecture (Milestone 0). The Milestone 16 build design is
[HIGH_AVAILABILITY.md](HIGH_AVAILABILITY.md); this document keeps the goals,
non-goals, recovery targets and the test plan.
Automatic failover is **disabled** and stays disabled until the fencing and
quorum mechanisms described here have been implemented and pass the test
plan below.

## 1. Goals and non-goals

Goals:

* Two full Veyra nodes in an **active/passive** pair.
* HA is **optional**. A standalone node can be converted to a primary without rebuilding its configuration.
* Roles are **dynamic data** (`cluster_nodes.role`) and never derived from hostnames. `veyra-dev1` starts as primary and `veyra-dev2` as secondary, but either can hold either role.
* Controlled, audited **manual switchover** first.
* No third full Veyra server. An optional lightweight **witness** may be added later.

Non-goals and things we will not claim:

* **Calls in progress do not survive a failover.** Asterisk keeps media and dialog state in memory. Moving an IP address does not move calls. Phones and trunks must re-register, and new calls work once they do.
* **No zero-downtime claim** unless it is measured.
* **Proxmox HA is not application HA.** It restarts a VM after a host failure but knows nothing about PostgreSQL roles, replication lag or split brain.
* **PostgreSQL replication alone is not application HA.** Asterisk configuration, secrets, voicemail, recordings and SIP registrations also have to move.

## 2. Development environment caveat

`veyra-dev1` and `veyra-dev2` are VMs on **the same physical Proxmox host**.
This environment tests application-level HA: process, VM and network
failures between VMs. It **does not protect against failure of the physical
host** and must never be described as if it did.

## 3. Topology

```
            phones / trunks / browsers
                       │
              floating service IP  (held only by the primary)
              ┌────────┴─────────┐
        ┌─────▼──────┐     ┌─────▼──────┐
        │  node A    │     │  node B    │
        │ PRIMARY    │     │ SECONDARY  │
        │ nginx, api │     │ nginx(ro), │
        │ worker     │     │ api(ro)    │
        │ asterisk ● │     │ asterisk ○ │  ● running  ○ stopped (cold standby)
        │ PostgreSQL │────►│ PostgreSQL │  streaming replication (async or sync, §5)
        │  (primary) │     │  (standby) │
        └────────────┘     └────────────┘
                 ╲             ╱
                  ╲  witness  ╱   optional lightweight quorum/fencing arbiter (later)
```

* **Floating IP:** keepalived (VRRP) or a Veyra-controlled `ip addr` move, with gratuitous ARP. VRRP priorities are set by Veyra from the node roles. keepalived is never allowed to decide on its own while automatic failover is disabled (`nopreempt`, manual mode).
* **Asterisk** runs only on the primary. On the secondary it is installed and configured but stopped, which avoids both nodes registering to carriers at once.
* **Web/API on the secondary** is read-only: it shows status and supports switchover. Writes require the primary database.

## 4. What is replicated, and how

| Data | Mechanism | Notes |
|---|---|---|
| Veyra database (configuration, users, audit, CDR) | PostgreSQL streaming replication (physical) | `pg_is_in_recovery()` tells each node its database role; already reported by `/api/v1/ha/status`. |
| Generated Asterisk configuration | Regenerated from the database on the new primary at promotion | The database is authoritative, so no file sync is needed. |
| `/etc/veyra` secrets (ARI password, installation key, TLS) | Enrollment copies them once over SSH, and they are re-synced on change | Must be identical on both nodes. |
| Voicemail, recordings, prompts (`/var/lib/veyra`) | rsync on a short interval (simple) or shared storage | Data written in the last interval can be lost (counts against RPO). |
| SIP registrations | Not replicated | Phones re-register to the service IP after failover (registration expiry ≤ 300 s by default in templates; lower for faster recovery). |

## 5. Recovery objectives (targets, to be measured in M16)

| Scenario | RTO target | RPO target |
|---|---|---|
| Planned switchover | ≤ 2 minutes until new calls work; calls in progress drop | 0 (switchover waits for replication to catch up) |
| Unplanned primary failure, manual failover | Operator response time + ≤ 2 minutes | Async replication: seconds of database writes; file sync interval for voicemail/recordings |
| Secondary failure | No service impact | Not applicable |

Synchronous replication (`synchronous_commit = remote_apply`) gives RPO 0 for
database writes but makes the primary depend on the secondary. If the
secondary is down, writes block unless the configuration falls back to
async. M16 will evaluate both and document the chosen default. These
numbers are targets until they are measured.

## 6. Split-brain prevention and fencing

Split brain means two nodes both believe they are primary: two databases
accept writes, and two Asterisk instances register to the same trunks.
Prevention rules:

1. **Single writer:** promotion is only allowed after the old primary is confirmed *fenced*: powered off through the Proxmox API (a VM-level fence), or confirmed not running PostgreSQL and Asterisk and not holding the service IP.
2. **Quorum for automatic decisions:** automatic failover needs a majority of three voters, which means a witness. Two nodes alone can never decide automatically. A small witness service (or a Proxmox-API-based arbiter) is planned and does not require a third full Veyra server.
3. **Generation number / epoch:** every promotion increments a cluster epoch stored on both nodes and the witness. A node that comes back with an older epoch demotes itself and rejoins as a standby (rebuilt with `pg_rewind` or a fresh base backup).
4. **Manual failover safeguards:** the UI and CLI require the operator to confirm that the old primary is down or fenced, show replication lag, and record everything in `cluster_events` and the audit log.

## 7. Health monitoring and failure detection

* Each node writes a heartbeat (`cluster_nodes.last_heartbeat_at`) through the worker. This exists in M0; a stale heartbeat shows the node as `unknown`.
* M16 adds peer checks over a dedicated path: PostgreSQL replication state (`pg_stat_replication`, lag in bytes and seconds), Asterisk ARI health, service IP ownership, and witness reachability.
* Alerts go to administrators. Nothing fails over automatically while automatic failover is disabled.

## 8. Procedures (M16)

* **Enroll secondary:** run the installer on node B with `--role secondary --join <primary>`. This copies secrets and takes a base backup over a dedicated replication role (TLS, `pg_hba` limited to the peer address). Asterisk is installed and stopped, and the node is recorded in `cluster_nodes`.
* **Planned switchover:** freeze configuration changes → wait for zero replication lag → stop Asterisk on A → demote A (stop PostgreSQL) → promote B (`pg_ctl promote`) → regenerate and deploy Asterisk configuration on B → start Asterisk on B → move the IP → B becomes primary, A rejoins as standby (`pg_rewind`) → audit.
* **Unplanned failover (manual):** the operator confirms A is down or fenced → promote B → as above.
* **Node recovery / rejoin:** the returning node checks the epoch → demotes → resynchronizes → becomes the standby.
* **HA-aware updates:** update the secondary, switch over, update the old primary, optionally switch back. Rolling updates will not be claimed safe until tested (see UPDATE_MANAGEMENT.md).

## 9. Network requirements

* Both nodes on the same L2 segment for VRRP and gratuitous ARP. Routed designs need different service-IP handling.
* Replication (PostgreSQL 5432/TCP) and the control channel are allowed only between the node addresses. Using a dedicated VLAN or interface is recommended.
* Carriers: the trunk must accept the service IP, or registration must come from it.
* Firewall rules are derived from the actual configuration and documented in NETWORKING.md, never assumed.

## 10. Test plan (all must pass before HA is offered)

| Test | Expected result |
|---|---|
| Planned switchover | New calls work on B within RTO; no data loss; audit trail complete |
| Primary failure (VM powered off) | Detected and alerted; manual failover succeeds; RPO measured |
| Secondary failure | No impact on A; alert raised; rejoin works |
| Database failure on primary (PostgreSQL killed) | Detected; failover or restart procedure documented and tested |
| Network partition between nodes | No split brain: no node promotes without quorum and fencing |
| Replication failure / lag | Alert; switchover blocked while lag > threshold |
| SIP trunk failure | Detected as trunk status, *not* treated as a node failure |
| Node recovery and rejoin | Old primary rejoins as standby (`pg_rewind`) with no divergence |
| Configuration sync failure | Promotion regenerates configuration from the database; secrets mismatch is detected |
| Repeated switchovers (10×) | Stable; no leaked state |

## 11. What exists today (Milestone 0)

* The `cluster_nodes` and `cluster_events` tables, with dynamic roles.
* `/api/v1/ha/status`: deployment mode, nodes, heartbeat-derived state, database role (`pg_is_in_recovery`), and an explicit `automatic_failover: false` with the reason.
* Worker heartbeats for the local node.
* The installer accepts only `--role standalone`. HA roles are refused with a pointer to M16.
