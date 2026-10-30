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

**Code sets** (issue #164): `features.PRESETS` holds whole sets of codes
(Veyra's defaults; Metaswitch as on Sparklight's code card, which moves
no-answer forwarding to `*92`/`*93`, park pickup to `*88` and the queue
waiting count to `*44` so `*85` and `*47` mean nothing unexpected). The
Feature Codes page loads one into its table as a draft (`GET
/telephony/feature-codes/presets`); Save validates and audits it like any
change, and it reaches the phones at the next deployment. Codes are
installation-wide, so a set applies to every organization. A set lists in
`notes` what it cannot change (fixed codes such as `*8`, `*97`). To add a
carrier, copy the `metaswitch` entry with the codes from its card.

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
The phone option that honours the header is in the templates since
0.27.4 (#129): Poly `voIpProt.SIP.alertInfo.1` = `alert-autoanswer` → ring
class `autoAnswer` (`ring-answer`), `call.autoAnswer.micMute`; Yealink
`features.intercom.allow` / `.mute`; variables `intercom_auto_answer`
(default on) and `intercom_mic_muted` (default off). Grandstream waits for
its templates (#36).

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
and `a` (the `*` key) opens the box with `VoiceMailMain`.

*Locater, built 0.27.3 (#131, migration `0056`):* `voicemail_boxes.locater_1`
and `locater_2` hold `followme` (key 1 of an extension's box) or a number of
the organization (`number_owner`; not the box's own). A box with an
operator or a locater gets the exit context; keys 1 and 2 there `Goto` the
extension's `fm` label or the number in the internal context, and every
`VoiceMail()` of the box takes `d(<exit context>)` so digits pressed during
the greeting leave. Administrators set them in the box dialog, users under
My Phone → Voicemail → Greeting keys (`PATCH /me/voicemail/{id}`); key 1 =
follow me is dropped at generation when the extension has no follow-me
list. The direct-to-voicemail code (`*<ext>`) now passes `u`: without it
`VoiceMail()` plays no greeting at all.

### 3.8 Class of service

`classes_of_service` per organization: `name`, `allowed_outbound_route_ids`,
`allowed_feature_code_keys`, `allow_external_forwards`,
`allow_external_follow_me`, `allow_intercom`, `allow_fax` (sending faxes from My Phone, [USER_PORTAL.md](USER_PORTAL.md) §9), `max_outbound_calls`;
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

### 3.9 My Phone (first slice of the user portal)

*Built 2026-10-18 at the owner's request ("a tab on my sidebar to configure
phones, like the UCP of FreePBX"):* every signed-in user has **My Phone** in
the sidebar, listing the extensions assigned to them with the phone's
registration, Do Not Disturb, the three forwards, find me / follow me,
their voicemail boxes (from the account page) and the feature codes they
can dial. The API is the `me` scope: `GET/PUT /me/extensions/{id}/state`
(`dnd`, `fmfm_enabled`, the forwards; the ring time stays with the
administrator), `GET/PUT /me/extensions/{id}/follow-me` (the legs; marks a
deployment like the administrator's change) and `GET /me/feature-codes`;
only extensions whose `user_id` is the caller's are reachable, changes are
audited with `self_service: true` and `updated_by: user`. Phone keys and
speed dials (#75, #76), personal contacts and the user's call history stay
with Milestone 20.

### 3.10 Telco habits and personal call rules (issues #163, #165, #170)

*Built 2026-10-26 from the Metaswitch comparison
(docs/research/pbx-comparison/COMPARISON.md, roadmap rows 5, 7 and 12).*
Staff coming from a carrier's hosted PBX dial these on day one.

| Code | What it does |
|---|---|
| `*67<number>` | One call with the number withheld (`CALLERID(pres)=prohib`). Trunks send `trust_id_outbound=yes`, so the carrier still gets the identity header, marked private. An emergency route sets the presentation back to allowed: 911 always sees the number. |
| `*69` | Calls back the last outside caller that rang this phone directly (the number `*32` blocks), reduced to ten digits for a North American number; "no number" when it was withheld. The number goes through the outbound routes as dialled, so a plan that needs an outside-line prefix (`9`) does not match it. |
| `*70<number>` | Call waiting off for that call: the code stores the call's unique ID in `veyra/ext/<org>/<ext>/nocw_call` and a hangup handler (`veyra-cw-clear`) removes it, unless a newer `*70` call replaced it. |
| `*77` / `*87` | Anonymous call rejection on and off (engine field `acr`, UserEvent like DND). |

`*67`, `*69` and `*70` place the call themselves, so nothing answers the
phone's channel first and the caller hears the far end ring. They live in
their own context, `veyra-call-codes`, which the phone context includes
**after** paging and parking: an exact page or slot number that starts with
the same digits (an all-call on `*700`) is found first.

The rules each extension may set (the administrator's extension page and
My Phone share one card; all take effect at once without a deployment,
like the forwards):

* **Forward when the phone is offline** (`cf_unavailable`): when `Dial`
  ends with `CHANUNAVAIL` (no registered phone), the call goes to this
  target at once instead of the no-answer path. The forwarding lamp counts
  it; the class of service's outside-forward rule applies as to the other
  forwards.
* **Call waiting** (`nocw`): off means a second caller is sent to the busy
  path (busy forward, busy greeting, or busy) while the phone's device
  state is anything but idle or unavailable. `DEVICE_STATE` is read only
  when call waiting is off, permanently or for a `*70` call.
* **Refuse callers who hide their number** (`acr`): outside calls only
  (`VEYRA_DID` set) whose number is empty, one of the carrier words in
  `ANONYMOUS_VALUES`, or whose presentation is `prohib*`, hear
  `privacy-unident` and are flagged `blocked` in call history.
* **Callers who still ring during Do Not Disturb** (`dnd_allow`): up to 20
  numbers or extensions. The engine holds them as one value
  `-5735550100-1002-`; the dialplan reduces the caller's number to its
  digits (ten for an eleven-digit number starting with 1) and looks for
  `-<digits>-`. A match rings as if DND were off (forwards still apply).
* **The organization's list** (`organizations.dnd_allow`, migration 0069,
  0.27.39): up to 50 numbers or extensions on the organization page that
  ring every phone of it through DND, for example the district office or
  the emergency responders' phones. Unlike the phone's own list it is
  written into the dialplan (checked first), so a change needs a
  deployment.

The row is the record (`extension_states`, migration 0068); the worker's
sync rewrites the engine's copy as for DND.

### 3.11 Supervisor listen, whisper and barge (issue #167)

*Built 2026-10-26 (Metaswitch comparison, roadmap row 9).*

* **Who:** a class of service has **May listen to, whisper on and join
  calls** (`allow_monitor`, off by default) and **Never monitored**
  (`monitor_protected`, for counselors and nurses). A phone without a class
  may *not* use the codes, unlike the other codes, and no code is rendered
  while no class allows supervising.
* **Phone codes** (Feature Codes page): `*222`, `*223`, `*224` plus an
  extension, to listen, whisper (only the extension's user hears you) or
  barge (both sides hear you). The target's device comes from its hint in
  the phone's own context, so only the organization's own extensions are
  reachable, and a protected extension has its own entry that refuses. The
  dialplan sends `UserEvent(VeyraMonitor)`, which the API audits as
  `call.monitor` (actor "phone <ext>"). In the Metaswitch code set they are
  `*47`/`*48`/`*49`.
* **Web:** permission `calls.monitor` (organization and site administrators
  by default); the live Calls page has a **Supervise…** choice per call.
  `POST /calls/{channel}/monitor {mode, extension_id?}` rings the
  supervisor's own phone (or a phone they administer) into `<ns>-spy`,
  which runs `ChanSpy` on the call's channel once answered. Refused for a
  protected class and across organizations (platform administrators
  excepted). Audited `call.monitor` with the mode and both extensions.
* ChanSpy runs with `q` (no announcement), `E` (ends with the call); the
  monitored parties hear nothing unless the organization turns on **Beep
  when a supervisor listens in** (`organizations.monitor_beep`, migration
  0069, 0.27.39). Recording-consent and notification rules differ by
  state; the class-of-service option and the switch say so.
* The beep (`<ns>-spy-beep`, a Gosub before the supervisor's ChanSpy, for
  the codes and the web alike): `Originate` of a `Local/play@<ns>-spy-beep`
  channel whose answering half plays `beep` and hangs up while the other
  half joins the call with `ChanSpy(PJSIP/<endpoint>…,qBE)`, so both sides
  hear it; the supervisor connects about 1.5 seconds later. Checked by the
  generator tests only so far; to be confirmed on handsets.

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

### 4.1 Announcements

Table `announcements` (migration `0042`): `organization_id`, `name`, `slug`
(context `veyra-ann-<slug>`), `prompt_id`, `allow_skip`, `repeat_key`, the
shared destination columns (`destination_type` + target ids) and
`is_enabled`. The context answers, plays the prompt and continues to the
destination; with `allow_skip` or a `repeat_key` the prompt is a
`Background()` with a one-second `WaitExten`, so any key skips and the
repeat key replays; a loop guard (`VEYRA_ANN_DEPTH`, eight hops) stops
announcements that point at each other. Without a prompt the context
answers with congestion and the interface flags the announcement.

API `GET/POST /announcements`, `GET/PATCH/DELETE /announcements/{id}`
(`ivr.read` / `ivr.write`); deleting one that a route, menu, group or
announcement points at is refused (`409 announcement_in_use`); a prompt
counts announcements among its uses. Interface: Telephony → Announcements
(list, create dialog, page with the destination picker).

*Built 2026-10-18.*

### 4.2 Dial-by-name directory

A destination kind without an object: `{type: "directory"}` sends the call
to `veyra-directory` (one context per engine namespace), which runs
`Directory(<voicemail context>,<phone context>,eb)`: callers spell the
first or the last name on the keypad over the organization's voicemail
boxes (an extension needs a box to be listed), hear the extension number,
and are connected; `0` and `*` leave with a goodbye. Available wherever a
destination is chosen.

*Built 2026-10-18.* *Custom names and the operator, built 0.27.10 (#135,
migration `0061`):* `directory_entries` (organization, name, number of the
organization) and `directory_settings.operator_number`; Telephony → Dial by
Name. The generator writes `directory.conf` (voicemail.conf layout without
PINs: each voicemail context lists the boxes and the organization's names)
and `Directory()` reads it with `c(veyra/directory.conf)`; `o` goes to the
operator in the phone context, or says goodbye. API `GET /name-directory`,
`PUT /name-directory/operator`, `POST/PATCH/DELETE /name-directory/entries`
(`ivr.read` / `ivr.write`).

### 4.3 Conference rooms

Table `conference_rooms` (migration `0042`): `organization_id`, `name`,
`slug` (context `veyra-conf-<slug>`), `number` (shares the organization's
number space with extensions and groups; `409 number_in_use`),
`user_pin_ciphertext` and `admin_pin_ciphertext` (installation key,
purposes `conference.pin:<id>:user|admin`; write-only in the API, the
output carries `has_user_pin` / `has_admin_pin`), `max_participants` (0 =
no limit, at most 500), `record`, `announce_join_leave`,
`music_on_hold_alone`, `wait_for_admin`, `moh_class_id`, `is_enabled`.

Generated: `confbridge.conf` (new managed file, stub installed by the
installer, reload scope `app_confbridge.so`) with a bridge profile, a user
profile, an administrator profile (`admin=yes`, `marked=yes`) and a key
menu per room (`*1` mute, `*4`/`*6` listening volume, `*7`/`*9` talking
volume, `*2` lock, `*3` kick last, `*8` mute all, the last three for
administrators); the room's context in `extensions.conf` asks for the PIN
(`conf-getpin`, three attempts) when a PIN is set, matches the administrator
PIN first, lets `#` alone through when only an administrator PIN exists,
then `ConfBridge(<room>,<bridge>,<profile>,<menu>)`. The phone context
dials the room by number and carries `hint,confbridge:<room>` so a line key
lights while the room is in use. Recordings go to
`<recordings>/conferences/<org>--<slug>-<timestamp>.wav` (directory created
by the installer, `2770 veyra:asterisk`); once a file has not grown for two
minutes the worker converts it like a call recording and lists it on the
Call Recording page with its room (0.27.2, #133; 90 days' retention).

API `GET/POST /conferences`, `GET/PATCH/DELETE /conferences/{id}`
(`groups.read` / `groups.write`); deleting a room in use is refused (`409
conference_in_use`). Interface: Telephony → Conference Rooms.

*Built 2026-10-18.* Known limitation: PINs appear in clear in the
generated `extensions.conf` (0640 veyra:asterisk), as voicemail PINs do in
`voicemail.conf`.


**Live control** (issue #96, 0.27.21): the room page shows who is in the
room (refreshed every 5 s) with **Mute/Unmute**, **Remove**, **Mute
everyone else** (non-administrators), **Unmute all**, **Lock/Unlock** and
**End**. `GET /conferences/{id}/live` → `{running, locked, participants
[{channel, caller_id, admin, marked, muted}]}`; `POST …/live {action,
channel?}` (`groups.write`, audited `conference.live_<action>`). The
Asterisk adapter reads `confbridge list` / `confbridge list <room>` and sends
`confbridge mute|unmute|kick|lock|unlock` through the console (rows parsed
by pattern; channel names validated).

Added in 0.27.49 (migration `0073`):

- **Recording**: `record_start` / `record_stop` send `confbridge record
  start|stop <room>`; every bridge profile now carries `record_file`, so the
  file is named and stored like an automatic recording. `recording` in the
  live state comes from the recorder channel `CBRec/<room>-…` in `core show
  channels concise`. A room with `record` on refuses `record_stop` (`409
  always_recorded`): `always_recorded` in the state tells the page.
- **Inviting a number**: `{action: "invite", number}` originates
  `Local/<number>@<phone or outbound context>/n` into the room's context with
  `VEYRA_CONF_INVITED=1`, which skips the PIN; the person joins as a
  participant. An organization's extension goes through the phone context,
  anything else through the outbound routes, under the class of service of
  the inviter's extension (an administrator with no phone in the organization
  has none). Numbers matching an enabled emergency route are refused (`422
  emergency_number`): the service would get the wrong caller ID and location.
- **Room owners**: table `conference_room_owners` (`room_id`, `extension_id`),
  set with `PUT /conferences/{id}/owners {extension_ids}` (`groups.write`,
  audited `conference.owners`, no deployment). The users of those enabled
  extensions get `GET /me/conferences` and `GET/POST
  /me/conferences/{id}/live` (same actions and audit, invitation under the
  owning extension's class of service) and the **Conference** widget on
  My Phone. Anyone else gets 404.

Not yet: push updates instead of the 5-second refresh (#111), scheduled
conferences and invitations by email.

### 4.4 Destination kinds

`DestinationType` gains `announcement`, `conference`, `call_flow` and
`directory`; every destination holder (inbound routes, IVR menus and
entries, ring groups, queues, announcements, call flows) carries
`<prefix>_announcement_id`, `<prefix>_conference_id` and
`<prefix>_call_flow_id` (ON DELETE SET NULL). The snapshot renders
`{type: "announcement", announcement: <slug>}`, `{type: "conference",
conference: <slug>}` and `{type: "directory"}`; the generator emits
`Goto(veyra-ann-<slug>,s,1)`, `Goto(veyra-conf-<slug>,s,1)` and
`Goto(veyra-directory,s,1)` ([VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §6).

### 4.5 Call flows (day/night switches)

Table `call_flows` (migration `0043`): `organization_id`, `name`, `slug`
(context `veyra-flow-<slug>`), `code_index` (0-99, unique per organization;
dialled as `*28<index>`, feature code `callflow_toggle_prefix`),
`pin_ciphertext` (installation key, purpose `call_flow.pin:<id>`,
write-only), the two destinations `normal_*` and `override_*` (the shared
destination shape), the switch itself (`override`, `override_by`,
`override_at`) and `is_enabled`. The engine keeps the switch in its store
(`veyra/switch/flow/<org>/<slug>` = `1`) behind
`Custom:veyra-flow-<org>-<slug>`, so a BLF key with the code lights while
the flow is switched.

The routing context reads the store at call time and jumps to the override
destination while it is `1`; the feature code (in the namespace's features
context, guarded by the class of service key `callflow_toggle_prefix` and
the phone's organization) asks for the PIN when one is set, flips the store
entry and the device state, plays *activated* / *de-activated* and tells the
API with `UserEvent(VeyraSwitch,Kind: flow,Org,Key,Value)`. The API
(`POST /call-flows/{id}/state {override}`) and the interface (Telephony →
Call Flows: a switch on each row and on the page) write the row and the
engine live; no deployment is needed to switch. The worker's sync
(`veyra/telephony/switches.py`) makes the engine match the rows every pass,
so a restart or a lost store entry heals itself.

API `GET/POST /call-flows`, `GET/PATCH/DELETE /call-flows/{id}`,
`POST /call-flows/{id}/state` (`routing.read` / `routing.write`); a flow in
use as a destination cannot be deleted (`409 call_flow_in_use`); two flows
of one organization cannot share an index (`409 code_index_in_use`).
Destination kind `call_flow` everywhere a destination is chosen.

*Built 2026-10-18.*

### 4.6 Time-condition override

`time_conditions` gains `override` (`open` | `closed` | NULL),
`override_temporary`, `override_since_open`, `override_by`, `override_at`,
`code_index` (0-99, unique per organization; `*27<index>`, feature code
`tc_override_prefix`) and `pin_ciphertext` (purpose
`time_condition.pin:<id>`). An inbound route consults the engine store
(`veyra/switch/tc/<org>/<condition id>`) before its `GotoIfTime` lines, so
a forced state wins over the schedule; the lamp is
`Custom:veyra-tc-<org>-<id>`.

The feature code inverts the schedule's current state (the dialplan runs
the same `GotoIfTime` checks): closed now → forced open, open now → forced
closed; dialled while an override is set, it clears it. Overrides set from a
phone are temporary. The interface (the time condition's page: *Force open*,
*Force closed*, *Back to the schedule*, with a temporary/permanent choice)
and the API (`POST /routing/time-conditions/{id}/override {state,
temporary}`) write live. A temporary override ends when the schedule itself
changes state: the worker compares the schedule's state now with the one
recorded when the override was set and clears the row and the engine. The
list and the page show what the schedule says and what callers get. A
condition with a code is deployed even before a route uses it.

*Built 2026-10-18.* Permanent overrides are cleared by hand (interface, API
or the phone code).

### 4.7 Call parking

Table `parking_lots` (migration `0044`): `organization_id`, `name`, `slug`
(contexts `veyra-park-<slug>` and `veyra-park-<slug>-timeout`),
`park_exten`, `slot_first`, `slot_last` (at most 50 slots; the park
extension outside them), `timeout_seconds` (10-1800),
`return_ring_seconds` (5-120), `courtesy_tone`, the timeout destination
(shared shape) and `is_enabled`. The lot's numbers live in the
organization's number space (`number_owner` knows them: an extension,
group, room or another lot cannot take them, `409 number_in_use`); they
are short by convention (70, 71-79) and exempt from the plan's extension
length.

Generated: `res_parking.conf` (new managed file, stub installed by the
installer, reload scope `res_parking.so`) with one lot per section
(`parkext`, `parkext_exclusive`, `parkpos`, `findslot=next`,
`parkingtime`, `comebacktoorigin=no`, `comebackcontext`,
`comebackdialtime`, `parkedplay=caller`, `courtesytone=beep`,
`parkedcalltransfers`/`parkedcallreparking=caller`). res_parking fills
the lot's context with the park extension, the slots and their hints
(`park:<slot>@<lot>`), and the phone context includes it, so a transfer
to the park extension parks (the slot number is read back) and dialling
a slot retrieves; a line key with a slot number lights while a call waits
there. On timeout the call enters the timeout context, which rings the
parker (`${PARKER}`) for the return time and then takes the lot's
destination.

API `GET/POST /parking-lots`, `GET/PATCH/DELETE /parking-lots/{id}`
(`groups.read` / `groups.write`). Interface: Telephony → Parking.

*Built 2026-10-18.* Not in this slice: a dedicated *park* line-key type in
the provisioning templates (#40) and FreePBX's `*85<slot>` pickup code
(dialling the slot does the same). *`*85<slot>` built 2026-10-20 (0.27.23,
issue #135):* feature code `park_pickup` (default `*85`); the phone context
gets `*85<slot>` → the slot's extension in the lot's context, with the
`park:<slot>@<lot>` hint so a key on it lights.

### 4.8 Caller block list

Tables `caller_blocks` (per organization: `number` as the carrier presents
it, `description`, `source` api | phone | csv, `hits`, `last_hit_at`) and
`caller_block_policies` (one row per organization: `block_anonymous`,
`anonymous_hits`, the destination of blocked calls in the shared shape);
migration `0045`. The engine keeps the numbers in its store
(`veyra/blacklist/<org>/<number>` = `1`) and every inbound route (shared,
per-trunk and the catch-all) starts with `DB_EXISTS` on the caller's number
and, when the policy says so, a test for withheld numbers (`anonymous`,
`restricted`, `unavailable`, `unknown`, `private`, empty, or a `prohib*`
presentation); a hit jumps to the route's `blocked` label, which sends
`UserEvent(VeyraBlocked,Org,Number,Did)` and then takes the policy's
destination or answers with *the number you have dialled is not in service*
(`ss-noservice`).

Numbers change live: the API writes the row and the store, the phone codes
write the store and report with `UserEvent(VeyraBlacklist,Action,Org,Number,By)`,
and the worker's sync (`veyra/telephony/blacklist.py`) reconciles the two
every pass. The policy (anonymous rule, destination) is dialplan and needs a
deployment. Feature codes: `blacklist_add` `*30` (enter the number),
`blacklist_remove` `*31`, `blacklist_last` `*32` (the last outside caller
the phone received directly: every extension records
`veyra/lastcid/<org>/<ext>` when a trunk call reaches it; calls that reached
the phone through a ring group or queue are not recorded). Blocked calls are
counted per number (`hits`) and, for withheld numbers, on the policy.

API `GET/POST /caller-blocks`, `PATCH/DELETE /caller-blocks/{id}`,
`POST /caller-blocks/import` (CSV text: `number[,description]`, a header line
is skipped, at most 5000 lines), `GET /caller-blocks/export?organization_id`
(CSV), `GET/PUT /caller-blocks/policy` (`routing.read` / `routing.write`).
Interface: Telephony → Blocked Callers (list with hit counts, add, import,
export, the rules card). Adapter: generic store access
(`store_entries(family)`, `store_put(family, key, value)`).

*Built 2026-10-18.* Not in this slice: an allow list, and the blocked count in
the call history rows (the refused call is counted here, not as a call record).

### 4.9 Queue dynamic agents

`queue_members` gains `dynamic`, `logged_in`, `paused`, `state_by`,
`state_at` (migration `0046`). A static agent is written to `queues.conf`
as before; a dynamic agent is left out of the file and joins at login:
from a phone with `queue_login` (`*45`: every queue the phone is a dynamic
member of; `*45<queue number>`: that queue), from the queue's page
(*Agents* card) or with `POST /queues/{id}/agents/{extension_id}/state
{logged_in, paused}`; `queue_pause` (`*46`) pauses or resumes the agent in
all its queues. `queue_count` (`*47<queue number>`) says how many callers
wait. `persistentmembers=yes` keeps dynamic members across an engine
restart and the worker's sync (`veyra/telephony/agents.py`) makes the
engine's member list (parsed from `queue show`) match the rows every pass.

Dialplan: the codes jump to `veyra-agent-login` (or
`veyra-agent-login-<queue>`) at the phone's own number, where one block per
dynamic agent runs `AddQueueMember` / `RemoveQueueMember` for its queues,
keeps the engine store (`veyra/agent/<org>/<ext>` while logged in anywhere,
`veyra/agent/<org>/<ext>/<queue>` per queue, `.../paused`) and the lamps
(`Custom:veyra-agent-<org>-<ext>`, `Custom:veyra-agentpause-<org>-<ext>`;
hints `*45*<ext>` and `*46*<ext>`), and reports with
`UserEvent(VeyraAgent,Org,Extension,Action[,Queue])`. The API writes rows and
the engine live (`queue add/remove/pause member` through the CLI). The queue
page lists dynamic agents with their state and a log in / pause control; the
members editor marks an agent as dynamic (*Logs in*). A dynamic agent keeps
its state when the member list is edited.

*Built 2026-10-18.* Not in this slice: pause reason codes, agent state in the
queue reports, restricting who may log in beyond the member list.
*Live check 2026-10-19 (dev1, 0.25.4):* a dynamic agent logged in through the
API appeared in `queue show` as a dynamic member within a second; the AstDB
marks the phone toggles read were missing, so `_write_member` and
`_write_lamps` now write `veyra/agent/<org>/<ext>[/<queue>|/paused]` as well
(0.25.5). *Live check 2026-10-19 (dev1, 0.26.0):* still missing — the
adapter's store key check refused keys with a path, so the writes were
logged as warnings; the check now allows a path and the test double applies
the engine's checks (0.26.1).

### 4.10 Queue break-out menu

`call_queues.breakout_ivr_id` (migration `0046`): an IVR menu of the
organization whose keys callers may press while waiting. `queues.conf` gets
`context=veyra-ivr-<slug>`, so a digit pressed in the queue leaves to that
key's extension in the menu's context (the menu's own destinations: voicemail,
an extension, another menu, …); the periodic announcement is the place to
tell callers which key does what. `queue_log` records the exit as
`EXITWITHKEY`.

*Built 2026-10-18.* The exit reason is not yet shown in the queue reports.

### 4.11 In-call codes

`features.conf` is a new managed file (stub installed by the installer;
applied with `features reload` through the CLI, since the features are a
core component without a module): `[featuremap]` carries `blindxfer`
(`blind_transfer`, `##`) and `atxfer` (`attended_transfer`, `*2`), with a
three-second transfer digit timeout, a beep on transfer and a 15-second
no-answer limit for attended transfers; `[applicationmap]` carries
`veyra-record` (`record_toggle`, `*1`), which runs
`Gosub(veyra-ondemand,s,1)` on the channel that pressed it, for either
side of the call.

The dialplan's `[globals]` set `VEYRA_XFER` (`tT` while a transfer code is
enabled, else empty), `VEYRA_XFER_OUT` (`T`) and `DYNAMIC_FEATURES`
(`veyra-record` while the recording code is enabled); every `Dial` to a
phone (extensions, ring groups) carries `${VEYRA_XFER}` and trunk legs
`${VEYRA_XFER_OUT}`, so DTMF transfers work on phones and softphones that
have no transfer key of their own while SIP transfers stay as they were. The
`veyra-ondemand` context starts a `MixMonitor` into the recordings' incoming
folder under the pseudo policy id `00000000-0000-0000-0000-000000000000`
(so the worker files it with the call record, default retention, no
policy), plays a beep, and stops the recording on the next press.

*Built 2026-10-18.* Not in this slice: class-of-service guards for the
in-call codes (the allowed-codes list applies to dialled codes), and a
"record this call" button in the interface. *Record button built
2026-10-20 (0.27.25, issue #135):* Calls → **Record** / **Stop recording**
(`POST /calls/{channel}/record {action: start|stop}`, permission
`calls.record`, audited `call.record_start|stop`). The adapter sets
`VEYRA_CALLREC` and `CDR(veyra_rec)` on the channel through ARI and runs
`mixmonitor start <channel> <recordings>/incoming/<ref>--<on-demand policy>.wav,b`
on the console, so the worker files it like the phone's `*1`; a call
already recorded is refused, and only a web-started recording can be
stopped from the web. *Class-of-service guards (same release):* the
`veyra-ondemand` toggle checks the pressing phone's `VEYRA_COS` against the
classes without `record_toggle` (error tone); a class allowing neither
`attended_transfer` nor `blind_transfer` loses Dial's `T` when its phone
calls (`REPLACE(VEYRA_XFER,T)`) and `t` when its phone is called (Dial's
options switch both transfer codes together, so allowing one of the two
allows both).
*Live check 2026-10-19 (dev1, 0.25.4):* `features.conf` was written on
deployment but `features show` kept the engine defaults: Asterisk 22 has no
`features reload` console command, and `asterisk -rx` exits 0 on "No such
command", so the adapter took it as done. The adapter now runs `module
reload features` and `cli.run` treats "No such command" as a failure
(0.25.5); after the fix `features show` lists `##`, `*2` and `veyra-record *1`.

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
