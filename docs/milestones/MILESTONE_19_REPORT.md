# Milestone 19 Report — Call-flow features

Branch `milestone-19` (from `main` at 0.24.2). Design:
[CALL_FEATURES.md](../CALL_FEATURES.md) §4. Status: **built 2026-10-18,
awaiting the owner's live checks on dev1; released as 0.25.0 on the
owner's go**. Issues: #19, #20, #21, #22, #25, #26, #27, #28, #29 under
"Call flow features"; progress comments on each. Pull request #87.

## 1. Scope (roadmap row 19)

The second half of the FreePBX gap work ([FREEPBX_GAP_ANALYSIS.md](../FREEPBX_GAP_ANALYSIS.md)
§4 item 1, §3.5): call parking with BLF, conference rooms, announcements,
dial-by-name directory, call-flow day/night toggles, time-condition
override, caller blacklist, queue dynamic agents with log-in/pause and the
break-out menu, in-call transfer and on-demand recording codes.

## 2. Results

* **Destination kinds** (§4.4): `announcement`, `conference`, `call_flow`
  and `directory` join the shared destination shape on every holder
  (inbound routes, IVR menus and keys, ring groups, queues, announcements,
  call flows, parking lots, the block list policy); the pickers in the
  interface offer them everywhere. A pre-existing bug fell out: the inbound
  route form dropped shared-inbox targets.
* **Announcements** (#21, §4.1): Telephony → Announcements plays a
  recording, optionally skippable by any key or replayable by a chosen key,
  then continues to a destination; announcements chain with a loop guard.
  Migration 0042.
* **Dial-by-name directory** (#22, §4.2): `Directory()` over the
  organization's voicemail boxes, first or last name, one context per
  namespace; a destination without an object.
* **Conference rooms** (#20, §4.3): Telephony → Conference Rooms with a
  dialable number (BLF `confbridge:` hint), participant and administrator
  PINs (encrypted, write-only, key-rotation registered), participant limit,
  join/leave announcements, hold music while alone, wait for the
  administrator, recording to `<recordings>/conferences`, and the in-room
  key menu; new managed file `confbridge.conf` with its installer stub.
* **Engine switches** (§4.5, §4.6): a shared mechanism for named on/off
  states in the engine store behind a BLF lamp, written live by the API,
  flipped by phones through feature codes that report back with
  `UserEvent(VeyraSwitch)`, reconciled by the worker every pass.
* **Call flows** (#25, §4.5): Telephony → Call Flows, a normal and an
  override destination, `*28<index>` with optional PIN and BLF, a switch on
  the list and page, `POST /call-flows/{id}/state`; takes effect at once.
  Migration 0043.
* **Time-condition override** (#26, §4.6): `*27<index>` inverts the current
  schedule state until the schedule changes (the worker clears temporary
  overrides), dialled again it clears; the page forces open or closed,
  temporary or permanent; routes consult the override before `GotoIfTime`;
  the list shows what callers get.
* **Call parking** (#19, §4.7): Telephony → Parking, lots with a park
  extension, slot range with BLF hints, timeout that rings the parker back
  and then a destination, courtesy tone; new managed file `res_parking.conf`;
  lot numbers protected in the number space. Migration 0044.
* **Blocked callers** (#27, §4.8): Telephony → Blocked Callers, numbers
  refused on every inbound route (engine store, live), withheld-number
  rule, destination for refused calls or "not in service", hit counts, CSV
  import/export, `*30`/`*31`/`*32`. Migration 0045.
* **Queue dynamic agents** (#28, §4.9): members marked "Logs in" join at
  login: `*45`, `*45<queue>`, `*46` pause, `*47<queue>` waiting count, BLF
  `*45*<ext>`/`*46*<ext>`, the queue page's Agents card, an API state
  endpoint; `persistentmembers=yes` and a worker sync from `queue show`.
  Migration 0046.
* **Queue break-out menu** (#29, §4.10): a queue names an IVR menu whose
  keys callers press while waiting (`context=`).
* **In-call codes** (§4.11): `*1` on-demand recording (filed with the call
  record), `*2` attended and `##` blind transfer through `features.conf`
  (new managed file, `features reload`), `Dial` options from globals.
* **Feature codes**: eleven new keys with FreePBX-style defaults,
  adjustable and allowable per class of service.

## 3. Testing (final tree, 2026-10-18)

Backend: full suite green on every commit (new files `test_api_callflow.py`,
`test_generator_callflow.py`, `test_switches.py`, `test_blacklist.py`,
`test_agents.py`, `test_incall.py`). Frontend: 53 vitest tests, typecheck,
lint and build clean. Installer: `test_lib.sh` 70 tests, shellcheck clean.
mypy clean. CI green on pull request #87 for every increment.

### Live checks on dev1

Pending the owner's installation of the milestone build (schema 0046):
announcements and the directory from a route, a conference room with PINs
from two phones, a call-flow toggle and a time-condition override from a
phone key (BLF), parking a call by transfer and retrieving it from a slot,
blocking a caller with `*32` and a refused call, a dynamic agent logging
in with `*45` and pausing, the break-out key during queue hold, `*1`
recording and `##`/`*2` transfers during a call.

## 4. Not verified

Phone-side behaviour of the applicationmap feature (`*1`) and DTMF
transfers on the Poly VVX; `Directory()` name matching against real
voicemail box names; ConfBridge recording file names; parking hints on a
line key (the park key type is #40); multi-organization isolation of the
new contexts beyond the automated checks.

## 5. Known limitations

Conference recordings are written but not listed on the Call Recording
page; the directory has no custom entries or operator key; `*32` records
only outside calls that reached the phone directly (not through a group or
queue); refused calls are counted on the block list, not in the call
history; agent state and break-out exits are not yet in the queue reports;
in-call codes are not guarded by class of service; PINs appear in clear in
the generated dialplan (as voicemail PINs do in voicemail.conf).

## 6. Open items

Owner upgrade and live checks (§3); the park line-key type (#40) and the
queue-report additions; the owner's notes filed as #84, #85, #86.

## 7. Next milestone

Milestone 20, the user portal (#31–#33, #60, #75, #77, #78).

## 8. Owner decisions

None blocking. Approval of this milestone bumps the version to 0.25.0 and
turns the changelog's Unreleased section into the release entry; 0.25.0
is the first release installed from System → Updates.
