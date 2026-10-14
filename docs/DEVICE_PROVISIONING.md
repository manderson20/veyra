# Device Provisioning (Milestone 9)

Design and reference for Milestone 9: phones registered by MAC address,
configuration files served over HTTPS from the provisioning templates,
templates edited in the web interface, device profiles that separate one
template family by use (for example one profile per building), paging zones
written into the phones, and hardware validation on the Poly VVX 411 and
VVX 450 the district uses.

Status: design (2026-10-14). Sections marked *(later)* are out of scope for
this milestone and listed so the data model does not paint us into a corner.

Owner requirements (2026-10-14) this design answers:

1. Group device brands and models: most models share common settings.
2. Separate the same settings by use, for example per building, where the
   only difference is multicast paging.
3. Use multicast for the speakers and Poly paging groups for the phones, so
   the phones page in sync with the speakers instead of through a relay.
4. Templates must be editable in the web interface.
5. (Asked the same day) A place for an **emergency caller ID** per
   extension, separate from the regular caller ID: delivered first in this
   milestone (§12) because it is small and safety-relevant.

## 1. Objects

| Object | Table | Scope | Purpose |
|---|---|---|---|
| **Template** | on disk (official, community) or `provisioning_templates` (local) | platform or organization | Files a phone downloads, rendered from variables (`PROVISIONING_TEMPLATES.md`). Unchanged, plus: editable local templates, structured facts (§4), spec version 2 |
| **Device profile** | `device_profiles` | organization | A template (family or model) plus values and paging-zone memberships: "VVX, High School", "VVX, Middle School", "VVX, District Office". Devices point at a profile |
| **Device** | `devices` (exists since Milestone 0, unused) | organization | A physical phone: MAC, manufacturer, model, label, site, profile, primary extension, extra line keys, per-device value overrides, provisioning credential and status |
| **Paging zone** | `paging_zones` | organization | A multicast page group: the speakers' address and port, the Poly group number, codec, kind (normal, priority, emergency). Profiles subscribe devices to zones |
| **Provisioning request** | `provisioning_requests` | platform | Log of what asked for which file from where (MAC, address, user agent, result); feeds the device "last seen" status and the unknown-device list |

### How the four requirements map

* **Brand and model families** are the template inheritance chain that
  already exists: `poly.vvx.base` (abstract, common settings) → `poly.vvx.411`,
  `poly.vvx.450` (model specifics). A local template can sit anywhere in
  the chain: `district.poly.vvx` (parent `poly.vvx.base`, district-wide
  changes) with the official model templates untouched. The catalog shows
  templates grouped by manufacturer and family.
* **Separation by use** is the device profile. A profile names a template
  key, which may be **abstract** (a family): when a device is rendered, the
  concrete template is the family's descendant that lists the device's
  model, preferring local templates. So "VVX, High School" and "VVX, Middle
  School" both point at `district.poly.vvx`, carry identical values except
  their paging-zone memberships, and serve a VVX 411 and a VVX 450 alike.
* **Paging** is a first-class object (§5) rendered into the phones from
  the profile's memberships; the phones get the Poly group-page settings
  that match the speakers' multicast groups. Sending pages from Veyra and
  bell schedules are Milestone 9c.
* **Editable templates**: local templates get an editor (§7); official
  templates stay read-only and "Customize" creates a local child.

## 2. Devices

Columns (existing in bold, new in plain text):

| Column | Notes |
|---|---|
| **organization_id**, **site_id** | Site is the building; defaults from the profile's site when set |
| **mac_address** | 12 lower-case hex digits, unique platform-wide |
| **manufacturer**, **model** | From the catalog's model list (every non-abstract template's `models`), free text allowed for unmanaged devices |
| **label** | "Room 112", optional |
| `profile_id` | FK `device_profiles`, nullable (a device without a profile is inventory only, nothing is served) |
| **template_key** | Dropped: the profile owns the template |
| **primary_extension_id** | Line 1. Nullable: a phone with no extension renders with registration omitted |
| `lines` | JSONB list of extra registrations `[{"extension_id": …}]` (line 2+); extensions of the same organization |
| `keys` | JSONB list of line keys (§4.2) overriding the profile's keys |
| `values` | JSONB `{variable: value}` per-device overrides of the profile's values (never `sip_password`) |
| `provisioning_secret_ciphertext` | Per-device HTTP credential (§3.2), encrypted with the installation key like SIP secrets |
| `last_seen_at`, `last_seen_ip`, `last_user_agent`, `last_result` | From the request log |
| `firmware_reported` | Parsed from the Poly user agent (`PolycomVVX-VVX_450-UA/6.4.5.1234`) |
| `is_enabled` | Disabled devices get 403 and are not rendered |

Rules: a MAC can belong to one device; an extension can be line 1 of
several devices (hot desks are *(later)*; today a shared extension simply
registers twice, which PJSIP allows with `max_contacts` ≥ 2, set by the
generator when an extension is on more than one device). Deleting an
extension clears the device's line and keys that pointed at it. Deleting a
device revokes its credential; the phone keeps its last files until it is
reset.

Device status shown in the list: **never provisioned** (no request),
**provisioned** (last request within the polling interval, 200), **stale**
(older than two polling intervals), **error** (last request failed:
unauthorized, disabled, render error). "Reprovision" sends a SIP NOTIFY
`check-sync`/`polycom-check-cfg` to the phone's endpoint (§3.4).

## 3. Delivery

### 3.1 URLs and files

The phone's provisioning server is `https://<VEYRA_PUBLIC_HOST>/provisioning/`.
Poly phones request, in order, `000000000000.cfg` (ignored, 404), then
`<MAC>.cfg` (master file naming the files to load), then each file named
in it. Veyra serves exactly the files the resolved template produces for
the device, under their rendered names, plus `000000000000.cfg` as an empty
master so phones do not log an error. Everything is rendered on request
(no files on disk; rendering is milliseconds) and never cached, so a change
in Veyra is live at the phone's next check.

Phones also upload logs, call lists and overrides (`<MAC>-phone.cfg`,
`<MAC>-app.log`, `<MAC>-directory.xml`) with PUT. Veyra answers 200 and
discards them (option *(later)*: keep logs for troubleshooting). Firmware:
the master file's `APP_FILE_PATH` points at `/provisioning/firmware/<file>`
only when an administrator uploaded a firmware image for the model (§7,
optional); otherwise it is left blank and the phone keeps its software.

NGINX gets a `location /provisioning/` proxied to the API with its own rate
limit (per address, 60 requests per minute, burst 30: a phone fetches four
to six files in a burst at boot) and a `location /provisioning/firmware/`
served by NGINX from `/var/lib/veyra/firmware/` (large files, byte ranges).

### 3.2 Authentication

HTTP Basic over TLS, two credential kinds:

* **Organization enrollment credential**: username `veyra-<org slug>`,
  password generated per organization (shown once, rotatable). Entered on
  the phone by hand (Settings → Provisioning Server) or via DHCP option 66
  with the URL form `https://user:pass@host/provisioning/`. It serves files
  for registered, enabled devices of that organization only.
* **Device credential**: after the first successful fetch, the rendered
  files set `device.prov.user`/`device.prov.password` to a per-device
  credential (`dev-<mac>` plus a 24-character secret), so from then on the
  phone authenticates individually. Rotating the enrollment credential does
  not touch provisioned phones; revoking a device invalidates its own
  credential.

Checks on every request: credential valid → device exists for the MAC in
the URL → device enabled → organization matches the credential → render.
Failures return 401 or 404 without saying which (the request log says).
Unknown MACs seen with a valid enrollment credential are listed in the
Devices page as "unregistered phones seen" so the technician can add them
with one click (the MAC and model from the user agent are pre-filled).

Sensitive values (`sip_password`, the device credential) are only rendered
for an authenticated request; preview in the interface masks them.

### 3.3 Transport and certificates

HTTPS only by default. Poly phones ship with a CA bundle covering public
CAs; dev1's self-signed certificate is not trusted, so until the owner's
trusted certificate (planned with the reverse proxy and domain name) is in
place, the phones need either the certificate installed via the phone's
web interface (`Settings → Network → TLS → Custom CA`, one-time per phone)
or plain HTTP. The installer gains an opt-in `VEYRA_PROVISIONING_HTTP=1`
that adds a plain-HTTP server block serving **only** `/provisioning/`
(credentials still required). The Devices page shows a warning while HTTP
provisioning is on, because SIP secrets then cross the LAN unencrypted.
Recommended path: a trusted certificate; HTTP for a staging VLAN only.

### 3.4 Reprovision

Asterisk sends `NOTIFY Event: check-sync` to a PJSIP endpoint with
`pjsip send notify <name> endpoint <endpoint>`; the names live in
`pjsip_notify.conf` (`polycom-check-cfg` is the Poly one). The generator
writes a Veyra-managed `pjsip_notify.conf` (stub like the others) and the
worker runs the CLI command through the deployer's existing Asterisk
access. The device page gets "Reprovision" (check config) and "Reboot".
Best effort: a phone that is not registered just does not get the NOTIFY.

## 4. Templates: spec version 2

Spec version 1 stays valid. Version 2 adds structured facts available to
every template without declaring them, replacing hand-typed per-device
values for the things Veyra already knows:

### 4.1 Facts

| Name | Content |
|---|---|
| `device` | `mac`, `mac_upper`, `model`, `model_slug`, `label`, `manufacturer`, `site_name`, `site_slug`, `credential_user`, `credential_password` (sensitive) |
| `organization` | `name`, `slug` |
| `lines[]` | Registrations in order: `index` (1-based), `extension_number`, `sip_username`, `sip_password` (sensitive), `display_name`, `caller_id_name`, `caller_id_number`, `label`, `voicemail_number` (`*97`) |
| `keys[]` | Line keys (§4.2) with `index`, `type`, `label`, `value` |
| `paging` | `enabled`, `address`, `port`, `codec`, `groups[]` (`number`, `label`, `subscribed`, `transmit`, `kind`), `default_group`, `priority_group`, `emergency_group` (§5) |
| `server` | `sip_host`, `sip_port`, `transport`, `provisioning_url`, `ntp_server`, `timezone` (IANA), `dst` (§4.3), `pickup_prefix` (`**`), `group_pickup_code` (`*8`) |
| `features` | Booleans derived from the extension: `voicemail` (box exists), `blf` (any BLF key) |

The core scalar variables of version 1 (`sip_username`, `timezone`, …)
remain and are filled from line 1 for compatibility. Validation (`validate`)
allows the fact names; `coerce_values` leaves them untouched. Facts are
read-only objects: templates cannot declare variables with these names.

### 4.2 Line keys

A key list belongs to a profile (shared) and may be replaced per device.
Entries: `type` ∈ `line` (a registration, `value` = line index), `blf`
(`value` = extension or ring-group number; renders a hint subscription and
the pickup prefix for a ringing call), `speed_dial` (`value` = number),
`page` (`value` = paging zone slug: Poly phones page a group from a key),
`park`/`transfer` *(later)*. Labels default to the target's name. The
renderer resolves numbers to the organization's extensions and groups at
render time, so renamed targets update on the next check.

### 4.3 Daylight saving

`server.dst` is computed from the IANA zone for the current year with
`zoneinfo`: `enabled`, `start` and `stop` as `month`, `week` (1–5, 5 = last),
`weekday`, `hour`, and the standard offset in seconds. The Poly template
writes `tcpIpApp.sntp.daylightSavings.*` (fixed-day disabled, start/stop
month/week/day/time) and `tcpIpApp.sntp.gmtOffset` with the **standard**
offset, replacing the Milestone 0 fixed-offset workaround. Zones without
DST render `daylightSavings.enable="0"`.

### 4.4 Poly templates after this milestone

`poly.vvx.base` 0.2.0: registrations for every line, line keys
(`lineKey.x`, `attendant.resourceList.x` for BLF with
`call.directedCallPickupMethod="native"` and
`call.directedCallPickupString="**"`), `feature.enhancedFeatureKeys`,
voicemail (`msg.mwi.x.subscribe`, `msg.mwi.x.callBackMode="contact"`
to `*97`), group paging (`ptt.pageMode.*`, §5), DST rules, SNTP, VLAN,
device credential, polling (`prov.polling.enabled="1"`, daily at a random
minute between 01:00 and 05:00), local admin password variable,
`up.backlight`/`up.screenSaver` optional variables. Model templates keep
their `model_settings` block (VVX 450: 12 line keys plus expansion module
*(later)*; VVX 411: 12 keys). Status moves to `stable` only after the
hardware checks (§9).

## 5. Paging zones

Facts first. Poly VVX phones page and listen only in Poly's **group paging**
format: multicast RTP with a Poly-specific header carrying the group
number; one multicast address and port for all groups (default
224.0.1.116:5001), 24 groups plus group 25 for emergency, G.711 or G.722.
Plain multicast RTP (what most speakers and the Asterisk `MulticastRTP`
channel send) is **not** heard by a VVX. Paging adapters such as Algo and
CyberData can send both formats at once, and Algo documents that Poly
phones buffer about 200 ms in group-page mode, so a sender aligning the
two formats delays the plain-RTP stream by roughly that much.

What the owner has today: speakers listening to plain multicast directly,
and a relay that pages the phones separately, hence the lag. The fix has
two halves: the phones must be configured for the right Poly groups (this
milestone), and whatever originates a page must emit both formats in step
(Milestone 9c, the Veyra page sender; or an Algo/CyberData sender in
"both" mode in the meantime).

### 5.1 Zone object

| Field | Notes |
|---|---|
| `name`, `slug` | "High School", `high-school` |
| `site_id` | Optional, for grouping |
| `multicast_address`, `multicast_port` | The speakers' group, e.g. `239.1.2.10:5004`; validated as a multicast address (224/4) |
| `poly_group` | 1–25 (25 = emergency); unique per `(organization, poly_address, poly_port)` |
| `poly_address`, `poly_port` | The Poly paging address and port used by this organization's phones; defaults 224.0.1.116:5001, same for all zones of an organization (a Poly phone listens on one address). Kept per zone in the table, validated equal within an organization |
| `kind` | `normal`, `priority`, `emergency` (priority and emergency pages interrupt active calls on Poly) |
| `codec` | `G.711Mu` (default) or `G.722` |
| `is_enabled` | |

### 5.2 Memberships

`device_profile_paging` rows: `(profile_id, zone_id, subscribed, transmit,
role)` where `role` ∈ `default`, `priority`, `emergency`, none. The
renderer builds `paging.groups[]` from the profile's memberships (a device
cannot override memberships; move it to another profile). Rendered Poly
parameters: `ptt.pageMode.enable`, `ptt.address`, `ptt.port`,
`ptt.pageMode.codec`, `ptt.pageMode.group.N.label`, `.subscribed`,
`.allowTransmit`, `.allowReceive` (UC Software 5.2.3+),
`ptt.pageMode.defaultGroup`, `ptt.pageMode.priorityGroup`,
`ptt.pageMode.emergencyGroup`, `ptt.pageMode.transmit.timeout.continuation`.

### 5.3 What this gives the owner now

* Each building's profile subscribes its phones to that building's zone;
  the phones can page each other and any Poly-format sender (a Poly phone's
  Paging key, an Algo in Poly mode) reaches them.
* Speakers keep their plain-multicast groups; zone records hold both so
  Milestone 9c can page a zone with one action and both audiences hear it
  together.

Open questions for the owner (answers go into §11): speaker brand and model
(do they also support Poly group paging as receivers?), what the current
relay is (device, SIP auto-answer, software), who originates pages today
(a phone, a bell controller, the PBX), the multicast addresses and ports in
use per building, and whether any Poly paging groups are already configured
on the phones.

## 6. Permissions and API

Permissions: `devices.read`/`devices.write` (exist: org admin, site admin,
technician write; read-only read), `provisioning.read`/`provisioning.write`
(templates; write stays org admin), new `paging.read`/`paging.write`
(org admin, site admin write; technician, read-only read).

```
GET/POST        /devices                      list (filters: organization, site, profile, status, q), create
GET/PATCH/DELETE /devices/{id}
POST            /devices/{id}/reprovision     {action: check_config | reboot}
GET             /devices/{id}/preview         rendered files, secrets masked
GET             /devices/unregistered         MACs seen with a valid enrollment credential, no device
GET/POST        /device-profiles
GET/PATCH/DELETE /device-profiles/{id}       template_key, values, keys, paging memberships, site
GET/POST        /paging-zones
GET/PATCH/DELETE /paging-zones/{id}
GET             /organizations/{id}/provisioning-credential   username, url, enabled flags
POST            /organizations/{id}/provisioning-credential/rotate   returns the new password once
PUT             /provisioning/templates/{key}           update a local template (manifest + sources)
POST            /provisioning/templates/{key}/customize {key, name} → local child of an official template
GET             /provisioning/models                    manufacturer → models from the catalog
POST            /provisioning/firmware                   upload (optional), GET list, DELETE
```

Phone-facing, outside `/api/v1`, mounted at `/provisioning/`:
`GET /provisioning/{file}` (Basic auth), `PUT /provisioning/{file}` (200,
discarded), `GET /provisioning/firmware/{file}` (NGINX). In-use rules:
deleting a profile with devices → 409 `profile_in_use`; deleting a zone
with memberships → 409 `zone_in_use`; deleting a template used by profiles
→ 409 `template_in_use` (local only; official cannot be deleted).

Audit: every create/update/delete, credential rotation, reprovision, and
failed provisioning fetches (rate-limited to one audit row per MAC per
hour).

## 7. Interface

* **Provisioning → Templates**: grouped by manufacturer and family; a
  local template opens in an **editor**: manifest fields (name, version,
  models, parent, status, description, variables with defaults and
  patterns) and a source editor per file (textarea with monospace font,
  line numbers, syntax check on save via `validate`), **Preview with a
  device** (choose a device, see the rendered files with secrets masked),
  and **Save as new version**. Official templates show "Customize" which
  creates a local child under a chosen key, pre-filled with the parent's
  file as an `{% extends %}` skeleton. Export/import stay.
* **Provisioning → Device profiles**: list; form with template (families
  first), values (one field per resolved variable, defaults shown), line
  keys editor, paging zone memberships (subscribe, transmit, role), site.
* **Provisioning → Devices**: list with status badges, filters, "Unregistered
  phones seen" panel; add form (MAC with any separators, manufacturer and
  model pickers, label, site, profile, extension, extra lines); device page
  with status, last request details, keys override, values override,
  preview, Reprovision and Reboot buttons, and the enrollment instructions
  (URL and credential name) for the technician.
* **Telephony → Paging zones**: list and form (§5.1).
* **Settings → Organizations**: provisioning credential card (URL, user,
  rotate, HTTP warning).
* **Extensions page**: a Devices card (which phones carry the extension).
* The "Devices" planned entry becomes real; "Paging" stays planned (9c).

## 8. Installer

* NGINX template: `location /provisioning/` with `limit_req` zone
  `veyra_prov`, `location /provisioning/firmware/` alias to
  `/var/lib/veyra/firmware/`; optional HTTP server block for provisioning
  (`VEYRA_PROVISIONING_HTTP=1` in `veyra.env`, re-run the installer).
* `/var/lib/veyra/firmware` (`750 veyra:veyra`).
* `pjsip_notify.conf` stub (`#tryinclude veyra/pjsip_notify.conf`), new
  managed file, reload scope `res_pjsip_notify.so` (not sensitive).
* `verify.sh`: `prov-location` (NGINX config contains the location),
  `prov-http` (reports whether HTTP provisioning is on, as a warning),
  `engine-stub:pjsip_notify.conf`, `firmware-dir`.

## 9. Testing

Unit: profile resolution (abstract family → model template, local
preferred, no match → error), facts (lines, keys, DST for
`America/Chicago`, `UTC`, southern hemisphere), paging rendering, Basic
auth paths (enrollment, device, wrong org, disabled, unknown MAC, rate
limit), master file contents, PUT discard, user-agent parsing, API CRUD
and in-use rules, audit rows, template editor save/validate/customize,
NOTIFY command building. Installer lib tests for the NGINX rendering.

Hardware (owner, dev1): factory-reset a VVX 411 and a VVX 450, set the
provisioning server (with the certificate or HTTP on a staging VLAN),
watch them appear under "Unregistered phones seen", register them, confirm
registration, caller ID, line keys and BLF lamps (extension and ring
group), `**` pickup from a BLF key, voicemail MWI and `*97`, DST/time,
group page between the two phones in one zone, a phone in a different
profile not hearing that page, Reprovision after a label change, and the
Milestone 5, 7 and 8 handset checks still open.

## 10. Known limitations (planned)

* One Poly paging address per organization; zones differ by group number.
* Sending pages from Veyra, bell schedules and Poly-format emission are
  Milestone 9c; until then, phone-originated pages reach phones only.
* Firmware upload is optional and manual; no automatic download from Poly.
* Hot desking, expansion modules, directory and background images are
  later.
* Only Poly VVX templates are official; other brands arrive as community
  or local templates (the editor makes that possible from the interface).
* Provisioning over HTTP is a deliberate opt-in with a visible warning.

## 11. Decisions and answers

* 2026-10-14: scope and requirements from the owner (above). Open
  questions of §5.3 sent; answers to be recorded here.

## 12. Emergency caller ID per extension

Today an emergency route sends the route's `caller_id_number` (one per
route), else the trunk's default, else the extension's regular caller ID.
There is no per-extension value, so a district with several buildings on
one route cannot present the building's ELIN or DID.

Change: `extensions.emergency_caller_id_number` (optional, digits, 3–20)
and `sites.emergency_caller_id_number` (default for the site's
extensions). Precedence on an emergency route: extension → site → route
`caller_id_number` → trunk default → regular caller ID. The snapshot
resolves extension-or-site into a per-endpoint `set_var=VEYRA_EMERGENCY_CID=…`
and the emergency branch of the outbound context runs
`ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]?Set(CALLERID(num)=${VEYRA_EMERGENCY_CID}))`
before dialling, so the route override no longer wins over a more specific
value. The Extensions form and page get an "Emergency caller ID" field
beside the regular caller ID; the site form gets the default; the Outbound
Routes warning list adds "N extensions have no emergency caller ID and no
site default" when an emergency route has no caller ID of its own. The
WARNING log line gains the number presented. Migration `0010`.
