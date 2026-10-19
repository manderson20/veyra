# Provisioning breadth (Milestone 21)

Status: **released as 0.27.0 on 2026-10-20** (slices A, B, C, E, F; D on request; templates experimental until the hardware checks). Roadmap row 21 (0.27.0). Tracking issue #61;
items #76 (variables), #40 (key types), #35 (Yealink), #36 (Grandstream),
#37 (ATA), #38 (Algo and CyberData), #39 (Poly Edge and CCX), #34 (VVX on
hardware). Builds on [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md)
(Milestone 9: templates spec 2, profiles, zones, firmware, delivery) and
[USER_PORTAL.md](USER_PORTAL.md) §8 (user keys, locked keys).

## 1. Goals

1. **Nothing shared is hard-coded on a template.** Multicast paging
   addresses, the district all-call key, the time server, the admin
   password: named variables defined once at the right scope, referenced by
   templates, resolved per phone, re-provisioned on change (owner
   requirement 2026-10-18, #76).
2. **Keys for what phones actually do:** park, voicemail, transfer,
   intercom, Do Not Disturb, and toggles for call flows, time conditions and
   queue log-in, each with its lamp semantics documented (#40).
3. **Official templates beyond Poly VVX:** Yealink T3x/T4x/T5x, Grandstream
   GRP26xx/GXP21xx, one ATA with fax guidance, Algo and CyberData paging
   endpoints, Poly Edge E and CCX, all from the same facts and key list, so
   a profile moves between brands without re-entering anything (#35–#39).
4. **A phone directory** phones download from Veyra (extensions, later the
   external directory of #93).
5. **Vendor redirect services** documented and fed (Yealink RPS, Poly ZTP,
   Grandstream GDMS): the owner's phones find Veyra out of the box.
6. **VVX 411/450 verified on hardware** with a written checklist (#34), so
   the Poly family moves from `experimental` to `stable`.

Not in this milestone (P2, #61): expansion modules, hot desking, background
images, vendor redirect APIs beyond CSV export, WebRTC phones.

## 2. Provisioning variables (#76)

### 2.1 Model

Table `provisioning_variables`: `scope` (`installation` | `organization` |
`site` | `profile`), `scope_id` (NULL for installation), `name`
(`^[a-z][a-z0-9_]{0,39}$`), `value` (text, up to 1000 characters),
`sensitive` (shown masked, never exported), `description`, timestamps.
Unique on (`scope`, `scope_id`, `name`). Permission: `provisioning.write`
within the scope's organization; installation scope is platform
administrators only.

### 2.2 Resolution

For a device: installation → organization → site (the device's site, else
the profile's) → profile → the device's own `values`. The nearest wins.
`facts.resolve_variables(db, ctx)` returns the merged dict and, for the
preview, the scope each value came from.

Templates reference variables as **`vars.<name>`** (`{{ vars.paging_all_call
}}`), and the resolved variables are also merged under the template's own
variable names when a template declares `[[variables]]` with the same name
and the profile set nothing (so `admin_password` defined once for the
organization reaches every Poly profile without editing them). A variable a
template references but nobody defined renders as empty and is listed as a
*warning* in the preview and the template editor, never as an error: a
phone must still boot.

### 2.3 Where variables are used

* **Templates**: any text; the editor's variable panel lists the template's
  own variables, the core variables and every control-plane variable
  visible from the template's organization, with their resolved value for a
  chosen sample device.
* **Key lists**: a key's `value` may be `$name` (a variable reference). The
  renderer resolves it per phone (`_keys`), so the district all-call key
  (`type: page, value: $all_call_zone`) is one key on one profile for every
  building, and each building's site variable names its zone. Locked keys of
  USER_PORTAL.md §8 are therefore defined once.
* **Paging zones**: a zone's multicast address and port may also be given as
  `$name`, so the per-building addresses live in site variables.
* **Companion and feature codes**: `GET /me/provisioning/variables` returns
  the non-sensitive variables of the user's organization and site
  (CALL_FEATURES.md §3.1 export); the feature-code table is published the
  same way. Later.

### 2.4 Re-provisioning on change

Saving a variable records which devices it reaches (the scope's devices,
intersected with devices whose resolved value actually changes) and marks
them for re-provisioning: the existing NOTIFY `check-sync` path
(DEVICE_PROVISIONING.md §3.5) for phones that support it, otherwise the next
daily poll. The response says how many phones are affected; the audit entry
carries the count.

### 2.5 API

```
GET    /provisioning/variables                       core + control-plane variables (?organization_id=, ?scope=)
POST   /provisioning/variables                       {scope, scope_id, name, value, sensitive, description}
PATCH  /provisioning/variables/{id}
DELETE /provisioning/variables/{id}                  409 variable_in_use when a key or zone references it
GET    /devices/{id}/variables                       the resolved set with scopes (preview)
```

The existing `GET /provisioning/variables` (core variables only) keeps its
shape and gains the control-plane entries with `scope`, `scope_id`,
`source: "core" | "defined"`.

### 2.6 Interface

Provisioning → **Variables**: a table grouped by scope with the value,
where it is used (keys, zones, templates), and an inline editor; a
*Resolve for…* picker that shows one phone's effective set. Profile and
device pages gain a *Variables* tab showing what they inherit and what they
override. The key editor offers *Use a variable* beside the value field.

*Built 2026-10-19 (slice A, #76):* table `provisioning_variables`
(migration `0054`; `organization_id` stored for the permission filter),
`veyra/provisioning/variables.py` (names, `$name` references, `VarsView`
that renders a missing name as empty and records it, resolution, reach,
re-provision through SIP NOTIFY `check_config`, in-use check),
`/provisioning/variables` CRUD (the old core-only list is merged into it
with `source: core`), `GET /devices/{id}/variables`, preview `warnings`.
Templates get the `vars` fact; a defined variable with a template
variable's name fills it below the profile and device values. Key lists
accept `$name` on any key type (validated as a reference, resolved in
`facts._keys`). Paging-zone `$name` addresses and the Companion export are
not in slice A (§2.3, later). Interface: Provisioning → Variables (scopes,
create/edit/remove, built-in values), a *Variables* card on the device's
Configuration tab, preview warnings, and "From a variable…" on page keys.
Deleting a variable is refused only when a phone that references it would
be left without any value (another scope may still provide it).

## 3. Key types (#40)

| Type | `value` | Phone behaviour | Lamp |
|---|---|---|---|
| `park` | parking lot slug, or `slug:slot` | one touch parks the call (transfer to the lot's park extension); with a slot, retrieves from or watches that slot | BLF on the slot's hint: busy while a call is parked |
| `voicemail` | line index (default 1) | dials the voicemail access code for that line | MWI of the line |
| `transfer` | empty | the phone's transfer softkey as a hard key (blind by default; `value: attended`) | none |
| `intercom` | extension number | dials the intercom code + number (CALL_FEATURES.md §3.6, auto-answer on the called phone) | none |
| `dnd` | empty | toggles Do Not Disturb (`*78`/`*79` or the phone's native DND where the template prefers it) | the extension's DND hint (`Custom:veyra-dnd-…`) |
| `toggle` | `flow:<slug>`, `tc:<key>`, `queue:<slug>`, `agent` | dials the switch code (call flow override, time condition override, queue log-in for a queue or all) | the switch's hint (`Custom:veyra-flow/tc/agent-…`), lit in the *override* / *logged in* state |
| `page` | zone slug or `$var` | as today | none |
| `blf`, `speed_dial`, `line`, `user` | as today | | |

The generator already publishes the hints the lamps need (CALL_FEATURES.md
§3.2, §4.5, §4.6, §4.9); this milestone adds the parking slot hints
(`park:<lot>` → `hint` per slot from `res_parking`) and documents the
semantics in DEVICE_PROVISIONING.md §4.2. Each template family maps the
types to its own syntax (Poly: `lineKey.category` Line/BLF/SpeedDial/Paging
plus EFK macros for transfer, DND and intercom; Yealink: `linekey.X.type`
codes; Grandstream: P-values per key with modes). A type a family cannot
express renders nothing and is listed as a warning in the preview.

*Built 2026-10-20 (slice B, #40):* the new types are translated in
`facts._feature_keys` into the BLF and speed-dial keys every template
already renders (the original type is kept as `feature`), so no template
changed: voicemail → speed dial `*97`; intercom → speed dial intercom code +
number; park without a slot → speed dial to the lot's park extension (the
user transfers the call to it), with a slot → BLF on the slot
(`parkinghints=yes` on every lot); DND → BLF on `<dnd_toggle><own number>`;
toggle `flow:<slug>` / `tc:<id>` → BLF on the override code; toggle `agent`
→ BLF on `<queue_login>*<own number>`. Pressing a BLF dials the watched
number, so the generator now makes the DND and agent hint numbers dialable
from the owner's own phone (any other phone hears an error tone). Transfer
has no key in the Poly family yet and is reported as a preview warning;
per-queue log-in toggles (`queue:<slug>`) are not in this slice. Lamp states
are not verified on hardware (§7).

## 4. Official templates (#35–#39)

Each family is an abstract base plus model templates (the Poly pattern):
one `template.toml`, files in the vendor's syntax, the same facts (§4.1 of
DEVICE_PROVISIONING.md), the same key list. Families and their files:

| Family | Models (first set) | Files | Notes |
|---|---|---|---|
| `yealink.t4x.base` | T43U, T46U, T48U, T53, T54W, T57W, T31P/T33G (T3x) | `y000000000000.cfg` (common) is **not** used; per MAC `{mac}.cfg` with `account.N.*`, `linekey.N.*`, `features.*`, `local_time.*`, `auto_provision.*`, `multicast.*` | key types via `linekey.N.type` (13 speed dial, 16 BLF, 10 park, 5 intercom, 27 DND…); phonebook remote URL (§5) |
| `grandstream.grp.base` | GRP2612/13/14/15/16, GXP2130/2135/2140/2160/2170 | `cfg{mac}.xml` (P-values) | keys as `P323`-style per-key mode/value; multicast paging listen addresses `P2900`…; LDAP/phonebook XML |
| `grandstream.ht8xx` (ATA) | HT801, HT802, HT812, HT814 | `cfg{mac}.xml` | fax pass-through guidance: G.711, no VAD, jitter buffer fixed, T.38 on when the trunk has `fax_t38` (USER_PORTAL.md §9); `fax_mode` variable |
| `algo.8xxx` | 8180 G2, 8186, 8188, 8301 | `algop{mac}.conf` key=value | SIP account for the page extension, multicast listen (RTP or Poly group), ring/page tones, relay |
| `cyberdata.speaker` | SIP speaker, paging adapter, outdoor horn | `{mac}.xml` autoprovision | SIP account, multicast listen, nightringer |
| `poly.edge.base`, `poly.ccx.base` | Edge E220/E350/E450, CCX 400/500/600 | same UCS XML as VVX with model `model_settings` | Edge: `lineKey` counts, pages of keys; CCX: no paging groups (CCX lacks PTT), softkeys |

Status of every new template is `experimental` until a hardware check is
recorded (§7). Templates ship in the repository under
`provisioning/templates/official/` and are read-only; *Customize* copies a
family into local templates as today.

*Built 2026-10-20 (slice C, #35):* `yealink.base` (abstract) with
`yealink.t3x` (T31P, T31G, T33G), `yealink.t4x` (T43U, T46U, T48U) and
`yealink.t5x` (T53, T53W, T54W, T57W); one `{mac}.cfg` per phone (the
common `y0000…cfg` files get a 404 and the phone goes on to its own file).
Keys: line 15, BLF 16 with the pickup code, speed dial 13, transfer 3 (the
family declares `key_transfer`, so no preview warning), multicast paging 24
on the zone's address; up to ten multicast listen addresses from the
profile's subscribed zones; DST as week-based rules (Yealink counts the
weekday from Monday); the variables share names and values with the Poly
family (`sip_transport` UDPOnly/TCPOnly/TLS/DNSnaptr, `admin_password`,
`polling_hour`, `registration_expires`) so one organization variable fills
both. Facts gained `server.directory_url` and the zone's multicast address
on page keys; the resolved template exposes the chain's `features`.

### 4.1 Current lineups (researched 2026-10-20)

Owner direction (2026-10-20): cover every model the vendors sell today;
the owner names the end-of-life models still in production and those are
added on request. Templates group models by **configuration format**, not by
model, so one family template covers a whole lineup.

| Vendor | Format family | Current models (vendor or distributor pages) | Plan |
|---|---|---|---|
| Yealink | one `.cfg` format for every SIP phone | T8: T85W, T87W, T88 · T7: T73U, T73W, T74U, T74W, T77U · T5: T53, T53W, T54W, T57W, T58W (Pro), VP59 · T4: T42U, T43U, T44U, T44W, T46U, T48U · T3: T30, T30P, T31, T31G, T31P, T31W, T33G, T34W · conference: CP925, CP935W, CP965 | extend the slice C family: model lists for T3x/T4x/T5x, new `yealink.t7x`, `yealink.t8x`, `yealink.cp` (no line keys). DECT (W70B/W80/W90 bases, W5x/W7x handsets) and Wi-Fi AX8x are a separate format: on request |
| Poly | UC Software XML (VVX, Edge E, CCX) | Edge E: E100, E220, E300, E320, E350, E400, E450, E500, E550 · CCX: CCX 350, 400, 500, 505, 600, 700 · VVX: end of sale (VVX 350 EOL June 2026) · Edge V (announced April 2026, availability September 2026): V200, V250, V250 Plus, V400, V450, V650, V800, V850 | Edge E and CCX on the VVX base (slice F); Edge V once its configuration format is documented (not stated in the announcement) |
| Algo | one `algop{mac}.conf` key=value format for every SIP endpoint | speakers 8180, 8186, 8188, 8189, 8190, 8196, 8197, 8198, 8199, 8507 · display speakers 8410, 8420 · paging adapters 8301, 8305, 8312, 8373 · intercoms 8028, 8028V, 8039, 8063, 8201, 8203 · alerters 8128, 8138 · clocks 8401, 8402 · console 8450 · controller 8300 | one family `algo.base` with role variables (page listener, ring, intercom); the owner's speakers and horns first |
| CyberData | XML autoprovision per device type | SIP Paging Server+ 011600/011601 (2026, replaces the paging adapter and paging server), SIP speakers, outdoor horn 011457, paging amplifier 011324 | on request (not in the owner's fleet) |
| Grandstream | P-value XML | GRP2600 (GRP2602, 2610, 2611, 2612/P/W/G, 2613-2616), GXP1600, GXP2100, ATAs HT801/HT802 v2, HT812/814/818, HT813 | on request (not in the owner's fleet); the ATA remains the fax pass-through candidate |
| Advanced Network Devices (AND) | not SIP-provisioned (web/TFTP/SLP; IPClockWise) | IPCSS-RWB, IPSWD-RWB, IPSIGNL-RWB, IPSWS-SM-O | out of scope for templates; messaging is the 9c / module item |

Sources: algosolutions.com/products, yealink.com/en/product-list/ip-phone,
HP newsroom (Edge V, April 2026), distributor listings for Poly, Grandstream
and CyberData. Models the owner still runs that are no longer sold are
added to the matching family when named.

*Built 2026-10-20 (Algo, #38):* one template `algo.sip` for every current
Algo SIP endpoint (§4.1 list). Files `algom<MAC upper>.conf` (Algo's
device-specific name, looked up before the generic `algop<model>.conf`) and
`algom<MAC upper>.md5` — the template spec gained `checksum_of`, a file
holding the MD5 of another rendered file in `md5sum` form, because Algo
ignores a configuration without a matching checksum. Parameter names from
Algo's provisioning reference for firmware 5.5: `sip.proxy`, `sip.transp`,
`sip.regexp`, `sip.u1.*` (page extension = line 1), `sip.alert1.*` (ring
extension = line 2), `mcast.mode`, `mcast.polycom.mode` (`multicast_format`
rtp/poly/both), `mcast.zone1-7` from the subscribed zones and `mcast.zone9`
from an emergency zone, `mcast.polycom.zone/groups/default`, `net.time1`,
`admin.timezone` (`algo_timezone`, Algo's own spelling such as US/Central),
`net.vlan.*`, `prov.*` (static HTTPS server with the device credential,
path `provisioning`, daily sync window), `prov.version.firmware` (full URL,
5.5+). Not set: the web admin password (Algo does not document its
parameter), comments (no documented syntax). Facts gained `server.host` and
`server.provisioning_path`. Template "Customize" now copies single-file and
checksum families correctly (it used to skip every `{mac}.cfg`).

## 5. Phone directory

`GET /provisioning/directory/{format}` (device credential required, like
the configuration files): the organization's extensions (number, display
name) and ring groups, as `poly` (`000000000000-directory.xml`), `yealink`
(remote phonebook XML), `grandstream` (phonebook XML), `csv`. Profiles gain
`directory_enabled` (default on; a Yealink variable in slice C, the other
families follow); the templates write the directory URL
(`dir.corp.*` for Poly, `remote_phonebook.data.1.url` for Yealink,
`P331`-style for Grandstream). Later: the external directory of #93 as a
second book.

*Built 2026-10-20 (slice C):* `GET /provisioning/directory/{poly.xml,
yealink.xml,grandstream.xml,contacts.csv}` with the device or organization
credential (logged like configuration files), `veyra/provisioning/directory.py`;
enabled extensions and ring groups sorted by name. The Yealink family uses
it; the Poly `dir.corp` wiring arrives with slice F.

## 6. Vendor redirect services

A **Redirect services** section on the Provisioning page: the installation's
provisioning URL (HTTPS, with the enrollment credential form), per-vendor
instructions (Yealink RPS, Poly ZTP, Grandstream GDMS), and *Export MACs*
(CSV of the devices of a manufacturer with the URL) for bulk registration in
the vendor portal. Direct API registration is P2 (vendor accounts, module).

## 7. Hardware verification (#34)

A checklist per model, recorded in the template's `status` and in
DEVICE_PROVISIONING.md §9: boot from the provisioning URL over HTTPS with
the enrollment credential; registration; line keys (BLF lamp, speed dial,
page key pages a zone, user slot filled from My Phone); voicemail MWI and
callback; DST rule; VLAN; firmware upgrade from an uploaded image; polling
and NOTIFY re-provision; the new key types of §3 that the model supports.
The owner runs it on the VVX 411 and 450; the result moves the Poly family
to `stable`.

*Built 2026-10-20 (slice F, part 1):* `poly.edge.e` (Edge E100–E550) and
`poly.ccx` (CCX 350–700, Open SIP; the paging block is empty because the CCX
has no Push-to-Talk) on the shared Poly base; the provisioning server answers
Poly's own `<MAC>-directory.xml` request with the organization's directory;
`GET /devices/export.csv?manufacturer=` (MACs plain and with colons, model,
label, provisioning URL) and a *Redirect services* card on the Provisioning
page with per-vendor instructions and exports; the checklist in
[PROVISIONING_HARDWARE_CHECKS.md](PROVISIONING_HARDWARE_CHECKS.md). Still
open: Edge V (format not published), the owner's hardware runs, Grandstream
and CyberData on request.

## 8. Slices and order

A. Variables: model, migration, resolution, API, re-provision on change,
   templates `vars.*`, key and zone `$name` references, Variables page and
   tabs, tests. (#76)
B. Key types: facts and generator (park slot hints), Poly mapping, editor,
   docs. (#40)
C. Yealink family + directory endpoint (`yealink`, `poly` formats). (#35, §5)
D. Grandstream family + ATA. (#36, #37)
E. Algo and CyberData. (#38)
F. Poly Edge and CCX; redirect services section; VVX checklist and the
   owner's hardware run. (#39, §6, #34)

Each slice lands as its own commit with tests and a progress comment on its
issue; the milestone releases as 0.27.0 after F, with the Poly hardware
results recorded.

## 9. Testing

Unit tests per family render a sample device with every key type and the
variables resolved from four scopes, and compare against golden files
committed next to the templates (`tests/golden/<family>/`), so a change to
the facts shows up in every family at once. API tests for the variables
(scopes, precedence, in-use refusal, preview) and the directory formats.
The installer is untouched; `verify.sh` unchanged.

## 10. Open questions for the owner

1. Which Yealink models are in the fleet (conference phones were
   mentioned: CP series?) so the first Yealink set matches.
2. The Algo models and firmware versions in the buildings, and whether
   the AND clocks should get a template (they take an IPClockWise
   configuration, not SIP provisioning, so probably not).
3. Whether the VVX hardware check can happen on a spare phone before the
   rollout (the checklist takes about an hour per model).
