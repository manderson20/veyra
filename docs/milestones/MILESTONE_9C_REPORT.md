# Milestone 9c Report — Paging and Recordings

Branch `milestone-9c` (from `main` at 0.12.0). Design:
[PAGING_RECORDINGS.md](../PAGING_RECORDINGS.md). Status: **built, awaiting
the owner's upgrade of dev1 and approval** (to be released as 0.13.0).

## 1. Scope (owner requests of 2026-10-14)

* Paging zones per building (several per building if wanted), with the
  multicast address, port and Poly group number; Poly phones paged
  directly, in step with the multicast speakers, without the relay speaker.
* Uploading recordings: bells, IVR prompts, shared voicemail inboxes.
* Bell schedules driven by a calendar (Google Calendar today, any calendar
  later): an event's start rings a page with a recording.
* Hold music.
* Messages to the AND clocks like Clockwise, as a module that can be
  installed or left out.
* Default sounds that may be used legally, and external triggers such as a
  door held open.

## 2. Results

* **Audio library** (Telephony → Audio): recordings classed as menu
  prompt, bell, announcement, greeting or hold music, with licence and
  credit; MP3, OGG, FLAC and M4A converted by `ffmpeg` (migration `0013`).
* **Paging** (Telephony → Pages, Paging Zones): zones with numbers from
  the shared number space and a policy of who may page; pages combining
  zones with live audio or a recording, pre-tone, repeats and a Poly
  priority, startable by dialling, from the interface and from the API
  (door alarms and other systems); a page log. The **page sender**
  (`veyra-pager`) emits the speakers' multicast after the Poly phones'
  buffering delay together with the Poly group-page stream so both play
  in step (migration `0014`).
* **Calendars and bell schedules** (Telephony → Calendars, Bell
  Schedules): iCal feeds (Google's secret address; encrypted at rest)
  fetched every few minutes, recurring events expanded; a schedule rings a
  page at the start or end of matching events, once per event, within a
  tolerance; next and last rings, "Ring now" (migration `0015`).
* **Shared voicemail inboxes**: their own number and name, member phones
  whose message lamp follows them, a destination for routes, menus and
  failovers (migration `0016`).
* **Hold music sets** (Telephony → Hold Music): ordered or shuffled sets
  from the library for the organization's held calls, call queues and ring
  groups (migration `0017`).
* **AND Clock Messages module** (`veyra.and-clocks`, installed under
  Modules): clocks with groups and reachability checks; messages to all
  clocks, a group or one clock, now or at a set time, with colour,
  flashers, priority and display time; a log; text with the bells
  ("Period 2"). The request that hands a message to a clock is entered
  once under Clock Delivery (see §6).
* **Module framework 1.1**: periodic tasks in the worker, encrypted module
  secrets, the `bell.rang` event; release modules are signed by the
  installer with the server's own key so they can be installed in
  production.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (152 files) |
| Backend pytest | **322 passed** (9c added audio, paging, sender, calendars and bells, shared inboxes, hold music, and the clock module: markup and request escaping, sending to a local test clock with sign-in, scheduled and bell messages through the worker task, reachability, the worker loading and unloading modules) |
| `alembic check` | No drift (migrations `0013`–`0017`) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **34 passed** / passed |
| Installer library tests | **45 passed** |
| Module signing | Key generation, signing and verification as `official` checked with the CLI |
| **Owner's `upgrade.sh` on dev1** | 0.12.0-cb76120267 → **0.12.0-82f5a0263d** (2026-10-15 00:13 UTC): migrations to `0017`, `musiconhold.conf` stub installed (original backed up), module signing key created and 1 module signed, all verify checks OK incl. `modules-signed` and `data-dir:moh`. Afterwards: `veyra modules list` shows `veyra.and-clocks` available with trust `official`; Asterisk still has the built-in `default` hold music class; worker restarted cleanly |

## 4. Not verified

* Any of it with hardware: Poly phones and speakers paged together, a
  bell from a real calendar, an AND clock showing a message.
* The Poly group-page header: the sender sends plain RTP to the Poly
  address until a capture from the phones confirms the format
  (`tools/poly-capture.py`).
* The AND clocks' web request (see §6).

## 5. Known limitations

* The clock module's pages can add and delete rows but not edit them (the
  module view type allows no editing yet; roadmap row 11).
* A scheduled clock message missed by more than an hour is logged as not
  sent.
* Default sounds (§3.1 of the design: synthesized tones and CC0 sets) are
  not generated yet; recordings are uploaded.

## 6. Open items

* Owner: try the new pages on dev1 (shared inbox, hold music set,
  install AND Clock Messages under Modules and add a clock).
* **Owner: AND clock capture.** On a clock's web page, with the browser's
  developer tools on the Network tab, send a test message and note the
  request (method, path, body, sign-in); steps in
  [the module README](../../modules/veyra-and-clocks/README.md) §2. Enter
  it under Modules → Clock Delivery, or send it with the password and
  site details removed and it becomes a ready-made setup.
* **Owner: Poly capture**: `python3 -I tools/poly-capture.py --out
  poly-page.txt` on the phones' network while one Poly pages another.
* From Milestone 9: hardware checks with the VVX phones and the handset
  checks of Milestones 5, 7 and 8.

## 7. Next milestone

9d — Firewall and phone trust (0.14.0), per the owner's "continue in
order".

## 8. Owner decisions

* 2026-10-14: scope from the owner's messages (§1); several zones per
  building allowed; the AND clocks feature is a module that can be
  installed or uninstalled.
* 2026-10-15: voicemail transcription discussed as a concept only
  (on-server speech recognition preferred for privacy; not scheduled).
