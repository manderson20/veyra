# Paging and Recordings (Milestone 9c)

Design for Milestone 9c (roadmap row 9c, 0.13.0). Owner requests of
2026-10-14, in the order they arrived:

1. Phones page in sync with the multicast speakers: the Poly phones only
   hear Poly group pages, the speakers only plain multicast, and today a
   relay pages the phones separately, so they lag.
2. "A way to upload recordings, say for a bell schedule, or for the IVR,
   or shared voicemail inboxes."
3. Bell schedules driven by a calendar: "the phone system currently checks
   the Google Calendar for events every few minutes and the start of an
   event is used to trigger a bell tone. The bell tone is just a page with
   a recording … then we create a calendar in the system that is linked to
   the Google calendar … configured to use a page that is already created
   … it may not always be a Google calendar."
4. Messages to the AND clock displays "similar to Clockwise", as an
   installable module, because not every installation has such devices.

Sections marked *(spike)* need a measurement on the owner's equipment
before the code is final; the rest is implementable from this document.

## 1. Objects

| Object | Table | Purpose |
|---|---|---|
| **Paging zone** | `paging_zones` (M9) | gains `number` (dialable from phones, from the numbering plan's shared space), `volume`, `max_seconds`, `allowed_extensions` policy (§2.4) |
| **Page** | `pages` | A named action: which zones, what audio (live from the caller, or a recording), the Poly priority, and an optional pre-tone. Dialable by number and triggered by bells |
| **Recording** | `prompts` (M7), extended | The audio library: `kind` ∈ prompt, bell, announcement, greeting; MP3 and WAV accepted; used by IVR menus, queues, pages and voicemail greetings |
| **Calendar** | `calendars` | An external calendar subscription: an iCal/ICS URL (Google Calendar's "secret address" or any feed), polled every few minutes; events are cached in `calendar_events` |
| **Bell schedule** | `bell_schedules` | Links a calendar to a page: every event start (or a named event pattern) triggers the page; with a tolerance window and an on/off switch |
| **Shared voicemail inbox** | `voicemail_boxes` extended | A box with no extension: its own number, name, PIN, email, and member extensions whose lamps light |
| **AND clock message** | module `veyra.and-clocks` | Text and alert messages to Advanced Network Devices clocks and signs (§6) |

## 2. Paging in sync: the Veyra page sender

### 2.1 Why Asterisk alone is not enough

Asterisk's `Page()` with `MulticastRTP/basic/<group>:<port>` sends plain
multicast RTP, which the AND and Algo speakers play. The Poly phones ignore
it: they listen only for Poly's group-page packets, whose header carries
the group number, and they buffer about 200 ms before playing (Algo's
integration note sets a 200 ms delay on its adapter for that reason). So
one source must emit **both** formats, with the plain stream delayed by
the phones' buffer, and that source is Veyra's.

### 2.2 The sender

A small service, `veyra-pager` (same code base, `veyra pager` command, a
systemd unit like the deployer):

* Listens for RTP on `127.0.0.1:<base port + zone index>` (unicast, one
  port per zone, `MulticastRTP/basic/127.0.0.1:<port>` from Asterisk).
* For every packet received it emits (a) the Poly group-page packet to the
  organization's Poly address and port with the zone's group number, and
  (b) the plain RTP packet to the zone's speaker multicast group after
  `poly_delay_ms` (default 200, per organization, tunable in the Paging
  settings) so phones and speakers play together.
* Rewrites nothing else: codec stays G.711 µ-law as Asterisk sends it
  (G.722 later; the zone's codec field then applies).
* Zones with `kind = emergency` or `priority` set the matching Poly flag so
  the phones interrupt calls, as the Poly settings in the phones allow.
* Reads its zone table from the generated `paging.json` in the engine's
  include directory (written by the deployer, so a deployment updates the
  sender without a restart; it watches the file).

*(spike)* The Poly group-page wire format is not documented. Before the
sender is finished, a packet capture of one Poly VVX paging another (the
owner's two phones, `tcpdump` on a mirrored port or on the server joined to
`224.0.1.116`) gives the header layout; Grandstream, Algo and CyberData all
implement it, so it is stable across firmware. The capture, the parsed
header and the test vectors go into `backend/tests/data/poly-page/` with
no identifying data.

### 2.3 Dialplan

* `veyra-paging` context: one `exten` per zone number →
  `Set(VEYRA_PAGE_ZONE=<slug>)`, organization check, optional pre-tone
  (`Playback(beep)`), then `Page(MulticastRTP/basic/127.0.0.1:<port>,
  i, <max_seconds>)` (`i` ignores attempts to forward). Hangup ends the
  page; `max_seconds` caps it.
* A page with several zones dials every zone's port in one `Page()` call
  (`&`-joined), so the sender emits each zone's groups.
* A page with a recording: the caller hears nothing; the dialplan plays
  the recording into the page (`Page(...,qA(<file>))` is not usable, so
  the sender's "play" mode (§2.5) is used instead).

### 2.4 Who may page

A zone (and a page) carries `allowed`: `everyone` in the organization
(default), `extensions` (a member list), or `administrators` (pages
started from the interface or bells only). The dialplan checks membership
with a generated list; the interface shows the rule.

### 2.5 Pages started by Veyra (bells, interface)

The API `POST /pages/{id}/send` (permission `paging.send`) and the bell
scheduler originate `Local/play-<page>@veyra-page-play` whose far leg does
`Playback(<recording>)` while the near leg runs the zone's `Page()` — the
standard Asterisk pattern for announcements — through ARI's originate with
`extension`/`context`. A live page from the interface is a later feature
(it needs browser audio, Milestone 6b's Companion could carry it).

### 2.6 Triggers from outside: door alarms and other systems

Pages with a recording are the building block for alerts from other
systems (the owner's example: a door-access controller reporting a door
held open too long plays a sound on the speakers of that area):

* **Webhook**: `POST /pages/{id}/send` with an **integration token** (a
  bearer token scoped to `paging.send` for one organization, created on
  the Integrations card; the Companion tokens of Milestone 6b already give
  the token mechanism). The door controller, a building-automation
  system, or a small script calls it; the body may name the zones and the
  recording to override the page's defaults and a `repeat` count.
* **Dial-in**: a contact-closure device or an ATA dials the page's number
  (§2.3), so controllers with a relay output or a SIP line work without
  any API, through an Algo 8301's input or a door station's relay.
* **Events to actions** (later): a general rule engine ("when X, do Y")
  arrives with Integrations (roadmap row 13); 9c ships the two triggers
  above and the page log that both write to.

## 3. Recordings: the audio library

* `prompts` becomes the library (`kind`, `tags`); the Prompts page becomes
  **Audio** (Telephony → Audio) with filters by kind and use; the existing
  prompt uses (IVR, queues, `*95` recordings) continue unchanged.
* Upload accepts **WAV and MP3** (and OGG/FLAC when available). Decoding
  MP3 needs `ffmpeg` (Ubuntu package, added by the installer; the installer
  degrades to WAV-only with a warning when the package is missing). Output
  stays 8 kHz mono WAV for Asterisk; a 16 kHz copy is kept for G.722 pages
  later.
* Uses are listed on the recording ("Bell: first period, Page: all call").
  In-use recordings cannot be deleted.

### 3.1 Default sounds shipped with Veyra

The owner asked for generic sounds that can be included legally to build
default options (bells, chimes, alerts, a door-held-open warning). Two
sources are safe to bundle in an AGPL product:

* **Synthesized tones**: bells, chimes, two-tone alerts and attention
  signals generated by a script in the repository (`tools/gen-sounds.py`,
  pure tone synthesis, deterministic). They are ours, need no licence
  text, and can be regenerated in any length or pitch.
* **CC0 recordings**: a small curated set from Freesound (filtered to the
  CC0 licence, which waives attribution and allows any use), stored with
  a `CREDITS.md` naming each source anyway. Freesound's API also allows a
  later "import from Freesound" search in the library, limited to CC0 and
  CC BY (with the attribution recorded on the recording).

Not suitable for bundling: the BBC sound effects archive (non-commercial
licence), Mixkit and Pixabay packs (their licences forbid redistribution
as part of a sound collection), and attribution-only packs unless the
credit is shown in the product. Asterisk's own sound sets (`asterisk-core-sounds`,
`asterisk-extra-sounds`, CC BY-SA 3.0) are already installed by the
package and may be referenced by the dialplan, but their share-alike
terms mean they are not copied into Veyra's library.

The shipped set lives in `provisioning/../sounds/` (name to be settled
with the installer: `/opt/veyra/current/sounds`), is listed in the Audio
page as "Built-in" (read-only, copy to edit), and converts on first use.

### 3.2 Hold music

Today every queue and every held call plays Asterisk's `default` class:
the Opsound set installed by the `asterisk-moh-opsound-wav` package
(Creative Commons music, licence-free for this use). The owner asked for
hold music to be a topic; 9c makes it a managed object:

* **Hold music sets** (`moh_classes`): per organization, a name, an
  ordered list of recordings from the audio library (kind `music`; WAV or
  MP3 uploads), `random` or in order, and a volume. The deployer writes
  the files as 8 kHz WAV into `<data>/moh/<org>/<slug>/` and a Veyra-managed
  `musiconhold.conf` (new stub, `#tryinclude`, reload `res_musiconhold.so`
  through the module reload path that Milestone 8 fixed) with one
  `[veyra-<slug>]` class per set.
* **Where it applies**: a default set per organization (endpoints get
  `moh_suggest=veyra-<slug>`, so a held caller hears it), and an optional
  set per queue and per ring group (the queue's `musicclass`); "ringing
  instead of music" stays available. A built-in set ("Veyra default",
  the Opsound files) is always there and cannot be deleted.
* **Streams** (a radio stream or an announcement loop generated by an
  external player) are *later*; they need `mode=custom` with a reader
  process and licensing care.
* **Licensing note shown in the interface**: commercial music played to
  callers needs performance rights in most jurisdictions; the built-in set
  and Creative Commons licensed music do not. Veyra shows the licence
  field of each recording next to the set.

## 4. Calendars and bell schedules

### 4.1 Calendar

`calendars`: `organization_id`, `name`, `kind` (`ical`; `google_api`
later), `url_ciphertext` (the feed URL is a secret for Google's "secret
address"; encrypted with the installation key), `poll_minutes` (default
3, minimum 1), `timezone`, `last_polled_at`, `last_status`, `last_error`.
The worker polls due calendars, parses VEVENTs (including recurring
rules through the `icalendar` and `dateutil` libraries), expands them for
the next 48 hours and upserts `calendar_events` (`uid`, `summary`,
`starts_at`, `ends_at`, `all_day`). The Calendar page shows the next
events and the last poll result.

Google Calendar: the owner copies the calendar's **secret address in iCal
format** from Google's calendar settings; nothing else is needed. The API
with a service account is a later option (`google_api`), for installations
whose policies forbid secret addresses.

### 4.2 Bell schedule

`bell_schedules`: `calendar_id`, `page_id`, `match` (all events, or a
summary pattern such as `Bell:*`), `trigger` (`start`, `end`, or both),
`tolerance_seconds` (default 90: a bell missed by a worker restart is
still rung within the window, never later), `is_enabled`. `bell_rings`
logs every ring (event, page, at, outcome). The worker checks every 10
seconds (its loop interval drops to 10 s, the samplers of 9b keep their
30 s cadence via their own timer) and rings each event once (unique
`(schedule_id, event uid, trigger)`).

The Bell Schedules page shows the calendar, the page, the next ten rings
and the last rings; a "Ring now" button tests the page.

## 5. Shared voicemail inboxes

`voicemail_boxes.extension_id` becomes nullable; shared boxes get
`number` (from the shared number space), `name`, and
`voicemail_box_members` (extensions whose message lamps light:
`mailboxes=<box>@veyra` on their endpoints). Destinations (`voicemail`)
gain `voicemail_box_id` so routes, menus and group failovers can point at
a shared box; `*98` already asks for a box number and PIN. The Voicemail
page lists both kinds; greetings can be uploaded from the library.

## 6. AND clock messages (module `veyra.and-clocks`)

The first real module on the framework of Milestone 0, shipped in
`modules/veyra-and-clocks`, enabled where the devices exist:

* **Devices**: the module keeps its own list of clocks (name, address,
  zone or site, model) and checks reachability.
* **Messages**: text, duration, priority, colour and flashers when the
  device has them, to one clock, a zone or all; scheduled or ad hoc; a
  message log.
* **Delivery** *(spike)*: AND publishes no inbound API for third parties;
  the devices accept messages from their own web page, from IPClockWise and
  from InformaCast-compatible senders. The spike captures the request the
  clock's web page sends (an HTTP form on the device) and confirms it with
  AND support (tech@anetd.com) before the module relies on it. The
  module's "Embeddable control commands" (AN058) are supported for inline
  formatting.
* Bells can also send a message ("Period 2") with the page, through a
  module hook on `bell.rang`.

## 7. Permissions, API, interface

Permissions: `paging.read/write` (M9) gain `paging.send`; `audio.read/write`
replace the prompt part of `ivr.*` (migration maps the roles);
`calendars.read/write`, `bells.read/write`; `voicemail.*` covers shared
inboxes.

```
GET/POST        /pages, /pages/{id}, POST /pages/{id}/send
GET/POST        /calendars, /calendars/{id}, POST /calendars/{id}/poll, GET /calendars/{id}/events
GET/POST        /bell-schedules, /bell-schedules/{id}, POST /bell-schedules/{id}/ring, GET /bell-schedules/{id}/rings
GET/POST        /audio (replaces /prompts; /prompts stays as an alias one release)
GET/POST        /voicemail (shared boxes: no extension_id, number, name, members)
```

Interface: Telephony → Paging (zones, pages, who may page, the sender's
status), Audio, Calendars, Bell Schedules; Voicemail gains shared inboxes;
the module adds Modules → AND Clocks.

## 8. Installer

`veyra-pager` unit (user `veyra`, needs raw UDP only); `ffmpeg` package;
`paging.json` managed file; `verify.sh` checks the pager service and the
sender's listening ports; nothing listens outside loopback except the
multicast sends.

## 9. Testing

Unit: Poly packet encoding against the capture's vectors; the sender's
dual emission and delay (loopback multicast in tests); zone numbers in the
shared number space; the page dialplan; iCal parsing including recurring
events and time zones; ring-once logic with tolerance; shared inbox
destinations and lamps; module manifest and message encoding. Live on
dev1: a page into a zone captured with `tcpdump` showing both formats and
the delay; a bell from a test calendar entry. Hardware (owner): a VVX
phone and a speaker on the same zone hear one page together.

## 10. Out of scope

Live pages from the browser, Poly PTT (two-way), per-tenant Poly
addresses, SIP paging to Algo units as call destinations (they already
listen to multicast), Informacast compatibility.

## 11. Decisions

* 2026-10-14: scope from the owner's messages (above); Google Calendar via
  the secret iCal address first.
* 2026-10-14: owner asked for legally usable default sounds and gave the
  door-held-open example → §3.1 (synthesized tones plus CC0 recordings)
  and §2.6 (webhook with an integration token, dial-in).
* 2026-10-14: owner raised hold music → §3.2 (managed hold music sets
  from the library, per organization, queue and ring group).
