# Milestone 8: Completion Report

**Milestone:** 8 — Ring groups, call queues and call pickup groups
**Date:** 2026-10-14
**Branch:** `milestone-8` (pushed to `manderson20/veyra`)
**Version:** 0.10.0 (0.10.0-dev until approval)
**Status:** Software complete; backend, installer, interface, tests and documentation done (§3). **Awaiting the owner's upgrade of veyra-dev1, the live checks and approval** (§3, §6).

## 1. Scope (chosen by the owner 2026-10-14)

Per the Milestone 7 report §7 and roadmap row 8: ring groups (ring all or
in sequence, failover destination), call queues (agents, hold music,
announcements, strategies) and the owner's call-pickup request (group
pickup `*8`, directed pickup `**<extension>`, pickup-group membership per
extension, BLF friendly). Design and reference:
[RING_GROUPS_QUEUES.md](../RING_GROUPS_QUEUES.md). The owner chose this
milestone over a short 6c (Google sign-in) and keeps `veyra-dev1` as the
host name for now.

## 2. Results

| Task | Result | Where |
|---|---|---|
| Ring groups | Done. `ring_groups` + ordered `ring_group_members`; number from the numbering plan (shared number space with extensions and queues, `409 number_in_use` names the holder); strategies `ringall`/`sequential`, ring time 5–120 s, skip of members already on a call (`DEVICE_STATE`) or call waiting, caller-ID prefix, typed failover, enabled flag; `problems` and `in_use_by`; `409 ring_group_in_use`. `GET/POST /ring-groups`, `GET/PATCH/DELETE /ring-groups/{id}`. Telephony → Ring Groups (list, create dialog with the next free number, group page with the ordered member editor and an "as deployed" summary). | `backend/veyra/api/v1/ring_groups.py`, `core/models/groups.py`, `frontend/src/app/(app)/ring-groups/`, `components/groups/RingGroupFields.tsx`, `MemberListEditor.tsx` |
| Call queues | Done. `call_queues` + `queue_members` (penalty 0–9); six strategies, agent ring time, retry pause, wrap-up, maximum wait (0 = unlimited or 30–3600 s), maximum callers, join-when-empty, position announcements, announcement on joining and periodic announcement from prompts, music on hold or ringing, typed failover for every unconnected exit (`QUEUESTATUS` logged); `409 queue_in_use`. `GET/POST /queues`, `GET/PATCH/DELETE /queues/{id}`. Telephony → Call Queues (list, create, queue page with the agent editor). | `api/v1/queues.py`, `frontend/src/app/(app)/queues/`, `components/groups/QueueFields.tsx` |
| Pickup groups and feature codes | Done. `pickup_groups` + `pickup_group_members`; the slug is the Asterisk named group, rendered as `named_call_group`/`named_pickup_group` on every member endpoint; `*8` → `Pickup()`; `**<extension>` → `PickupChan(PJSIP/<endpoint>,,p)` with an organization check (`VEYRA_ORG`), so it also answers calls ringing through a group or queue; a `hint` per extension and per ring group for busy lamp fields and BLF pickup. `GET/POST /pickup-groups`, `GET/PATCH/DELETE /pickup-groups/{id}`. Telephony → Pickup Groups (list with edit and delete dialogs). | `api/v1/pickup_groups.py`, `telephony/asterisk/generator.py` (`_endpoints`, `_dialplan`), `frontend/src/app/(app)/pickup-groups/`, `components/groups/PickupGroupDialog.tsx` |
| Generated configuration | Done. Dialplan: group and queue numbers in `veyra-internal`, one `veyra-rg-<slug>` context per ring group (busy check per member, joined `Dial` or one `Dial` per member, `ANSWER` test, failover, loop guard `__VEYRA_GROUP_DEPTH` ≤ 6 shared with queues), one `veyra-queue-<slug>` per queue (`Answer`, announcement, `Queue(veyra-<slug>,t|tr,,,<max wait>)`, failover); IVR direct dialling lists group and queue numbers. New managed file `queues.conf` (`[general]`, one `[veyra-<slug>]` per queue with static `member =>` lines and the endpoint as state interface, `ringinuse=no`), reload scope `app_queue.so`. Snapshot version 5 with a `Targets` resolver for the five destination kinds. | `telephony/asterisk/generator.py` (`_ring_group_contexts`, `_queue_contexts`, `_queues`, `_goto`), `telephony/snapshot.py` |
| Destinations | Done. `DestinationIn/Out` gain `ring_group_id` and `queue_id`; every holder (inbound routes ×2, IVR menus ×2, IVR entries, ring groups, queues) stores the two new columns (`SET NULL`); one reference counter and describer (`count_uses`, `describe_uses`) serves the in-use rules of voicemail boxes, menus, groups and queues; labels `Ring group: Sales (2300)`, `Queue: Support (2400)`. Interface: the shared destination picker offers both kinds and hides the object being edited from its own list. | `api/v1/destinations.py`, `routing.py`, `ivr.py`, `voicemail.py`, `frontend/src/components/routing/DestinationPicker.tsx`, `lib/routing.ts` |
| Extensions | Done. `GET /extensions[/{id}]` lists `ring_groups`, `queues` and `pickup_groups`; the extension page gets a Call groups card; the next-number suggestion and the number check cover the three tables under the existing advisory lock. | `api/v1/extensions.py`, `telephony/numbering.py`, `components/extensions/CallGroupsCard.tsx` |
| Installer | Done. `queues.conf` stub; package `asterisk-moh-opsound-wav` (Ubuntu's Asterisk ships an empty `[default]` music class, so queues would hold callers in silence); `verify.sh` checks the stub, the `Queue`, `Pickup` and `PickupChan` applications and that class `default` is loaded. Dry run on dev1 shows the package and stub steps. | `installer/templates/asterisk/queues.conf`, `installer/lib/steps.sh`, `installer/verify.sh` |
| Permissions and audit | `groups.read` (administrators, technicians, read-only), `groups.write` (organization and site administrators); audit `ring_group.*`, `queue.*`, `pickup_group.*`; every write raises the Deploy changes flag. | `core/security/permissions.py` |
| Database | Migration `0009`: six tables, fourteen destination columns on `inbound_routes`, `ivr_menus` and `ivr_entries`; the ring group ↔ queue and menu ↔ group cycles use `use_alter` constraints added after both tables exist; `alembic check` clean, downgrade and upgrade exercised. | `migrations/versions/0009_ring_groups_call_queues_pickup_groups.py`, `docs/DATABASE_SCHEMA.md` |
| Documentation | `RING_GROUPS_QUEUES.md` (design and reference), API, schema, engine, installation and extensions docs, changelog, roadmap (Paging stays planned for a later milestone). | `docs/` |

## 3. Testing (veyra-dev1, 2026-10-14, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (109 files) |
| Backend pytest against PostgreSQL 18.6 | **278 passed** (11 new: pickup groups on endpoints, `*8`, `**<ext>` with the organization check, hints; ring group `ringall` with the busy check and failover, `sequential`, ring-busy, caller-ID prefix, empty group; queue context and `queues.conf` values, ring instead of music, unlimited wait, members of undeployed extensions left out; group and queue destinations in menus and routes, groups failing over to each other; value validation incl. the shared number space; ring group API CRUD, number space with extensions and the next-number suggestion, validation, in-use with a route, disabled group flagged on the route, audit and the Deploy flag; queue API CRUD with prompts, patching agents, in-use from a group failover and a menu key; pickup group CRUD, extension memberships, deletion of a member extension; organization scoping for an org admin and a read-only user; deployment writing the endpoint groups, the contexts, the pickup codes, hints and `queues.conf`, and a disabled queue leaving both files) |
| `alembic check` | No drift (migration `0009`); `downgrade 0008` and `upgrade head` clean |
| Installer `tests/test_lib.sh` | **38 passed**; `shellcheck` clean; `sudo installer/upgrade.sh --dry-run --yes` shows the `asterisk-moh-opsound-wav` install and the `queues.conf` stub |
| Frontend lint / typecheck / vitest | Clean / clean / **30 passed** (destination tests extended to the two new kinds) |
| Frontend `npm run build` | Passed; `/ring-groups`, `/ring-groups/view`, `/queues`, `/queues/view` and `/pickup-groups` exported |
| **Owner's `upgrade.sh` on dev1** | *Pending* |

### Live checks on dev1

*Pending the owner's upgrade* (§6). Plan: `tools/fakephone.py` registers
two throwaway extensions (22216, 22217); a ring group 22300 with both, a
queue 22400 with both as agents, and a pickup group with both are seeded;
calls are originated from the Asterisk CLI to the group and queue numbers
(answer order, busy skip, failover), a call to 22216 that is not answered
is picked up from 22217 with `*8` and with `**22216`; `verify.sh` must
report the queue applications and the music class.

## 4. Not verified

* With a handset: BLF lamps following a hint, BLF pickup with the `**`
  prefix on a Poly phone, hold music heard by a waiting caller, the
  position announcement wording.
* Queue behaviour with several callers waiting at once and agents in
  wrap-up (the test driver places one call at a time).

## 5. Known limitations

See [RING_GROUPS_QUEUES.md](../RING_GROUPS_QUEUES.md) §10: static agents
(no login/logout or pause codes), no live queue view or statistics until
reporting (Milestone 10), one music-on-hold class, members are extensions
only (no follow-me to external numbers), `*8` answers the longest-ringing
call, directed pickup is restricted to the organization rather than to a
pickup group, no paging, one dialplan context until Milestone 14.

## 6. Open items

* Owner: upgrade dev1 from `~/veyra` on `milestone-8` (`sudo
  installer/upgrade.sh --yes`; `frontend/out` and `companion/dist` are
  prebuilt there), then the live checks of §3 are run from the session and
  appended here; remove the test objects afterwards.
* Owner: BLF and hold-music checks with a handset (§4); the handset checks
  still open from Milestones 5 and 7.
* From Milestone 7: the M7 test objects on dev1 (extension 22215, prompt
  `m7-test-tone`, menu "M7 test menu") are still there for the owner's
  browser checks.

## 7. Proposed Milestone 9 (awaiting approval)

Device provisioning and custom templates (roadmap row 9, 0.11.0): HTTPS
delivery of phone configuration from the provisioning templates, device
registration by MAC address with an extension and a template, and hardware
validation on the Poly VVX 411/450 the district uses, including the BLF
and pickup prefix settings this milestone relies on. Alternatives if
preferred: the short 6c (Google sign-in), or a queue follow-up (agent
login/logout codes and a live queue view).

## 8. Owner decisions

* Milestone 8 chosen over 6c on 2026-10-14; `VEYRA_PUBLIC_HOST` stays
  `veyra-dev1` with the self-signed certificate until the reverse proxy and
  domain name are ready.
* Approval: *pending*.
