# Ring groups, call queues and call pickup

How Veyra rings several phones for one number, queues callers for a group
of agents, and lets a user answer a call that is ringing on a colleague's
phone. Delivered in Milestone 8 on top of the destination model of
[VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §6: ring groups and queues are new
kinds of destination and new dialable numbers; pickup groups are a
property of extensions.

## 1. Objects

| Object | Scope | Purpose |
|---|---|---|
| **Ring group** (`ring_groups`, `ring_group_members`) | Organization | A number that rings a list of extensions all at once or one after the other, then sends the call on to a failover destination |
| **Call queue** (`call_queues`, `queue_members`) | Organization | A number that holds callers with music and announcements and distributes them to agents (extensions) by a strategy; callers leave to a failover destination on timeout, when the queue is full or when no agent is available |
| **Pickup group** (`pickup_groups`, `pickup_group_members`) | Organization | A set of extensions that may answer each other's ringing calls with `*8`; membership is per extension and an extension can be in several groups |
| **Destinations** | | Inbound routes, after-hours branches, IVR keys and fallbacks, ring-group failovers and queue failovers can now also point at a ring group or a queue |

Ring groups and queues take a **number from the numbering plan**
([EXTENSIONS.md](EXTENSIONS.md)): same length and range as extensions,
unique across the organization's extensions, ring groups and queues
(per organization since Milestone 14). Users dial them from a phone,
IVR direct dialling reaches them, and the Companion directory lists them
(since Milestone 13). Everything reaches Asterisk through a generated and
deployed revision ([TELEPHONY_ENGINE.md](TELEPHONY_ENGINE.md) §4); new in
this milestone is a generated `queues.conf` and the stub that includes it.

## 2. Ring groups

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Name unique per organization; slug unique per installation and stable; context `veyra-rg-<slug>` |
| `number` | From the numbering plan; unique across extensions, ring groups and queues |
| `description` | |
| `strategy` | `ringall` (every member at once, default) or `sequential` (members in order, each for `ring_seconds`) |
| `ring_seconds` | 5–120, default 20: total ring time for `ringall`, per member for `sequential` |
| `ring_busy_members` | Default off: a member whose phone is already on a call is skipped (`DEVICE_STATE` is `INUSE`, `BUSY` or `RINGINUSE`); on, the phone gets a second call (call waiting) |
| `caller_id_prefix` | Optional, shown on the ringing phones before the caller's name (`Sales: Jane Doe`), so a user sees which group the call came in on |
| `failover_*` | A destination (§5) or hang up (default) when nobody answers, every member is skipped or the group has no members |
| `members` | Ordered extensions of the organization (table `ring_group_members`, `position`); 1–32; an extension may be in several groups |
| `external_members`, `confirm_external` | Up to ten outside numbers rung with the members (Milestone 18, [CALL_FEATURES.md](CALL_FEATURES.md) §3.4; migration `0039`): `Local` legs through the organization's follow-me outbound context, so they leave through its outbound routes; with `confirm_external` the answering party presses 1 or the leg is dropped (a mobile's voicemail cannot take the call). Rung after the extension members in `sequential`, together with them in `ringall`; busy-member skipping does not apply to them |
| `is_enabled` | A disabled group leaves the engine and is no longer a valid destination; its number does nothing until it is enabled again |

The dialplan dials the members' endpoints directly, so a member's own
voicemail never answers for the group: unanswered calls go to the group's
failover. When one member answers a `ringall` call, the other phones stop
ringing with "call completed elsewhere", which keeps missed-call lists
clean on phones that honour it.

```
[veyra-internal]
exten => 2300,1,NoOp(Veyra ring group Sales)
 same => n,Goto(veyra-rg-sales,s,1)
exten => 2300,hint,PJSIP/example-2214&PJSIP/example-2215

[veyra-rg-sales]
exten => s,1,NoOp(Veyra ring group Sales (example))
 same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])
 same => n,GotoIf($[${VEYRA_GROUP_DEPTH} > 6]?toodeep)
 same => n,Set(CALLERID(name)=Sales: ${CALLERID(name)})      ; caller_id_prefix
 same => n,Set(VEYRA_DIAL=)
 same => n,GotoIf($["${DEVICE_STATE(PJSIP/example-2214)}" : "(INUSE|BUSY|RINGINUSE)"]?m2)
 same => n,Set(VEYRA_DIAL=${VEYRA_DIAL}&PJSIP/example-2214)  ; one pair per member
 same => n(m2),GotoIf($["${DEVICE_STATE(PJSIP/example-2215)}" : "(INUSE|BUSY|RINGINUSE)"]?dial)
 same => n,Set(VEYRA_DIAL=${VEYRA_DIAL}&PJSIP/example-2215)
 same => n(dial),GotoIf($["${VEYRA_DIAL}"=""]?failover)
 same => n,Dial(${VEYRA_DIAL:1},20)                           ; ringall
 same => n,GotoIf($["${DIALSTATUS}"="ANSWER"]?done)
 same => n,Goto(failover)
 same => n(done),Hangup()
 same => n(failover),NoOp(Veyra ring group Sales: not answered)
 same => n,<failover destination lines>
 same => n(toodeep),NoOp(Veyra: groups and queues point at each other in a loop)
 same => n,Playback(pbx-invalid)
 same => n,Hangup()
```

The busy check is a `GotoIf` on `${DEVICE_STATE(PJSIP/x)}` per member
(left out when `ring_busy_members` is on); `sequential` renders one `Dial`
per member in order instead of the joined string, each preceded by the same
check and followed by the `ANSWER` test, so a call that was answered and
ended does not ring the next member. The depth guard (`__VEYRA_GROUP_DEPTH`, shared with queues) stops
groups and queues whose failovers point at each other. `hint` lines make a
phone's BLF key for the group number light while the group rings.

### 2.1 One-at-a-time strategies (issue #166)

*Built 2026-10-26 from the Metaswitch comparison (roadmap row 8).* Besides
`ringall` and `sequential`, a group can ring one member at a time in a
moving order:

| Strategy | Order |
|---|---|
| `circular` | Starts after the member who answered the last call |
| `roundrobin` | Each new call starts one member later, answered or not |
| `longest_idle` | The member who answered least recently first (never: list order) |

Each member may have its own ring time (`member_ring_seconds` on the API,
"Ring time per member" in the form; `sequential` uses it too). The dialplan
is one `While` loop over `:`-separated member and ring-time lists, so its
size grows with the members only for `longest_idle` (three lines each, to
pick the next member). State is in AstDB `veyra/rg/<org>/<slug>`: `next`
for circular and round robin, `idle_<endpoint>` (answer time) for longest
idle. The answering member's channel writes it through Dial `U()`
(`veyra-rg-answered`, which also records the last caller like
`veyra-lastcid`), so a caller who hangs up during the call still counts.
Busy members are skipped as in the other strategies unless "ring members
who are already on a call" is on. Outside numbers ring after the members.

**Skip after unanswered calls** (`skip_after_misses` 1–10, `skip_minutes`
default 15; migration 0069, 0.27.39): in the one-at-a-time strategies, a
member who let that many calls in a row ring out (`DIALSTATUS` `NOANSWER`)
is passed over until `skip_minutes` after the last of them; answering a
call clears the count (`miss_<endpoint>`, `missat_<endpoint>` in the same
AstDB family, cleared by `veyra-rg-answered`). If every member would be
skipped, none is. Busy and offline phones do not count as misses. A
`sequential` group with skipping is generated as the same loop, always
starting at the first member.

We chose the generated dialplan over Asterisk queues behind the scenes so
per-member ring times, hold music or ringing, and the caller ID prefix work
as for the other ring groups. FreePBX `memoryhunt` (cumulative) is still
imported as `sequential`.

## 3. Call queues

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | As ring groups; queue name in Asterisk `veyra-<slug>`, context `veyra-queue-<slug>` |
| `number` | From the numbering plan |
| `description` | |
| `strategy` | `ringall` (default), `rrmemory` (round robin, remembers where it left off), `leastrecent`, `fewestcalls`, `random`, `linear` (members in order) |
| `member_timeout` | Seconds each agent attempt rings, 5–60, default 15 |
| `retry_seconds` | Pause before the next agent attempt, 1–30, default 5 |
| `wrapup_seconds` | Rest for an agent after a call, 0–600, default 0 |
| `max_wait_seconds` | How long a caller may wait, 0 (unlimited) or 30–3600, default 300; then the failover |
| `max_callers` | 0 (unlimited) or 1–100; a caller beyond it goes to the failover |
| `join_when_empty` | Default off: a caller whose agents are all unavailable, paused or invalid goes straight to the failover instead of waiting (`joinempty=strict`, `leavewhenempty=strict`); on, callers wait regardless |
| `announce_position` | Default off: "You are caller number N" every `announce_frequency` seconds (`announce-position`, `announce-frequency`, with the estimated hold time off) |
| `announcement_prompt_id` | Optional prompt played to the caller once before joining ("All our lines are busy...") |
| `periodic_prompt_id`, `periodic_seconds` | Optional prompt repeated while waiting (`periodic-announce`, `periodic-announce-frequency`, 15–600, default 60) |
| `music` | `default` (the music-on-hold class the installer provides, §7) or `ring` (the caller hears ringing instead of music) |
| `failover_*` | A destination (§5) or hang up (default) when the caller times out, the queue is full, no agent is available (`join_when_empty` off) or the queue has no members |
| `members` | Agents: extensions with a `penalty` 0–9 (lower is tried first; agents with a higher penalty only ring when every lower one is busy or absent) in `queue_members`; 0–64; an extension may be an agent of several queues |
| `is_enabled` | A disabled queue leaves `queues.conf` and the dialplan |

Agents are static members: `member => PJSIP/<endpoint>,<penalty>,<name>,PJSIP/<endpoint>`
with the endpoint as the state interface, so the queue sees who is on a
call (`ringinuse=no`: an agent already talking is not offered a second
caller). Agent login/logout and pause codes, a live queue dashboard and
queue statistics are later milestones (§10).

Generated `queues.conf` (reloaded with `app_queue.so`):

```
[general]
persistentmembers=no
autofill=yes
shared_lastcall=yes
monitor-type=

[veyra-support]              ; Support (example)
strategy=rrmemory
timeout=15
retry=5
wrapuptime=0
maxlen=0
ringinuse=no
joinempty=strict
leavewhenempty=strict
musicclass=default
announce-position=no
announce-holdtime=no
periodic-announce=/var/lib/veyra/prompts/example/please-hold
periodic-announce-frequency=60
member => PJSIP/example-2214,0,Front Office,PJSIP/example-2214
```

Dialplan:

```
[veyra-internal]
exten => 2400,1,NoOp(Veyra queue Support)
 same => n,Goto(veyra-queue-support,s,1)

[veyra-queue-support]
exten => s,1,NoOp(Veyra queue Support (example))
 same => n,Set(__VEYRA_GROUP_DEPTH=$[0${VEYRA_GROUP_DEPTH} + 1])
 same => n,GotoIf($[${VEYRA_GROUP_DEPTH} > 6]?toodeep)
 same => n,Answer()
 same => n,Playback(/var/lib/veyra/prompts/example/lines-busy)   ; announcement prompt
 same => n,Queue(veyra-support,t,,,300)                            ; r instead of t for music=ring; timeout = max_wait
 same => n,NoOp(Veyra queue Support left: ${QUEUESTATUS})
 same => n,<failover destination lines>
 same => n(toodeep),...
```

`Queue()` returns to the dialplan with `QUEUESTATUS` (`TIMEOUT`, `FULL`,
`JOINEMPTY`, `LEAVEEMPTY`, `JOINUNAVAIL`, `LEAVEUNAVAIL`) in every case
where the caller was not connected, and the failover handles all of them
alike; the status is logged for diagnosis. The `t` option lets the agent
transfer the caller; `n` is not set, so Asterisk retries agents until the
timeout.

## 4. Call pickup

### 4.1 Pickup groups

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Name unique per organization; slug unique per installation (it is the Asterisk named group) |
| `description` | |
| `members` | Extensions of the organization (`pickup_group_members`); 1–64 |

Every member may answer a call ringing on any other member. The generated
endpoint section carries the extension's groups as both
`named_call_group` and `named_pickup_group` (comma-separated slugs), so
Asterisk's `Pickup()` with no argument answers the longest-ringing call in
any group the caller shares with the ringing phone. An extension in no
group cannot be picked up with `*8` and cannot pick up with it.

### 4.2 Feature codes and BLF

```
[veyra-features]
exten => *8,1,NoOp(Veyra group pickup by ${CALLERID(num)})
 same => n,Pickup()
 same => n,Hangup()
; directed pickup: one entry per extension of the installation
exten => **2214,1,NoOp(Veyra directed pickup of 2214 by ${CALLERID(num)})
 same => n,GotoIf($["${VEYRA_ORG}"!="example"]?denied)
 same => n,PickupChan(PJSIP/example-2214,,p)
 same => n,Hangup()
 same => n(denied),Playback(pbx-invalid)
 same => n,Hangup()

[veyra-internal]
exten => 2214,hint,PJSIP/example-2214      ; one per extension
```

* **Group pickup `*8`**: answers a ringing call on another phone of one of
  the caller's pickup groups (§4.1). If nothing is ringing, Asterisk plays
  the invalid tone.
* **Directed pickup `**<extension>`**: answers the call ringing on that
  specific phone, whether it was called directly or as a ring-group or
  queue member (`PickupChan` matches the ringing channel by endpoint name,
  which the extension's dialplan location does not). It works between any
  two extensions of the same organization; pickup-group membership is
  not required. Extensions of other organizations are refused.
* **BLF**: every extension and ring group gets a `hint`, so a phone's busy
  lamp field shows idle, ringing and in-use states (the endpoint's
  subscription context is `veyra-internal`). Phones with a *BLF pickup*
  feature dial a prefix plus the monitored extension when its lamp blinks;
  set that prefix to `**` in the phone (and in the provisioning templates
  of Milestone 9).

Both applications are core modules (`app_directed_pickup.so`), loaded by
default.

## 5. Destinations

`DestinationType` gains `ring_group` and `queue`; the shape becomes
`{type, extension_id, ivr_id, ring_group_id, queue_id}` everywhere a
destination is stored or returned:

| Where | Columns added |
|---|---|
| `inbound_routes` | `destination_ring_group_id`, `destination_queue_id`, `after_hours_ring_group_id`, `after_hours_queue_id` |
| `ivr_menus` | `timeout_ring_group_id`, `timeout_queue_id`, `invalid_ring_group_id`, `invalid_queue_id` |
| `ivr_entries` | `destination_ring_group_id`, `destination_queue_id` |
| `ring_groups`, `call_queues` | `failover_type`, `failover_extension_id`, `failover_ivr_id`, `failover_ring_group_id`, `failover_queue_id` |

All foreign keys are `ON DELETE SET NULL`, so a deleted target leaves the
reference flagged (`missing`) rather than broken, as before; deleting a
ring group or queue that something points at is refused (`409
ring_group_in_use`, `409 queue_in_use`), and the API reports `in_use_by`.
The resolver labels them `Ring group: Sales (2300)` and `Queue: Support
(2400)`; the snapshot carries `{type: "ring_group", ring_group: <slug>}` /
`{type: "queue", queue: <slug>}` and `missing` when the target is gone or
disabled; the generator renders `Goto(veyra-rg-<slug>,s,1)` /
`Goto(veyra-queue-<slug>,s,1)`. IVR direct dialling lists ring-group and
queue numbers of the organization beside its extensions.

## 6. Permissions and API

| Permission | Default roles |
|---|---|
| `groups.read` | Organization and site administrators, technicians, read-only users |
| `groups.write` | Organization and site administrators |

Both cover ring groups, queues and pickup groups.

```
GET    /ring-groups?organization_id=&q=        with members, failover, in_use_by, problems
POST   /ring-groups                            {organization_id, name, number, strategy?, ring_seconds?, ring_busy_members?, caller_id_prefix?, failover?, members: [extension_id, ...], is_enabled?}
GET    /ring-groups/{id}
PATCH  /ring-groups/{id}                       any of the above (members replaces the list)
DELETE /ring-groups/{id}                       409 ring_group_in_use

GET    /queues?organization_id=&q=
POST   /queues                                 {organization_id, name, number, strategy?, member_timeout?, retry_seconds?, wrapup_seconds?, max_wait_seconds?, max_callers?, join_when_empty?, announce_position?, announce_frequency?, announcement_prompt_id?, periodic_prompt_id?, periodic_seconds?, music?, failover?, members: [{extension_id, penalty}], is_enabled?}
GET    /queues/{id}      PATCH /queues/{id}      DELETE /queues/{id}      409 queue_in_use

GET    /pickup-groups?organization_id=&q=
POST   /pickup-groups                          {organization_id, name, description?, members: [extension_id, ...]}
GET    /pickup-groups/{id}   PATCH /pickup-groups/{id}   DELETE /pickup-groups/{id}

GET    /extensions/{id}                        gains ring_groups, queues, pickup_groups: [{id, name, number?}]
```

Numbers are validated against the numbering plan and for uniqueness
across extensions, ring groups and queues under the same advisory lock
the extension API uses (`409 number_in_use`); `GET /extensions/next-number`
skips group numbers too. Members must be extensions of the same organization (a disabled one is
accepted, left out of the engine and flagged); prompts must belong to the
organization. `problems` names what stops a group from working (no
members, a missing failover target, a disabled member). Audit: `ring_group.create/update/delete`,
`queue.create/update/delete`, `pickup_group.create/update/delete`; every
write raises the Deploy changes flag (pickup groups and members change
`pjsip.endpoints.conf`).

## 7. Installer

* Stub `/etc/asterisk/queues.conf` (`#tryinclude veyra/queues.conf`),
  installed like the other stubs with the package sample backed up;
  `verify.sh` checks it. New managed file `queues.conf` in the include
  directory, reload scope `app_queue.so`.
* Package `asterisk-moh-opsound-wav` joins the package list: Ubuntu's
  `asterisk` ships a `[default]` music-on-hold class pointing at the empty
  `moh` directory of its data directory, so queues would hold callers in
  silence. The package fills it with the Open Sound license-free music;
  `verify.sh` checks that class `default` is loaded (`moh show classes`).
  When the package arrives while Asterisk is already running (an upgrade),
  the class is missing because it only registers when its directory has
  files, and `moh reload` does nothing while `musiconhold.conf` is
  unchanged; the Asterisk step therefore unloads and loads
  `res_musiconhold.so` when `moh show classes` lacks `Class: default`.
  Custom hold music sets arrived in Milestone 9c
  ([PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §3.2); the stub
  `/etc/asterisk/musiconhold.conf` keeps `[default]` and includes them.
* No module changes: `app_queue`, `app_directed_pickup` and
  `res_musiconhold` are core modules already loaded; `verify.sh` checks
  that the `Queue` and `Pickup` applications are registered.

## 8. Interface

* Telephony → **Ring Groups**: list (number, name, strategy, members,
  failover, problems), create dialog, group page with the member picker
  (ordered, add from the organization's extensions, move up and down) and
  an "as deployed" summary.
* Telephony → **Call Queues**: list, create dialog, queue page with the
  agent picker (extension and penalty), announcements (prompts of the
  organization), behaviour and failover.
* Telephony → **Pickup Groups**: list, create and edit dialog with the
  member picker.
* The extension page gets a **Call groups** card: the ring groups, queues
  and pickup groups the extension belongs to, linking to them.
* The destination picker offers *Ring group* and *Queue* wherever a
  destination is chosen (inbound routes, IVR keys and fallbacks, group and
  queue failovers; a group's own failover may not point at itself).
* Nav: the planned entries for Ring Groups and Call Queues become real
  pages; Paging stays planned.

## 9. Testing

Backend tests render the generated files from snapshots (groups with
both strategies, the busy check, failovers, loop guard; queues.conf
values and member lines; pickup groups on endpoints, `*8`, `**<ext>` and
hints; typed destinations in routes and menus) and exercise the API
(CRUD, number uniqueness across tables, member validation, in-use rules,
organization scoping, deployment producing `queues.conf`). On dev1,
`tools/fakephone.py` registers several phones at once (one process per
endpoint, different `--local-port`), so a ring group can be called from a
third phone and the answer order observed; a queue is checked the same way
with one agent busy; pickup is checked by calling a phone that does not
answer and dialling `*8` and `**<ext>` from another.

## 10. Known limitations

* Queue agents are static: no login/logout or pause codes, no dynamic
  membership from the browser; a live queue view and statistics come with
  reporting (Milestone 10).
* Hold music sets (per organization, queue and ring group) are described
  in [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §3.2; streamed music is
  later.
* Ring group members are extensions only; external numbers (follow-me to a
  mobile) are later.
* `*8` answers the longest-ringing call in the caller's groups; there is
  no choice between several ringing calls.
* Directed pickup is restricted to the caller's organization; since 0.27.11
  (#138, migration `0062`) an organization can limit it to phones sharing a
  pickup group with the ringing phone (Organizations → "Answer another
  phone's call"; `organizations.directed_pickup` = `group`: the `**<ext>`
  entry checks `VEYRA_EXT` against the peers before `PickupChan`).
* Paging and intercom are not part of this milestone.
* Since Milestone 14 group and queue numbers are unique per organization,
  like extension numbers, and each organization has its own contexts
  ([MULTI_TENANCY.md](MULTI_TENANCY.md)).
