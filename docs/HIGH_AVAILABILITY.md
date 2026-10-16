# High Availability (Milestone 16)

Design for Milestone 16 (roadmap row 16, 0.22.0): the implementation of
[HA_ARCHITECTURE.md](HA_ARCHITECTURE.md) (the M0 architecture and its
goals, non-goals, recovery targets and test plan, which still hold) and
ADR 0006. ARCHITECTURE.md §3 mode B. This document says what gets built,
how the pieces talk to each other, and what the operator sees.

Two full Veyra nodes, **active/passive**. The primary runs everything; the
secondary keeps a replica of the database and the files, runs the web
interface read-only, and can take over by a **manual, audited switchover**
(both nodes up) or **failover** (the primary is down). Automatic failover
stays off: nothing in this milestone promotes a node without an operator.

## 1. Principles

1. **Same build, mode is data.** `installation.deployment_mode` becomes
   `ha` when the second node joins; `cluster_nodes.role` is the only
   source of roles. A standalone installation becomes the primary in
   place, with its data, phones and certificates.
2. **One writer, always.** At most one node holds the service address,
   runs Asterisk and has a writable database. Every rule below exists to
   keep that true, in particular after a restart or a healed partition.
3. **No SSH between nodes, no shared root.** Nodes talk over HTTPS with
   the node keys from the join (the signed message format of
   [CENTRAL_MANAGEMENT.md](CENTRAL_MANAGEMENT.md) §1.4, reused as is) and
   over PostgreSQL's own replication connection. The installer never
   changes SSH settings; that stays true.
4. **Privileged actions are a fixed list** run by a root agent on each
   node (§3), the way `veyra-firewall` applies rules and `veyra-deployer`
   writes files. The API never runs as root.
5. **The operator decides, and can always see why.** Every switchover and
   failover is a sequence of named steps, recorded while it runs and
   written to `cluster_events` and the audit log when the database can
   take it. A node that is unsure of its role waits and says so instead
   of guessing.
6. **A single node must keep working.** The secondary being down never
   stops the primary (asynchronous replication by default, §4).

## 2. Topology and addresses

```
   phones / trunks / browsers  ──►  service name  (veyra.example → 172.16.2.10)
                                         │ held by the primary only
          ┌──────────────────────────────┴───────────────────────────────┐
   node A (veyra-dev1, 172.16.2.250)                 node B (veyra-dev2, 172.16.2.251)
   PRIMARY: nginx, api, worker, deployer,            SECONDARY: nginx, api (read-only),
   pager, firewall, asterisk ●, postgres (primary)   worker (idle), firewall, asterisk ○,
   ha-agent (holds 172.16.2.10)                      postgres (standby), ha-agent
                     ├── 5432/TCP streaming replication (TLS) ──►
                     ◄── 443/TCP signed node calls ──────────────►
                     ◄── file sync over the node calls ──────────┤
```

* **Service address:** one IPv4 address on the nodes' shared L2 segment
  (`ha.service`: address, prefix length, interface). The agent on the
  primary adds it to the interface and announces it (gratuitous ARP);
  the agent on any node whose database is in recovery removes it. No
  keepalived: VRRP would be a second decision maker, and it is not
  needed while failover is manual.
* **Service name:** `VEYRA_PUBLIC_HOST` becomes the name phones and
  browsers use (it resolves to the service address). The HTTPS
  certificate covers the service name and both node names, so each node
  can also be reached directly by its own name, which is how the
  operator reaches the standby. The Veyra CA is shared (its key is part
  of the join bundle), so phones that trust it today keep trusting it.
* **Node addresses:** each node keeps its own fixed address for
  replication, node calls and the standby interface.

## 3. Components

| Piece | Where | What |
|---|---|---|
| `veyra-ha-agent` (new unit, root) | both nodes | `veyra ha agent`. Listens on `/run/veyra/ha.sock` (root:veyra 0660) for a fixed list of verbs (§3.1). Holds or releases the service address, runs the role sequences (§6–§8), polls the peer every 10 s on the primary, runs the file sync on the secondary. State in `/var/lib/veyra/ha/` (`node.json`: node id, role, epoch, peer; `operation.json`: the running sequence). |
| `veyra.ha` package | backend | `agent` (the unit), `client` (socket client for the API and CLI), `peer` (signed node calls), `postgres` (replication state, `pg_basebackup`, promote, `pg_rewind`, configuration fragments), `sequences` (switchover, failover, rejoin, enable), `sync` (file manifest and transfer), `status` (extended from M0). |
| API `/ha/*` | both nodes | §9. Signed node endpoints `/ha/peer/*` (no session). |
| Installer | both nodes | `install.sh --role secondary --join <url> --token <t>`; role-aware `upgrade.sh` and `verify.sh`; `veyra ha enable` on the primary (§5). |
| Interface | both nodes | System → High availability (§10); the standby banner; dashboard item. |
| Migration `0029` | | §11. |

### 3.1 Agent verbs

`status`, `enable` (standalone → primary), `join-prepare` (secondary:
write secrets and TLS, configure and base-backup PostgreSQL), `hold-address`,
`release-address`, `promote`, `demote`, `rejoin` (`pg_rewind` or fresh
base backup, then standby), `engine start|stop`, `postgres start|stop|reload`,
`sync-now`, `fence <node>` (§7.2), `resume` (§7.3), `set-role`. Each verb
checks that it makes sense for the local state (`promote` refuses when
the database is not in recovery; `hold-address` refuses while in
recovery) and logs to `/var/log/veyra/ha.log` and the journal.

### 3.2 Node identity and the peer channel

Each node has an Ed25519 node key in `/etc/veyra/secrets/node.key`
(created by `enable` on the primary and by the join on the secondary).
The join exchanges public keys; `cluster_nodes.public_key` and
`node.json` hold the peer's. Node calls are `POST https://<peer>/api/v1/ha/peer/<verb>`
with the signed body, timestamp and nonce from M15's protocol; the
certificate is verified against the shared Veyra CA. Verbs: `health`
(role, epoch, database role, replay LSN, version, service address
held?), `heartbeat`, `manifest` and `file` (sync, §4.2), `run <agent verb>`
(only the verbs a peer may ask for: `engine stop`, `demote`, `rejoin`,
`release-address`, `postgres stop`, `upgrade <version>`), `epoch`.

## 4. Replication

### 4.1 Database

PostgreSQL physical streaming replication, set up by the agent, never by
hand:

* On the primary (`enable`): `listen_addresses` adds the node address;
  `wal_level = replica`, `wal_log_hints = on` (for `pg_rewind`),
  `max_wal_senders = 5`, `max_replication_slots = 5`,
  `max_slot_wal_keep_size = 4GB` (a slot never fills the disk), `ssl = on`
  with a certificate issued by the Veyra CA to the node name
  (`/etc/veyra/tls/postgres.crt|key`, owned by `postgres`), `ssl_ca_file`
  the Veyra CA. A replication role `veyra_replication` with a generated
  password in `/etc/veyra/secrets/replication_password` (part of the join
  bundle). `pg_hba.conf` gets one line per peer:
  `hostssl replication veyra_replication <peer>/32 scram-sha-256`, and the
  same for the `veyra` database so the standby's API can, after promotion,
  keep using the local socket (unchanged) — the network line exists for
  `pg_rewind` only. All fragments live in `conf.d/veyra-ha.conf` and a
  marked block of `pg_hba.conf`, backed up before every change, exactly
  like the installer's other managed files. These need a PostgreSQL
  restart once (`enable`), which the interface warns about (the API
  reconnects; calls in progress are unaffected).
* On the secondary (`join-prepare`): `pg_basebackup -R --slot veyra_<node>
  --checkpoint=fast` over TLS (`sslmode=verify-ca`) into a fresh data
  directory; `standby.signal`; the same `conf.d` fragment so it is ready
  to be promoted.
* **Asynchronous by default.** `synchronous_commit` stays `on` locally
  with no synchronous standby: the primary never blocks on the secondary.
  The HA page offers "Synchronous replication" as an explicit switch with
  its consequence spelled out (writes block while the standby is down;
  turning it off is the recovery). The default is the recommendation for
  a two-node pair without a witness (§13 question 3).
* **Lag** is measured on the primary from `pg_stat_replication`
  (`write_lag`, `replay_lag`, bytes behind) and on the standby from
  `pg_last_wal_replay_lsn()` and `pg_last_xact_replay_timestamp()`;
  `/ha/status` shows both.

### 4.2 Files

What is not in the database and must exist on the new primary:

| Path | Why |
|---|---|
| `/var/lib/veyra/prompts`, `moh`, `firmware`, `provisioning/templates`, `modules`, `updates` | Prompts and hold music the dialplan plays; firmware and templates phones fetch; installed modules; downloaded releases (so a standby can be updated from the same artifact) |
| `/var/lib/veyra/recordings` | Call recordings (can be large; excluded by a switch, §13 question 5) |
| `/var/spool/asterisk/voicemail` | Voicemail messages and greetings |
| `/etc/veyra/secrets`, `/etc/veyra/tls`, `/etc/veyra/trust` | Copied once by the join; re-synced when they change (the CA, certificate renewals, catalog keys) |

The secondary **pulls** every 30 s: `manifest` returns path, size, mtime
and a BLAKE2 digest for files changed since the last manifest (the
primary keeps a small cache keyed by mtime); `file` streams one file. New
and changed files are written to a temporary name and renamed into place
with the right owner and mode (the agent is root); files that left the
manifest are removed. The last successful sync time and the backlog are
in `/ha/status`; a sync older than 5 minutes raises an alert. rsync over
SSH would be the shortcut and is not used (principle 3). Data written on
the primary in the last interval is lost in a failover; that is the file
part of the RPO and the test plan measures it.

### 4.3 What is not replicated

SIP registrations and calls in progress (HA_ARCHITECTURE.md §1). After a
role change, phones re-register at their next interval; the provisioning
templates get a `registration_expiry` default of 120 s (§13 question 6),
and the agent's gratuitous ARP makes the switch of the address immediate
for the switches.

## 5. Enrollment

**On the primary** (standalone → primary, once): System → High
availability → *Enable high availability*: service name, service address
and prefix, interface (pre-filled from the node's routes), replication
mode. The agent runs `enable`: node key, PostgreSQL configuration and
restart, replication role, certificate reissued with the service name,
`cluster_nodes` row becomes `primary`, `deployment_mode = ha`, the
service address is taken. Phones keep working on the node name until the
templates say the service name; the page says so.

**Add node**: creates a **join token** (single use, 24 h, shown once with
the primary's address and node-key fingerprint). On the new server:

```
sudo installer/install.sh --role secondary --join https://veyra-dev1 --token vyj_…
```

The installer runs preflight (adds: an address in the service prefix on
one interface, the primary reachable, clock within 30 s, same Ubuntu
release), packages, versions and the account; then, instead of secrets
and a new database, it starts the agent and runs `join-prepare`:

1. `POST /ha/peer/join` with the token and the new node's key and name;
   the primary verifies the token, records the node (`secondary`,
   `joining`), adds the `pg_hba` lines and reloads PostgreSQL, and answers
   with the **bundle**, encrypted with a key derived from the token:
   secrets (installation key, ARI password, companion and module signing
   keys, replication password), TLS (CA key and certificate, node
   certificate issued for the new node and the service name), trust keys,
   `installation.conf` values (public host, provisioning options), the
   peer's public key and epoch.
2. The bundle is written with the same owners and modes as on the primary.
3. PostgreSQL: data directory replaced by `pg_basebackup`, standby.
4. The rest of the installer runs as today, role-aware: migrations are
   skipped (the standby cannot write; the schema arrives with the backup),
   Asterisk is installed and configured and then **stopped and disabled**,
   `veyra-pager` and `veyra-deployer` are installed but stopped, NGINX
   serves the standby interface, `veyra-ha-agent` is enabled.
5. The first file sync runs; the node reports `health`; the primary marks
   it `online`.

`upgrade.sh` on a secondary skips migrations and keeps Asterisk stopped.
`verify.sh` adds `ha-role` (what `node.json`, the database and the
service address say must agree), `ha-replication` (streaming, lag),
`ha-sync` (last success), `ha-peer` (reachable, same version, same CA).

## 6. Planned switchover

From the HA page on either node ("Switch over to veyra-dev2"), or
`veyra ha switchover <node>`. Preconditions, all shown before the
confirmation: both nodes online and the same version; replication
streaming with replay lag under 16 MB; no deployment or upgrade in
progress; file sync within the last 5 minutes. The operator is told that
**calls in progress end** and phones re-register within their expiry.

The sequence runs on the **target** node's agent (B), so that it survives
A's database going away; A-side steps are node calls. Each step is written
to B's `operation.json` as it starts and ends:

1. `freeze`: the primary's API refuses writes (`503 ha_switchover`) and
   the deployer pauses; the worker finishes its pass.
2. `engine stop` on A (calls end; trunks unregister).
3. `catch-up`: wait until B's replay LSN equals A's current WAL LSN
   (A's `pg_current_wal_lsn()` after a final checkpoint), at most 60 s,
   else abort and unfreeze.
4. `release-address` on A, then `postgres stop` on A (no writer exists now).
5. `promote` on B (`pg_ctl promote`), wait until not in recovery.
6. `epoch`: B's epoch = old + 1, written to `node.json` and
   `installation`; `cluster_nodes`: B `primary`, A `secondary`
   (`rejoining`); `cluster_events` and the audit log get the sequence so
   far.
7. `deploy`: B's deployer regenerates and writes the engine configuration
   from the database (the authoritative copy); `engine start` on B;
   `veyra-pager`, `veyra-deployer` started; worker resumes duties.
8. `hold-address` on B with gratuitous ARP.
9. `rejoin` on A (node call): `pg_rewind --source-server=<B>` (fast,
   because of `wal_log_hints`) or, if that fails, a fresh base backup;
   `standby.signal`; `postgres start`; A's `node.json` gets role
   `secondary`, B's epoch and B as peer; A's sync starts pulling from B.
10. `unfreeze`; `cluster_events` `switchover_completed` with the measured
    duration per step.

An abort before step 5 leaves A primary (unfreeze, engine start, address
back). An abort after step 5 cannot go back: B is primary and the operator
sees what remains (typically step 9, which can be rerun from the page).

## 7. Failover (the primary is down)

### 7.1 Procedure

On the standby's own interface (`https://veyra-dev2`) or `sudo veyra ha
failover`: the page shows what B knows (last contact with A, replay lag at
that moment, which means the possible data loss), and requires the operator
to confirm **A is powered off or fenced**. Then: `fence` (§7.2) if
configured, else the operator's confirmation is recorded; `promote`,
epoch + 1, deploy, engine start, hold the address, events and audit
(now writable). A is marked `secondary`/`unknown` until it comes back.

### 7.2 Fencing

Optional `ha.fencing` setting: Proxmox VE API (URL, API token with
`VM.PowerMgmt` on the two VMs, the VM id per node, CA or fingerprint).
`fence <node>` calls `POST /nodes/<pve>/qemu/<vmid>/status/stop`, then
polls `status/current` until `stopped`, at most 60 s; failure to fence
blocks the failover unless the operator confirms by hand (recorded as
such). The token secret is stored encrypted with the installation key
(as M11 stores module secrets). Nothing else uses the token. Other
fencing methods are not in scope (§14).

### 7.3 The old primary comes back: no split brain

The agent decides at every start and whenever the peer becomes reachable:

* Read `node.json` (role, epoch). Ask the peer for `health`.
* **Peer answers with a higher epoch** → this node is stale: `demote`
  (stop Asterisk if running, release the address, PostgreSQL stays stopped),
  then `rejoin` as standby of the peer. Logged, alerted.
* **Peer answers with the same epoch and is secondary** → resume primary
  duties (start PostgreSQL, deployer, Asterisk, hold the address).
* **Peer answers with the same epoch and says primary too** → never
  happens by construction (promotion increments the epoch); treated as the
  stale case, and alerted.
* **Peer unreachable** → the node does **not** resume primary duties:
  Asterisk stays stopped, the address is not taken, PostgreSQL starts
  (reads work). State `isolated`, alert `node_isolated`, and the page
  offers *Resume as primary* for the case where the peer is genuinely
  gone (`veyra ha resume`). This is the price of two nodes without a
  witness: a reboot of the primary while the peer is down needs one click.

The standby applies the mirror rule: it never promotes itself.

## 8. Node recovery, removal, replacement

* **Rejoin** is step 9 of §6 and §7.3; it is also a button on the HA page
  for a node in `rejoining` or `diverged` state (`pg_rewind` failed →
  fresh base backup).
* **Remove node**: allowed for a secondary; drops the slot and the
  `pg_hba` lines, deletes the row, and the node becomes a standalone that
  refuses to start Asterisk until `veyra ha standalone` is run on it (so
  a forgotten node never registers to the carrier). With one node left,
  `deployment_mode` goes back to `standalone` and the service address stays
  on the remaining node (phones keep working).
* **Replace node**: remove, then add with a new join token.

## 9. API

| Route | Who | What |
|---|---|---|
| `GET /ha/status` | `ha.read` | As M0 plus: `local` (this node, role, epoch, database role, address held), `peer`, `replication` (state, lag bytes and seconds, slot), `sync` (last success, backlog), `service` (name, address, holder), `operation` (the running or last sequence with its steps), `fencing` (configured?) |
| `PUT /ha/service` | `ha.manage` | Service name, address, prefix, interface, replication mode; `POST /ha/enable` |
| `POST /ha/join-tokens`, `DELETE …/{id}` | `ha.manage` | Join tokens (shown once) |
| `POST /ha/switchover` `{target}` | `ha.manage` | Preconditions checked; starts the sequence on the target |
| `POST /ha/failover` `{confirm_fenced}` | `ha.manage`, standby only | §7.1 |
| `POST /ha/resume`, `POST /ha/nodes/{id}/rejoin`, `DELETE /ha/nodes/{id}` | `ha.manage` | §7.3, §8 |
| `PUT /ha/fencing` | `ha.manage` | §7.2 |
| `GET /ha/events` | `ha.read` | `cluster_events` |
| `POST /ha/peer/{join,health,heartbeat,manifest,file,run,epoch}` | node key | §3.2, rate limited, `include_in_schema=False` |

**The standby's API** answers `GET` from the replica. Any write answers
`503 ha_standby` with the service name, except the HA routes above and
sign-in. **Sign-in on the standby**: the password and second factor are
verified against the replicated tables; the session lives in the API
process only (`StandbySessions`, one hour, platform administrators only),
because the session table cannot be written. The interface shows the
banner "Standby node: manage the system at <service name>" and hides
everything but the HA page, status pages and sign-out. Audit entries for
the failover are written right after promotion.

**The worker on a standby** does only the heartbeat (through the peer
channel) and nothing else; it checks `pg_is_in_recovery()` at the start of
every pass. Central management (M15) check-ins come from the primary only;
the instance identity is shared, so the console sees one instance.

## 10. Interface

System → **High availability** (`/system/ha/`):

* **Not enabled:** the explanation, *Enable high availability* with the
  form of §5.
* **Enabled:** two node cards (name, role, state, version, database role,
  replication lag, last heartbeat, address holder), the service card
  (name, address, holder, replication mode, fencing), *Add node* (the
  token dialog with the exact `install.sh` line), *Switch over* (the
  preconditions and the warning), *Fail over* (on the standby), *Rejoin*,
  *Remove*, the running operation with its steps and timings, and the
  events table.
* Dashboard: an HA tile (healthy / degraded / isolated) for platform
  administrators.
* Updates page on an HA primary: "Update the standby first" (§12), the
  standby's version, and the order of the three steps.

Alerts (M10 rules, `ensure_rules`): `node_offline` (no heartbeat for 2
minutes), `replication_broken` (no WAL receiver), `replication_lag`
(over 64 MB or 60 s), `ha_sync_failed` (over 5 minutes), `node_isolated`,
`ha_operation_failed`.

## 11. Data (migration `0029`)

* `cluster_nodes`: + `public_key`, `epoch`, `db_role` (`primary|standby|
  down`), `replication` (JSONB: state, lag, slot), `sync_at`,
  `holds_address` (bool), `fingerprint`.
* `installation`: + `ha_epoch` (the cluster epoch, replicated so a
  promoted standby carries it), `ha_frozen` (switchover in progress).
* `system_settings`: `ha.service`, `ha.fencing`, `ha.sync` (recordings
  included?, interval), `ha.join_tokens` (hashes, like M15's tokens).
* `cluster_events`: unchanged; `event_type` values documented:
  `ha_enabled`, `node_joined`, `node_removed`, `switchover_started|step|
  completed|aborted`, `failover_started|completed`, `fenced`, `demoted`,
  `rejoined`, `isolated`, `resumed`.
* Node-local, not in the database: `/var/lib/veyra/ha/node.json`,
  `operation.json`, `sync.json`, `/etc/veyra/secrets/node.key`.

## 12. HA-aware updates

Order (UPDATE_MANAGEMENT.md §8): the standby first, then switch over,
then the old primary, then optionally switch back. From the Updates page
on the primary, *Install on the standby* sends `run upgrade <version>` to
the peer: the standby starts its own `veyra-upgrade@<version>` with the
artifact it already pulled by the file sync, re-verified there; migrations
are skipped on a standby. Then *Switch over*: the new primary (newer code)
runs the migrations at promotion (the §6 `promote` step runs
`alembic upgrade head` before `deploy`); the old primary, now standby,
runs older code against a newer schema for the minutes until *Install on
<old primary>* — only its HA page and read-only status are used in that
window, and this exact window is in the test plan. Both nodes are never
upgraded at the same time; the page refuses the second upgrade while a
sequence runs.

## 13. Open questions for the owner

1. **Service name and address:** a name phones and browsers will use
   (e.g. `veyra` → `veyra.brookfieldr3.org`?) and a free address in
   172.16.2.0/24 on the same VLAN as both nodes, plus the interface name
   on dev2 if it differs from dev1's.
2. **Fencing:** a Proxmox API token with `VM.PowerMgmt` on the two VMs
   (and the VM ids), or manual confirmation only?
3. **Replication mode:** asynchronous by default (proposed), with the
   synchronous switch available?
4. **The standby's interface:** HA page and status only (proposed), or
   also read-only browsing of reports and call history?
5. **Recordings in the file sync:** included by default (proposed; they
   are the largest files), or excluded?
6. **Phone registration expiry** in the provisioning templates: 120 s
   (proposed) for a faster recovery, at the cost of a little more SIP
   traffic?

## 14. Out of scope

Automatic failover, a witness or quorum service (HA_ARCHITECTURE.md §6
remains the plan for it); keepalived/VRRP; more than two nodes; fencing
other than Proxmox (IPMI, PDU); shared storage; migrating calls in
progress; routed (non-L2) service addresses; a read-write standby; Proxmox
HA of the VMs themselves (allowed to coexist, documented as not being
application HA).

## 15. Testing

* **Unit:** the epoch rules of §7.3 as a pure function (every combination
  of local role, local epoch, peer answer); switchover preconditions;
  manifest diff and file transfer (temporary directories); PostgreSQL
  configuration fragments and `pg_hba` block editing; the join bundle
  (encrypt, decrypt, owners and modes); the fencing client against a mock
  Proxmox; `StandbySessions`.
* **API:** two apps in one test as M15 does, with the agent socket mocked
  by an in-process fake that records verbs and answers; join, status,
  switchover sequence with step order and abort paths, failover with and
  without fencing, the standby's `503 ha_standby` and sign-in, peer
  endpoints' signature and rate limit checks.
* **Installer:** `test_lib.sh` for the role-aware paths and the new verify
  checks.
* **Live, stage 1 (dev1 + an Ubuntu 26.04 LXD container on dev1 as the
  stand-in secondary, same L2 on `lxdbr0`):** enable, join, replication,
  file sync, switchover both ways, failover (container stopped), rejoin,
  remove. Finds the integration bugs without waiting for hardware.
* **Live, stage 2 (dev1 + veyra-dev2):** the full HA_ARCHITECTURE.md §10
  table — planned switchover, primary VM powered off, secondary failure,
  PostgreSQL killed on the primary, network partition (no promotion),
  replication lag threshold, trunk failure not a node failure, rejoin with
  `pg_rewind`, configuration sync failure, ten switchovers — plus the
  update order of §12, with RTO and RPO measured and written into the
  report. HA is described as available only after this table passes.

## 16. Implementation notes (build, 2026-10-16)

Where the build departs from or sharpens the sections above:

* **Digests are SHA-256**, not BLAKE2 (§4.2): one hash function for the
  manifest and for the signed `file` answer, whose signature covers the
  SHA-256 of the streamed body (`veyra.ha.peer.answer_headers`).
* **The node key is `root:veyra 0640`** (§3.2), like the installation key:
  the API signs its answers to the peer and makes node calls itself
  (switchover request, `run`, health); the agent uses the same key.
* **Database writes of the agent** go through `veyra ha db <action>` run as
  the service account (`set-roles`, `set-frozen`, `event`, `node-report`,
  `enable`, `register-peer`, `remove-node`, `standalone`, `deploy`,
  `deploy-state`): the root agent never holds a database connection, and
  PostgreSQL keeps peer authentication. The standby's agent reports through
  the primary's `heartbeat` instead.
* **The CA may be widened** (§2, §5): the installer's CA carries name
  constraints for one server; `enable` and `make-bundle` re-sign the CA with
  its own key when the service name or a node name is not permitted, and
  the HA page says that phones and browsers must trust the new copy. The
  node's PostgreSQL certificate is issued by the primary and travels in the
  bundle, as does the HTTPS certificate for the service name and both nodes.
* **PostgreSQL reads its certificate from `/var/lib/postgresql/veyra-tls/`**
  (postgres-owned copies of the CA and the node certificate, refreshed by
  the agent), because `/etc/veyra/tls` is root-only; the `conf.d` fragment
  is written world-readable. The agent's runtime directory is `root:veyra`.
* **The root agent serves the root-only sync roots** (`etc/secrets`,
  `etc/tls`, `etc/trust`): the API cannot read them, so `manifest` merges
  the agent's entries and `file` relays those files through the agent; the
  manifest names the roots it covers and a standby deletes only inside
  them, so a root the primary could not list never empties the standby.
* **The §7.3 rules run at the agent's start and when the peer becomes
  reachable again**, never when a running primary loses its peer: a healthy
  primary keeps serving through a standby outage (§1 principle 6).
* **NGINX listens on the service address on both nodes** through two
  include files the agent writes (`/etc/veyra/nginx-ha-listen-{http,https}.conf`)
  with `net.ipv4.ip_nonlocal_bind=1`, so the standby's NGINX starts without
  the address and answers the moment the address is held; the installer
  keeps the service address out of its own listen list.
* **Removing a node keeps its events** (`cluster_events.node_id` is cleared).
* **Engine units are not enabled at boot on an HA node** (`asterisk`,
  `veyra-deployer`, `veyra-pager`): the agent starts them with the primary
  role (§7.3), the installer and `upgrade.sh` respect `node.json`.
* **Sign-in on the standby** takes the authenticator code in the login body
  (`code`), because a pre-authentication session cannot be written; sessions
  are in memory, one hour, platform administrators only (§9).
* **Synchronous replication** is switched on the HA page (`PUT /ha/service`
  `synchronous`); the agent rewrites `conf.d/veyra-ha.conf` and reloads.
* **Fencing settings** are mirrored by the API into the agent's
  `<data>/ha/fencing.json` (root 0600, with the decrypted token) so a
  failover can fence without the database.
* **Additional routes:** `GET /ha/switchover-check`, `GET /ha/fencing`,
  `POST /ha/fencing/test`, `PUT /ha/sync`, `POST /ha/standby-upgrade`.
* **Agent verbs added:** `set-synchronous`, `set-sync`, `set-fencing`,
  `remove-peer`, `make-bundle`, `current-lsn`, `checkpoint`, `freeze`,
  `unfreeze`, `event`; peers may ask for `switchover`, `engine-start`,
  `hold-address` (refused in recovery) and `event` besides the §3.2 list.

