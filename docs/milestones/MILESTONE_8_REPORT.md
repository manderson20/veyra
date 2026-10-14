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
| **Owner's `upgrade.sh` on dev1** | 0.9.0-0e88091a91 → 0.9.0-7fefc4b534: backups taken, `asterisk-moh-opsound-wav` installed, migration `0009` applied, `queues.conf` stub installed (sample backed up), Asterisk reloaded, services restarted. Verification failed on one check, `engine-moh`: Asterisk had started with the empty `moh` directory, so the `default` class had never registered, and `moh reload` is a no-op while `musiconhold.conf` is unchanged. Unloading and loading `res_musiconhold.so` fixed it; the installer now does that itself when the class is missing (commit after 7fefc4b) and `verify.sh` names the same fix. `sudo installer/verify.sh` afterwards: all checks OK |

### Live checks on dev1

Run from the session after the upgrade with `tools/fakephone.py`
registering two throwaway extensions (22216 "A", 22217 "B"), seeded
together with ring group 22300 (A and B), queue 22400 (A penalty 0, B
penalty 1, `rrmemory`, agent timeout 10 s, retry 2 s, hold music) and a
pickup group with both; calls were originated from the Asterisk CLI
(`channel originate Local/<number>@veyra-internal`) and watched through
`core show channels`, `queue show`, a temporary verbose logger channel,
`queue_log` and the fake phones' logs. All objects were removed afterwards
and the configuration redeployed (dev1 is back to extensions 22214 and
22215).

| Check | Result |
|---|---|
| Deployment | Revision deployed `extensions.conf`, `pjsip.endpoints.conf` and `queues.conf`; both endpoints show `named_call_group`/`named_pickup_group` `m8-test-pickup`; `queue show` lists both agents with their penalties; hints `22216`, `22217` and `22300` (both members) exist and follow the phones |
| Ring group, ring all | Both phones rang at once; A answered after 3 s, B received CANCEL; caller bridged with A |
| Ring group, busy member skipped | With A on a call (`DEVICE_STATE` in use), a call to 22300 rang only B, which answered |
| Ring group, sequential | Strategy changed to sequential with 5 s per member and failover to the queue: A rang 5 s and was cancelled, then B rang and answered |
| Ring group, failover | Same group with B's phone stopped: A rang 5 s, B failed at once, the dialplan went to `failover` and into the queue context (`Goto(veyra-queue-m8-test-queue,s,1)`) |
| Queue | Caller answered and queued; verbose log shows `Started music on hold, class 'default'` on the caller, then `Called PJSIP/…-22216`, A answered after 4 s, `Stopped music on hold`, bridge; `queue_log` has `ENTERQUEUE`, `CONNECT`, `COMPLETECALLER` |
| Queue, agent not answering | A set to answer after 12 s (longer than the 10 s agent timeout): A was rung 10 s, 2 s pause, rung again, until the caller hung up (`RINGNOANSWER` twice, `ABANDON`); B (penalty 1) was never rung, as documented: a higher penalty only rings when every lower-penalty agent is busy or absent, not when they do not answer |
| `*8` group pickup | Call to A ringing (A set not to answer); B originated into `*8@veyra-features`: `Pickup()` took the call (`app_directed_pickup: pickup PJSIP/…-22216 attempt by PJSIP/…-22217`), A received CANCEL, B bridged with the caller |
| `**22216` directed pickup | Same with `**22216`: the organization check passed (`GotoIf("0?denied")`), `PickupChan(PJSIP/…-22216,,p)` took the call, A cancelled, B bridged |
| `verify.sh` | `engine-stub:queues.conf`, `engine-app:Queue/Pickup/PickupChan` and `engine-moh` all OK after the installer fix |

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

* Owner upgraded dev1 on 2026-10-14 (§3); the live checks are done and the
  test objects removed. The installer fix for the music-on-hold class is
  committed on `milestone-8` after the release the owner installed; it
  takes effect on the next upgrade (dev1 itself is already fixed).
* Owner: BLF and hold-music checks with a handset (§4); the handset checks
  still open from Milestones 5 and 7.
* From Milestone 7: the M7 test objects on dev1 (extension 22215, prompt
  `m7-test-tone`, menu "M7 test menu") are still there for the owner's
  browser checks.

## 7. Proposed Milestone 9 (approved 2026-10-14, with the owner's requirements in §8)

Device provisioning and custom templates (roadmap row 9, 0.11.0): HTTPS
delivery of phone configuration from the provisioning templates, device
registration by MAC address with an extension and a template, and hardware
validation on the Poly VVX phones in use, including the BLF
and pickup prefix settings this milestone relies on. Alternatives if
preferred: the short 6c (Google sign-in), or a queue follow-up (agent
login/logout codes and a live queue view).

## 8. Owner decisions

* Milestone 8 chosen over 6c on 2026-10-14; `VEYRA_PUBLIC_HOST` stays
  `veyra-dev1` with the self-signed certificate until the reverse proxy and
  domain name are ready.
* Upgrade of dev1 run by the owner on 2026-10-14; the one failed verify
  check (`engine-moh`) was fixed in place and in the installer.
* Approved 2026-10-14 ("You have my approval to proceed!"); released as
  0.10.0. With the approval the owner set requirements for Milestone 9:
  group device brands and models (most share settings), yet separate
  templates by use, e.g. one per building differing only in multicast
  paging; multicast paging zones for the phones so they page in sync with
  the multicast speakers (today a relay pages the phones and they lag the
  speakers); Poly paging groups as an option.

## Addendum (2026-10-14 14:34 UTC)

The owner upgraded dev1 from `~/veyra-release` to **0.10.0-980d95b0dd**:
backups taken, no package changes, schema current (0009), Asterisk
configuration unchanged (no reload), services restarted, all verify
checks OK including `engine-moh`, old releases pruned to three.
