# Call Features (Milestones 18 and 19)

Design for the first two FreePBX-parity milestones ([ROADMAP.md](ROADMAP.md)
rows 18 and 19; [FREEPBX_GAP_ANALYSIS.md](FREEPBX_GAP_ANALYSIS.md) §4 item 1).
Milestone 18 (0.24.0) delivers **diagnostics** the owner asked for on
2026-10-16 (where phones register from, packet capture) and the
**extension-centred** features: Do Not Disturb, call forwarding, find me /
follow me, per-extension outbound caller ID, intercom and auto-answer,
transfer to voicemail, the voicemail operator, class of service and a
feature-code page. Milestone 19 (0.25.0) delivers the **call-flow**
features: parking, conferences, announcements, the dial-by-name directory,
day/night toggles, time-condition override, the caller blacklist, queue
agent log-in and pause, the queue break-out menu and the in-call codes.
The diagnostics come first so they can be used while the rest is tested.

## 1. Principles

1. **State lives in the database, not only in the engine.** DND, forwards
   and toggles set from a phone are written back to Veyra (through the ARI
   event stream or a dialplan `UserEvent`), so the interface, the user
   portal (Milestone 20) and the generator always agree. The engine's
   `AstDB` is a cache the generator seeds; it never holds the truth.
2. **Feature codes are data.** One table of codes per installation with the
   FreePBX defaults (so a migrating site keeps its habits), renamable and
   switchable per code; the generator reads them; the Companion and the
   phone templates learn them from the API.
3. **Nothing an extension does can exceed its class of service.** External
   forwards and follow-me legs are outbound calls from the extension and
   follow its routes, its caller-ID rules and its class.
4. **Per organization.** Every object is tenant-scoped; numbers and codes
   live in the organization's engine namespace ([MULTI_TENANCY.md](MULTI_TENANCY.md)).
5. **Root only where the kernel requires it.** Packet capture runs as root
   through a fixed unit; nothing else in these milestones does.

## 2. Diagnostics (Milestone 18, built first)

### 2.1 Where each phone registers from

Owner request: "see what IP addresses endpoints are registering from
(local/public when necessary)". ARI's `/endpoints` only says online or
offline. PJSIP keeps the facts in its contact objects, persisted in the
Asterisk database (`database show registrar/contact`, one JSON object per
contact with `uri`, `via_addr`, `via_port`, `user_agent`, `expiration_time`,
`reg_server`, `endpoint`) and listed with reachability and round-trip time
by `pjsip show contacts`. Both are read over the CLI socket the service
account already has (`veyra/telephony/asterisk/cli.py`), parsed in
`contacts.py` without a shell, joined on the contact hash (the store keys
each contact by its full hash, the listing prints the first ten characters
and cuts long URIs to its column width) and cached for five seconds.

Veyra generates every endpoint with `rewrite_contact=yes`, so PJSIP stores
the contact URI with the host and port the REGISTER actually arrived from and
keeps the phone's own Contact address in the `x-ast-orig-host` URI parameter
(`sip:ep@203.0.113.9:36821;x-ast-orig-host=192.168.1.20:5060`). `via_addr`
is the Via header as the phone sent it, not the source, and is used only
for an endpoint configured without the rewrite.

Two addresses per contact, named plainly in the interface:

| Field | Meaning |
|---|---|
| `source_host`, `source_port` | where the REGISTER actually arrived from (the rewritten URI host and port). Public when the phone sits behind a remote NAT; the LAN address for a local phone |
| `contact_host`, `contact_port` | what the phone put in its Contact header (`x-ast-orig-host`): its own address, usually private |
| `nat` | the two differ |
| `transport`, `user_agent`, `expires_at`, `status` (`Avail`, `Unavail`, `NonQual`), `rtt_ms` | from the URI parameters, the store and the listing |

Adapter: `Capability.REGISTRATIONS`, `registrations() -> list[Registration]`.
API: `GET /telephony/registrations[?organization_id=&q=]` (`extensions.read`,
scoped like the extension list; platform administrators also see contacts no
extension claims), and `registration.contacts` on every extension. Webhook
`registration.changed` carries `address` (source), `contact_address` and
`nat`. Interface: Telephony → Registrations (search, organization filter,
refresh every ten seconds, NAT badge, reachability and expiry) and a
"Registers from" column on Extensions. Addresses are not written to the
audit log. Trunk registrations (Veyra registering to a carrier, issue #45)
are a different object, `pjsip show registrations`, and join this page in
the same milestone. *Built 2026-10-18:* `Capability.TRUNK_REGISTRATIONS`,
`trunk_registrations()` (parsed from `pjsip show registrations`), the trunk
`status` gains `registration` and the states `rejected`, `registering`,
`unregistered` (a refused registration outranks a good qualify), the
`trunk_down` alert reports the registration word, and
`GET /telephony/registrations` carries `trunks` for platform administrators.

### 2.2 Packet capture

Owner request: "the ability to do packet captures for testing". System →
Diagnostics → Captures (platform administrators, permission
`diagnostics.capture`):

* **Start** with a filter built from data, never typed: an extension or
  device (its current source address and the SIP ports), a trunk (its
  host), an address or network, or "all SIP" (the SIP transports' ports);
  **RTP** is a separate tick box because media is sensitive; a duration
  (default 2 min, max 30) and a size limit (default 50 MB, max 500).
* A root unit `veyra-capture@<id>.service`, started and stopped through
  polkit like `veyra-backup@` ([PRODUCTION_HARDENING.md](PRODUCTION_HARDENING.md) §2.2),
  runs one fixed `tcpdump` command: `-i any -nn -s 0 -Z root -U -w <file>`
  plus a BPF expression Veyra assembles from validated fields (`host`,
  `net`, `port`, `portrange`; `veyra/diagnostics/filters.py`). The row
  stores the fields, not the expression the runner uses: the root runner
  (`veyra/diagnostics/runner.py`) reads the row through the service account
  and rebuilds the expression with the same validation, so nothing typed
  reaches tcpdump. The runner, not tcpdump, enforces the duration and the
  size limit (tcpdump's `-G` only rotates when a packet arrives and `-C -W 1`
  overwrites from the start), ends tcpdump with SIGTERM so the file is
  complete, reads the packet count from its summary and hands the file to
  the service account (`/var/lib/veyra/captures/<id>.pcap`, veyra:veyra
  0640, in a directory the service account owns) so the API serves, prunes
  and deletes it without another root step. A stop from the page is
  `systemctl stop` of the unit; the runner records `stopped`. At most two
  captures run at a time. `veyra capture start|stop|list|delete` for the
  console.
* The page (System → Diagnostics) lists captures (state, started, length,
  size, packets, filter, who), **stops** a running one, **downloads** the
  `.pcap` (audited `capture.download`; a one-time notice per browser
  reminds the operator that captures can contain call content and personal
  data) and **deletes** it. Starting is audited as `capture.start` with the
  expression, stopping as `capture.stop`, deleting as `capture.delete`,
  the SIP view as `capture.view`; the unit's outcome as `capture.run`.
* A **SIP summary** is parsed from the file in Python (`dpkt`-free, own
  minimal pcap reader, `veyra/diagnostics/pcap.py`: classic pcap, the Linux
  cooked v1/v2 link types `-i any` writes, Ethernet with VLAN tags, raw IP,
  IPv4/IPv6, UDP and TCP, the first 64 MB and 5000 messages): one row per
  SIP message (time, source, destination, method or response, Call-ID,
  From, To, User-Agent), grouped by dialog, so the common "why does this
  phone not register" needs no Wireshark. TLS transports stay opaque.
* Retention class `captures` (default 7 days, minimum 1; the job removes
  the file with the row, running captures stay; [PRODUCTION_HARDENING.md](PRODUCTION_HARDENING.md) §4).
  Captures are per node and are not synced to an HA standby. `verify.sh`
  checks the unit, the polkit rule, the directory and `tcpdump`
  (`capture-unit`). Model `Capture` (migration `0032`), table `captures`.
  Permissions: `diagnostics.read` (the page, the list, the SIP view) and
  `diagnostics.capture` (start, stop, download, delete), both platform
  only. Targets: an extension resolves to the addresses its phones
  register from (§2.1; refused with `409 not_registered` when none is), a
  trunk to its host and port, an address or network as given, "all SIP" to
  the SIP transports' ports; RTP adds the RTP port range.

### 2.3 Diagnostics page

The P2 row "Asterisk logfiles and CLI in the browser" as a safe subset:
a **log tail** of `/var/log/asterisk/full` and `security.log` (last N
lines, filter, audited `diagnostics.log_read`) and **engine queries** from
a fixed list (`pjsip show endpoint <name>`, `pjsip show contacts`, `core
show channels verbose`, `pjsip show registrations`, `database show
registrar`), arguments validated, every query audited. No free-form CLI.

*Built 2026-10-18:* System → Diagnostics has three tabs: Packet captures
(§2.2), **Logs** (`GET /diagnostics/logs`, `GET /diagnostics/logs/{key}
?lines=&q=`: the tail of `messages.log`, `security.log` or `queue_log` from
`/var/log/asterisk`, 10–2000 lines read from the end, an optional
case-insensitive filter, audited `diagnostics.log_read`; `full` is not
configured by Veyra's `logger.conf`) and **Engine queries** (`GET
/diagnostics/queries`, `POST /diagnostics/query {key, argument?}`: a fixed
list — endpoints, one endpoint, contacts, trunk registrations, transports,
channels, the contact store, the extension states, uptime, version — the
argument one validated token, run through the CLI socket, audited
`diagnostics.query`). Both need `diagnostics.read`.

## 3. Extension call features (Milestone 18)

### 3.1 Feature codes

Table `feature_codes` (per installation; migration `0032`): `key`, `code`,
`enabled`, `description`. Defaults follow FreePBX so a migrating site keeps
its habits; the existing Veyra codes stay (`*43`, `*60`, `*95`, `*97`,
`*98`, `*8`, `**<ext>`):

| Key | Default | Milestone |
|---|---|---|
| `dnd_on`, `dnd_off`, `dnd_toggle` | `*78`, `*79`, `*76` | 18 |
| `cf_on`, `cf_off`, `cfb_on`, `cfb_off`, `cfu_on`, `cfu_off` | `*72`, `*73`, `*90`, `*91`, `*52`, `*53` | 18 |
| `fmfm_toggle` | `*21` | 18 |
| `intercom` | `*80` | 18 |
| `vm_direct` | `*` (prefix: `*<ext>`) | 18 |
| `park`, `park_slot_prefix` | `70`, `71–79` | 19 |
| `callflow_toggle_prefix`, `tc_override_prefix` | `*28`, `*27` | 19 |
| `blacklist_add`, `blacklist_remove`, `blacklist_last` | `*30`, `*31`, `*32` | 19 |
| `queue_login`, `queue_logout`, `queue_pause` | `*45`, `*46`, `*47` | 19 |
| `record_toggle`, `attended_transfer`, `blind_transfer` | `*1`, `*2`, `##` | 19 |

Codes may not collide with each other, with the numbering plan's reserved
prefixes or with extensions; the API validates and the generator refuses a
snapshot with a collision. `GET/PUT /telephony/feature-codes`; Telephony →
Feature Codes lists them with what each does. Codes are also exported to
templates (`{{feature_codes.dnd_toggle}}`) and the Companion.

*Built 2026-10-18:* the codes live in one settings document
(`telephony.feature_codes`, overrides only; `veyra/telephony/features.py`)
rather than a table, so a new default reaches every installation without a
migration. Codes start with `*` or `#` (2 to 7 characters), may not be one
of the fixed codes (`*43`, `*60`, `*8`, `*95`, `*97`, `*98`, `**<ext>`) and
enabled codes are unique; a change marks a deployment (`routing.write`).
The snapshot carries `feature_codes` (enabled key → code); the generator
checks them again. Template and Companion export: with Milestone 21.

### 3.2 Do Not Disturb

`extension_states` (one row per extension, migration `0032`): `dnd`,
`cf_always`, `cf_busy`, `cf_no_answer`, `fmfm_enabled`, `updated_at`,
`updated_by` (`phone`, `user`, `admin`). Phone: `*78`/`*79`/`*76` run a
dialplan that answers, confirms with a prompt and raises
`UserEvent(VeyraExtState,Extension:…,Field:dnd,Value:1)`; the API's ARI
listener writes the row and publishes `extension.state_changed`. Interface:
a switch on the extension page (and the user's own page in Milestone 20).
Generator: the internal context checks `${DB(veyra/dnd/<org>/<ext>)}`,
seeded from the table at deployment and kept current by the same event
handler, before dialling; DND sends the call to the extension's busy
destination (voicemail busy greeting by default). A BLF hint
`*76<ext>` (custom device state) lights a key when DND is on.

*Built 2026-10-18* (migration `0034`, table `extension_states` with the
forward, follow-me and ring-time columns the next sections fill):

* Every endpoint carries `set_var=VEYRA_EXT=<number>` beside `VEYRA_ORG`,
  so a feature code acts on the phone's own extension whatever its internal
  caller ID says. The AstDB family is `veyra/ext/<org slug>/<number>` with
  the keys `dnd`, `cf_always`, `cf_busy`, `cf_no_answer`; the device states
  are `Custom:veyra-dnd-<org slug>-<number>` and `Custom:veyra-cf-…`.
* `*78`/`*79`/`*76` answer, set the key and the device state, raise
  `UserEvent(VeyraExtState,Org,Extension,Field: dnd,Value)` and play
  `do-not-disturb` + `activated`/`de-activated`; a channel without
  `VEYRA_EXT` hears `feature-not-avail-line`.
* The API (`GET/PUT /extensions/{id}/state`, `extensions.read`/`.write`,
  audited `extension.state_update`) writes the row and the engine's copy
  through the adapter (`Capability.EXTENSION_STATE`, `set_dnd`,
  `dnd_states`, CLI `database put/del` and `devstate change`): no
  deployment is needed. The extension list carries `dnd`.
* Instead of seeding at deployment, the worker reconciles the engine's keys
  with the rows every pass (`extension_state.sync`), which also covers a
  restored backup (AstDB is not in the backup) and an HA failover. A phone's
  change reaches the row through the UserEvent (`updated_by: phone`).
* The ring time (`ring_seconds`, 5–120) is stored now and read by the
  dialplan with §3.3.

### 3.3 Call forwarding

Three targets per extension: always, busy, no answer, each an internal or
external number (external only when the class of service allows it) with
the extension's own ring time (`ring_seconds`, 5–120, default 30; this also
closes the gap that an extension without voicemail could not change its
ring time). Phone: `*72<number>` or `*72` then prompt, `*73` off, likewise
busy and no answer; same `UserEvent` path. Generator: the internal context
reads the three `DB` keys, dials the forward target as a new leg through
the organization's outbound routes (`Local/<number>@veyra-out-<org>`) with
the extension's outbound caller ID (§3.5) and class (§3.8). An
administrator sees and clears forwards on the extension page; a BLF hint
shows CF state.

*Built 2026-10-18:* the three targets are columns of `extension_states`
(§3.2) and engine keys `cf_always`, `cf_busy`, `cf_no_answer` under the
extension's family; the API (`PUT /extensions/{id}/state`, digits with an
optional `+`, empty clears) and the feature codes write both and take
effect at once; the ring time (`ring_seconds`) is in the dialplan and waits
for a deployment (it wins over the voicemail box's ring time when a state
row exists). Dialplan per extension: DND → busy branch; `cf_always` →
forward; Dial for the ring time; BUSY → `cf_busy` → busy greeting or
`Busy()`; otherwise `cf_no_answer` → unavailable greeting or hang-up. The
forward leg is `Dial(Local/<target>@<internal context>/n)`, so an internal
target rings the phone (with its own forwards) and an outside number
leaves through the organization's outbound routes; the leg carries
`__VEYRA_OUT_CID` of the forwarding extension (§3.5) when set, resets the
trunk loop guard (`VEYRA_HOPS`) because an administrator's forward is
allowed to leave again, and stops after three chained forwards
(`VEYRA_FWD`, `number-not-answering`). Phone: `*72<number>` or `*72` then
`vm-enter-num-to-call` (digits checked with `REGEX`, `pbx-invalid`
otherwise), `*73` off; `*90`/`*91` busy; `*52`/`*53` no answer; the
forwarding lamp hint `*72<ext>` is lit while any forward is set. The class
of service check for external targets comes with §3.8.

### 3.4 Find me / follow me and external ring-group members

`follow_me` per extension: `enabled`, `strategy` (`ringall`,
`sequential`), `members` (extensions and external numbers with a per-member
ring time), `initial_ring_seconds` (ring the desk first), `confirm_calls`
(an external leg must press 1, so a mobile voicemail cannot swallow the
call), `caller_id_mode` (`caller`, `extension`), `destination` when nobody
answers. The generator emits one `Dial` with the legs, `Local` channels for
external numbers through the outbound context, `confirm` through a short
macro-free `Gosub`. Ring groups accept external members the same way
(`ring_group_members.external_number`). Toggle from the phone with `*21`.

*Built 2026-10-18* (migration `0035`, table `follow_me`; the on/off switch is
`extension_states.fmfm_enabled`, engine key `fmfm`, lamp
`Custom:veyra-fm-<org>-<ext>` with hint `*21<ext>`):

* `GET/PUT /extensions/{id}/follow-me` holds the legs (`strategy`,
  `initial_ring_seconds` 0–60, `confirm_calls`, `caller_id_mode`, up to ten
  `members` of type `extension` (must be in the organization, not the
  extension itself) or `external` (digits), each with `ring_seconds` 5–60,
  and `no_answer_destination`, an extension); it needs a deployment.
  Switching on and off is `PUT /extensions/{id}/state {fmfm_enabled}` or
  `*21`, immediate; the page refuses to switch on without members.
* Dialplan: after the always-forward check, `fmfm = 1` jumps to the `fm`
  label: the desk phone alone for `initial_ring_seconds` (busy → busy
  branch), then one `Dial` of every leg (`ringall`, for the longest ring
  time) or one `Dial` per leg (`sequential`). Extension members are
  `PJSIP/<endpoint>` (a disabled one is left out); outside numbers are
  `Local/<number>@veyra-fm-out/n`, a per-namespace context that dials the
  number into the internal context (so the organization's outbound routes
  carry it) with `VEYRA_HOPS` reset and `VEYRA_FM_OPTS` as Dial options.
  `confirm_calls` sets `U(veyra-fm-confirm^s)` (per namespace, like
  `veyra-fm-out`, so the isolation checks hold): the answering party hears
  `followme/options`, presses 1, or the leg returns `GOSUB_RESULT=CONTINUE`
  and is dropped while the others keep ringing. `caller_id_mode=caller`
  sets `__VEYRA_OUT_CID` to the caller's number, `extension` to the
  extension's outbound caller ID. Nobody answers → `no_answer_destination`
  in the internal context, else the extension's own `noanswer` label
  (no-answer forward, voicemail).
* External members of ring groups (built 2026-10-18, migration `0039`):
  `ring_groups.external_members` (up to ten numbers) and `confirm_external`;
  the generator rings them as `Local/<number>@veyra-fm-out/n` legs with
  `VEYRA_FM_OPTS` set to the confirmation routine when asked, together with
  the members (`ringall`) or after them (`sequential`), and a group with
  only outside numbers still rings. The ring group dialog has an "Outside
  numbers" field and the press-1 option.

### 3.5 Per-extension outbound caller ID

Today the endpoint's `caller_id_number` reaches the carrier only when
neither the route nor the trunk sets one (gap analysis §3.1, corrected
2026-10-16). New fields on extensions: `outbound_caller_id_number`,
`outbound_caller_id_name` (migration `0033`, with `caller_id_force` on
outbound routes and `caller_id_allow_list` on organizations). Precedence on
a trunk call: emergency caller ID (emergency routes) → route caller ID when
the route is marked **force** → extension outbound caller ID → route caller
ID → trunk default. Validation: the number must be one of the
organization's DIDs (`inbound_routes`), or be on the organization's allow
list (editable with `routing.write` on the organization page), or the
caller must hold `routing.write`; otherwise `422 caller_id_not_allowed`.
Generator: the endpoint carries `set_var=VEYRA_OUT_CID=<number>` and
`set_var=VEYRA_OUT_CID_NAME=<name>`; each trunk leg in the outbound context
applies the precedence with `ExecIf` (`_outbound_caller_id`), and the
outbound name is set only together with the extension's outbound number.
Built 2026-10-18.

### 3.6 Intercom and auto-answer

`*80<ext>` dials the extension with `Alert-Info: <http://www.notuse.com>;info=alert-autoanswer`
(Poly) and `Call-Info: <uri>;answer-after=0` (Yealink, Grandstream)
headers through `PJSIP_HEADER(add,…)`, the called phone answers on
speaker; per-extension `intercom` setting (`allow`, `deny`,
`allow_from_group`) and a per-organization default. The templates set the
matching phone option. Paging zones already use the same headers
([PAGING_RECORDINGS.md](PAGING_RECORDINGS.md)).

*Built 2026-10-18* (migration `0036`): `extensions.intercom` is `default`,
`allow` or `deny` and `organizations.intercom_default` is `allow` or `deny`
(both on their pages; a change needs a deployment; `allow_from_group`
waits for the class of service, §3.8). The snapshot resolves the setting
per extension. With the `intercom` feature code enabled the generator
emits `_*80.` in the features context, which jumps into a per-namespace
`veyra-intercom` context: an allowed extension is dialled for 20 seconds
with `b(veyra-intercom-hdr^s^1)`, a per-namespace routine that adds `Alert-Info:
<http://www.notuse.com>;info=alert-autoanswer` and `Call-Info:
<sip:veyra>;answer-after=0` on the called phone's channel; Do Not Disturb
answers busy; a denied extension hears `feature-not-avail-line`, an unknown
number `pbx-invalid`. Paging zones use multicast and keep their own path.
The phone option that honours the header (Poly `alertInfo` class, Yealink
and Grandstream intercom allow) belongs to the templates, Milestone 21.

### 3.7 Transfer to voicemail and the voicemail operator

`*<ext>` from a phone (direct dial or as a transfer target) goes straight to
the box's unavailable greeting, `VoiceMail(<box>@<ns>,s)`. Voicemail boxes
gain `operator_extension` (press 0 while the greeting plays → that
extension, the organization's operator or a destination) and `locater`
(press 1 → find me / follow me, press 2 → a second destination), rendered
as `exitcontext` and the `o`/`a` options with a per-box context.

*Built 2026-10-18* (migration `0037`): the `vm_direct` feature code (default
`*`) renders one exact entry per voicemail box in the features context,
`*<number>` → `Answer`, `VoiceMail(<number>@<ns>,s)`, so dialling it or
using it as a transfer target reaches the greeting; exact entries are
chosen over patterns, so `*7210` still reaches box 7210 beside the `_*72.`
forwarding pattern. `voicemail_boxes.operator_extension` (an extension of
the organization; the dialog field "Operator extension (press 0)") adds
`operator=yes|exitcontext=veyra-vmx-<number>` to the box and a per-box
context where `o` goes to the operator extension in the internal context
and `a` (the `*` key) opens the box with `VoiceMailMain`. The locater
(1 → follow me, 2 → a second destination) is left for the user portal.

### 3.8 Class of service

`classes_of_service` per organization: `name`, `allowed_outbound_route_ids`,
`allowed_feature_code_keys`, `allow_external_forwards`,
`allow_external_follow_me`, `allow_intercom`, `max_outbound_calls`;
extensions reference one (`class_of_service_id`, default class per
organization = everything allowed, so nothing changes until an
administrator restricts). Generator: `set_var=VEYRA_COS=<slug>` on the
endpoint; each outbound route context and feature code starts with a
`GotoIf` on the class's allow sets (a `DB` tree seeded at deployment);
refusals play `pbx-invalid` and are counted (`cos.denied` in the call
history outcome).

*Built 2026-10-18* (migration `0038`, table `classes_of_service`,
`extensions.class_of_service_id`): Telephony → Classes of Service
(`/classes-of-service`, `routing.read`/`routing.write`) holds per
organization the allowed non-emergency outbound routes (its own and the
shared ones), the allowed feature codes (or all), the three allow flags and
the simultaneous outside-call limit; the extension page assigns the class.
The guards are generated statically, no `DB` tree: every endpoint carries
`set_var=VEYRA_COS=<class slug>`, and a context denies with
`GotoIf($[${REGEX("^(a|b)$" ${VEYRA_COS})}]?cosdenied)`, listing the
classes that may *not* do the thing, so a phone without a class (empty
`VEYRA_COS`) is never denied. Each non-emergency route block starts with
its guard and, when a class has a limit, `Set(GROUP(veyra_cos)=${VEYRA_COS})`
plus one `GROUP_COUNT` check per limited class (`cosbusy` → `Busy`); each
feature code starts with its guard after the phone check (direct voicemail
has no phone check, so a transferred caller still reaches the box); the
forward label refuses targets longer than an extension number for classes
without outside forwards (`numbering.extension_length` is in the snapshot);
follow-me legs to outside numbers are left out of the dialplan for a phone
whose class forbids them; `*80` is refused for classes without intercom.
Refusals answer with `pbx-invalid` and hang up; the call-history outcome
counter (`cos.denied`) needs a new CDR field and waits for the report
builder's next pass. `allow_from_group` of §3.6 is not modelled.

## 4. Call-flow features (Milestone 19)

Parking (`res_parking` lots per organization, `70` parks, `71–79` slots
with hints, timeout return to the parker), conference rooms (`ConfBridge`
with user and admin PINs, menu, recording to the recordings store, limit),
announcements (play a prompt then continue to a destination), dial-by-name
directory (`Directory()` on the organization's voicemail context, last or
first name), call-flow toggles (`*28<n>` day/night per flow with BLF, two
destinations), time-condition override (`*27<n>` temporary until the next
change or permanent, BLF), caller blacklist (`*30`/`*31`/`*32`, anonymous
callers, CSV, counts, per organization in `DB(veyra/blacklist/<org>)`),
queue agents (`*45`/`*46`/`*47`, `AddQueueMember`/`PauseQueueMember`,
hints, pause reasons), the queue break-out menu (press a key while waiting
to leave a message or reach a destination) and the in-call codes
(`features.conf` `applicationmap`: `*1` on-demand recording, `*2`
attended, `##` blind transfer). Each gets its section in this document
when Milestone 19 starts; the data model is sketched here so Milestone 18
leaves room for it (destinations, feature codes, extension states).

## 5. Permissions and API summary

| Permission | Grants |
|---|---|
| `extensions.read` / `extensions.write` | registrations view; DND, forwards, follow-me, outbound caller ID, intercom, class assignment on an extension |
| `routing.write` | classes of service, feature codes, caller-ID allow list |
| `diagnostics.capture` | start, stop, download, delete captures (platform administrators by default) |
| `diagnostics.read` | diagnostics page: log tail, engine queries |

New endpoints: `/telephony/registrations`, `/telephony/feature-codes`,
`/extensions/{id}/state` (DND, forwards), `/extensions/{id}/follow-me`,
`/classes-of-service`, `/diagnostics/captures[/{id}[/download|/stop]]`,
`/diagnostics/logs?file=&lines=&q=`, `/diagnostics/query`.

## 6. Testing

Generator tests per feature (contexts, precedence, class refusals), API
tests (scoping, validation, audit), parser tests for contacts and pcap SIP
summaries, installer tests for the capture unit. Live on dev1: register a
phone from the LAN and one through NAT and compare the two addresses; a
capture of a registration; DND, forwards and follow-me from a Poly VVX and
a softphone; outbound caller ID observed at the carrier or in a capture.

## 7. Known limitations (planned)

Secure SIP stays in 17b. Presence-driven DND (from a calendar or Teams)
is Milestone 20 or a module. Captures are per node. The SIP summary reads
pcap files Veyra wrote; arbitrary uploads are not parsed.
