# Milestone 16 Report — High Availability

Branch `milestone-16` (from `main` at 0.21.0). Design:
[HIGH_AVAILABILITY.md](../HIGH_AVAILABILITY.md) (goals, recovery targets and
the full test plan in [HA_ARCHITECTURE.md](../HA_ARCHITECTURE.md)). Status:
**approved 2026-10-16, released as 0.22.0** (stage 2 pending veyra-dev2). HA is
not described as available until the stage-2 table (two real servers) passes.

## 1. Scope (roadmap row 16)

Two Veyra nodes, active/passive: a standalone installation becomes the
primary in place, a second server joins as the standby with a one-time
token; PostgreSQL streaming replication and a file sync keep the standby
current; a planned switchover or a manual failover moves the service; the
standby's interface is read-only. Nothing promotes a node without an
operator.

## 2. Results

* **Enablement** (`veyra.ha.agent`, `POST /ha/enable`, `veyra ha enable`):
  node key, replication credential, PostgreSQL fragment (`wal_level`,
  `wal_log_hints`, slots, TLS from the Veyra CA) with one restart, the
  Veyra CA re-signed with its own key when its name constraints do not
  permit the service or node names, HTTPS certificate for the service name,
  both node names and both addresses, the service address taken with
  gratuitous ARP. Six steps, 8 s on dev1.
* **Join** (`install.sh --role secondary --join <url> --token <t>`): the
  installer checks the primary answers, installs the packages, starts the
  agent and runs `join-prepare`: the signed `join` call (unverified TLS,
  since the new node has no CA yet; the bundle is encrypted with a key
  derived from the single-use token), the bundle (secrets, CA, certificates,
  trust keys, replication credential, the node's own PostgreSQL
  certificate), `pg_basebackup` with a slot, a standby in 11 s. Then the
  rest of the installer, role-aware: no migrations, Asterisk configured and
  stopped, `veyra-deployer`/`veyra-pager` stopped, engine units not enabled
  at boot, `verify.sh` with `ha-role`, `ha-replication`, `ha-sync`,
  `ha-peer`.
* **Replication and file sync**: streaming, lag 0 in the test; the
  secondary pulls the manifest every 30 s (data roots from the API, the
  root-only roots secrets/TLS/trust from the primary's agent) and fetches
  files through the signed channel with the body hash under the signature;
  a file written on the primary appeared on the standby with its owner and
  mode within one interval; deletions only inside roots the manifest covers.
* **The standby's interface**: writes answer `503 ha_standby` (reads work),
  sign-in with the authenticator code and an in-memory session for platform
  administrators, the banner, the HA page with *Fail over*.
* **Switchover** (`POST /ha/switchover`, `veyra ha switchover` on the
  target): preconditions (versions, streaming, lag < 16 MB, sync < 5 min,
  nothing running), then the thirteen steps of §6 with per-step timings
  recorded in `operation.json` and the events table. Node calls keep working
  while the old primary's database is stopped (caller from `node.json`,
  in-memory nonces, health from the state files); an abort before promotion
  restarts PostgreSQL, the engine, the address and unfreezes.
* **Failover** (`POST /ha/failover`, `veyra ha failover --confirm-fenced`):
  Proxmox fencing when configured (mock-tested), else the operator's recorded
  confirmation; promote, epoch, slot for the old primary, migrations,
  deploy, address.
* **Epoch rules** (§7.3) at agent start and when the peer reappears: a
  stale primary demotes and rejoins by itself; a primary whose peer is
  unreachable at boot waits as *isolated* until *Resume as primary*; a
  running primary is never isolated by a peer outage.
* **Rejoin** by `pg_rewind`, else a fresh base backup; **remove node**
  returns the pair to standalone (events kept); `veyra ha standalone` on a
  removed secondary.
* **HA-aware updates**: *Install on the standby* from the Updates page
  (`POST /ha/standby-upgrade`); `upgrade.sh` on a standby skips migrations
  and keeps the engine stopped; the switchover runs migrations at promotion.
* **Interface**: System → High availability (enable form, node cards,
  service and fencing cards, add node with the exact installer command,
  switch over with the precondition list, fail over, rejoin, remove,
  replication mode and recordings switches, the running operation with its
  steps, events, join tokens); dashboard tile; standby banner; Updates page
  callout. Alert rules `node_offline`, `replication_broken`,
  `replication_lag`, `ha_sync_failed`, `node_isolated`, `ha_operation_failed`.

## 3. Testing (final tree, 2026-10-16)

| Suite | Result |
|---|---|
| Backend `pytest` | 454 passed, 39 of them HA (`test_ha_core.py` rules, state files, fragments, pg_hba, LSN parsing, manifests and transfer, bundle, fencing; `test_ha_sequences.py` switchover happy path, abort before and failure after promotion, catch-up timeout, failover with and without fencing, rejoin/demote/resume, the agent's verbs, epoch rules on tick, sync; `test_ha_api.py` enable, tokens, signed join, health/heartbeat/manifest/file/run with signature, replay and unknown-node checks, switchover preconditions and start, failover/resume/rejoin/remove, fencing and sync settings, standby guard and in-memory sign-in, HA alert checks) |
| Frontend `vitest`, `tsc`, `eslint`, `next build` | 51 passed, clean |
| Installer `test_lib.sh` | 61 passed |

### Stage 1 live test (dev1 + LXD container `veyra-dev2t`, 03:56–04:40 UTC)

dev1 (veyra-dev1, 172.16.2.250, Ubuntu 26.04, PostgreSQL 18) as the primary
and an Ubuntu 26.04 container on `lxdbr0` (10.227.92.11) as the stand-in
secondary; service `veyra-ha-test` 10.227.92.10/24 on `lxdbr0` (dev1) and
`eth0` (container). The container was installed from a tarball of the
branch with the prebuilt frontend; dev1 was upgraded by the owner from
`~/veyra` between rounds.

| Check (HA_ARCHITECTURE.md §10 where applicable) | Result |
|---|---|
| Enable on a standalone | OK, 8 s; CA widened, certificate valid, address held, PostgreSQL restarted once |
| Join | OK, 11 s to a streaming standby; the rest of the installer role-aware; verify green |
| File sync | OK: test file on the standby within 30 s, owner/mode kept; root-only roots served by the agent |
| Standby interface | `POST` → `503 ha_standby`, reads 200 |
| Planned switchover dev1 → container, then back | OK both ways, 13–14 s per sequence (freeze 1.1 s, catch-up 0.3 s, promote 0.2 s, epoch 2.2 s, migrate 1.1 s, deploy 5.2 s, address 2.1 s, rejoin call 0.1 s, unfreeze 1.1 s); the old primary rejoined by itself in ~12 s; the service address answered on the new primary each time |
| Primary failure (container stopped) → failover on dev1 | OK, 14 s with the operator's confirmation (no fencing configured); epoch 3 |
| Node recovery and rejoin | The stale primary booted, saw the higher epoch, demoted and rejoined in ~20 s without an operator |
| Standby update first (§12) | `upgrade.sh` on dev1 as a standby: migrations skipped, engine stopped, verify green |
| Remove node | The secondary made standalone, the slot and pg_hba lines dropped, the row removed, the installation standalone again; verify green |
| Secondary failure | Not driven explicitly; the primary kept serving through every container reinstall and stop (the rule that a running primary is never isolated came out of this test) |
| Network partition, database killed on the primary, replication lag threshold, trunk failure, ten switchovers, RPO/RTO measurement | **Stage 2** (two real servers) |

Twenty-two defects were found and fixed during the live test; the ones
that changed the design are in HIGH_AVAILABILITY.md §16. Rejoins used a
fresh base backup each time (`pg_rewind` first lacked grants, then Debian's
configuration path, then the WAL-restore flag); the last fix is in the tree
and untested live.

Test-topology artefact: dev1 reaches the container from its `lxdbr0`
address, not from its declared node address, so the container's
`pg_hba.conf` got two extra lines by hand. On one segment (stage 2) this
does not arise.

## 4. Not verified

* Stage 2 of §15: two real servers on one segment (veyra-dev2 is not set
  up): RTO and RPO measurement with real phones and a trunk, network
  partition, PostgreSQL killed on the primary, lag threshold, ten
  switchovers in a row, the full update order with a real release.
* `pg_rewind` succeeding (see §3); Proxmox fencing against a real Proxmox;
  synchronous replication live; recordings and voicemail in the sync with
  real volumes.
* The HA page and the standby sign-in in a browser (the API paths are
  tested; the owner has not opened the page).

## 5. Known limitations

* No automatic failover and no witness (by design, §14): a primary that
  boots without reaching its peer waits for the operator.
* A switchover ends calls in progress; phones re-register within their
  expiry (§13 question 6 proposes 120 s).
* The service address must be on the nodes' shared L2 segment; node calls
  and replication use each node's own address.
* After `enable`, phones and browsers that trusted the old CA certificate
  must trust the re-signed one when the names had to be widened.
* `install.sh --role secondary` needs the same release unpacked on the
  second server; a release tarball with the prebuilt frontend is the way.

## 6. Open items

* The six owner questions of HIGH_AVAILABILITY.md §13 (service name and
  address, fencing token, replication mode, standby page scope, recordings
  in the sync, registration expiry).
* dev1 keeps the HA remnants of the test: the PostgreSQL fragment
  (listening on 172.16.2.250 with TLS), the re-signed CA, the test service
  address 10.227.92.10 on `lxdbr0` (held until the next agent restart or
  `ip addr del`), `ha.service` in the settings; the container
  `veyra-dev2t` is stopped and can be deleted.

## 7. Next milestone

Milestone 17 per the roadmap, or stage 2 of this one as soon as
veyra-dev2 exists.

## 8. Owner decisions

* 2026-10-15: "Go ahead with the design, I'll set up veyra-dev2."
