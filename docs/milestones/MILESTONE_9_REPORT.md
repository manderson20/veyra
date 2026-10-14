# Milestone 9 Report — Device Provisioning

Branch `milestone-9` (from `main` at 0.10.0). Reference:
[DEVICE_PROVISIONING.md](../DEVICE_PROVISIONING.md). Status: **delivered,
awaiting the owner's upgrade of dev1, hardware checks and approval.**

## 1. Scope (owner requirements of 2026-10-14)

1. Group device brands and models that share settings → template
   families (inheritance chain) with model templates under them.
2. Separate the same settings by use, e.g. per building → **device
   profiles** (template family + values + line keys + paging zones +
   firmware); the phone's model picks the concrete template.
3. Multicast for the speakers, Poly paging groups for the phones, in sync
   → **paging zones** carrying both the speakers' multicast group and the
   Poly group number, rendered into the phones; the Veyra page sender that
   emits both formats together is Milestone 9c.
4. Templates editable in the web interface → in-place editor for local
   templates and **Customize** for official ones.
5. Emergency caller ID per extension (asked the same day) → delivered first
   (§12 of the design), with a site default.
6. Firmware management → images uploaded, assigned per profile or phone,
   served by NGINX, compared with what the phone reports.
7. Fleet: AND clock speakers, Algo ceiling speakers and SIP horns, Yealink
   conference phones, Poly VVX 410 and 411 (only the Poly phones need Poly
   paging groups) → the VVX 411 template also serves the VVX 410; zones
   expose address, port and group number so templates match the speakers.

Also recorded for later milestones (roadmap rows 9b, 9c, 11): flyout
navigation and dashboard graphs; recordings upload for bells, calendar-driven
bell schedules (Google Calendar or any iCal feed), an audio library, shared
voicemail inboxes, messages to AND clock displays as an installable module;
a free module catalog on GitHub and custom module upload.

## 2. Results

* **Data model** (migrations `0010`, `0011`): `extensions.emergency_caller_id_number`,
  `sites.emergency_caller_id_number`, organization enrollment credential,
  `paging_zones`, `device_profiles` + `device_profile_paging`,
  `firmware_images`, `provisioning_requests`, and the device columns
  (profile, lines, keys, values, credential, last seen, firmware).
* **API**: `/sites`, `/paging-zones`, `/device-profiles`, `/devices`
  (+ `unregistered`, `preview`, `reprovision`), `/provisioning/firmware`,
  `/provisioning/models`, template `PUT`/`DELETE`/`customize`,
  `/organizations/{id}/provisioning-credential[/rotate]`. Permissions
  `paging.read`/`paging.write` added; `devices.*` now used.
* **Provisioning server** (`/provisioning/<file>`, outside `/api/v1`):
  HTTP Basic with the enrollment credential (`veyra-<org slug>`) or the
  per-device credential (`dev-<mac>`) that the phone's own configuration
  sets; files rendered on request; uploads from phones accepted and
  discarded; every request logged (device status, unregistered phones).
* **Templates**: spec version 2 with structured facts and DST rules from
  the zone database; Poly VVX templates 0.2.0 (lines, line keys, BLF with
  `**` pickup, MWI, group paging, DST, VLAN, polling, device credential);
  previews with sample facts; editor and Customize (a customized family
  gets local model templates).
* **Engine**: `max_contacts` for extensions on several phones;
  Veyra-managed `pjsip_notify.conf`; NOTIFY through the Asterisk CLI.
* **Installer**: NGINX locations and rate limit, opt-in HTTP block,
  `VEYRA_PUBLIC_HOST`/`VEYRA_PROVISIONING_HTTP`, `pjsip_notify.conf` stub,
  control socket for the service account (`asterisk.conf`, one restart),
  firmware directory, five new verify checks.
* **Interface**: Sites, Paging Zones, Devices (list with "phones seen but
  not registered", detail with settings, line keys, configuration preview,
  status, Reprovision, Reboot), Device Profiles, Firmware, template Edit
  tab and Customize, Phones card on the extension page, provisioning
  credential card on the organization page.
* **Privacy**: identifying organization names removed from tests and docs
  (owner rule of 2026-10-14); git history before that commit still has the
  old test fixture names.

## 3. Testing (final tree, 2026-10-14)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (120 files) |
| Backend pytest against PostgreSQL | **292 passed** (new: emergency caller ID in the API, snapshot and generator; sites CRUD and emergency default; paging zone validation, uniqueness, Poly address consistency, in-use; device profile resolution of a family to model templates, values, keys and paging validation; device registration, template resolution, overrides, search, status and unregistered list; firmware upload, assignment and in-use; enrollment credential rotation and scoping; DST rules for US, UK, Australia, UTC, Tokyo; device preview with lines, keys, paging and DST; the provisioning server's authentication paths, master file, uploads, disabled devices, credential rotation; snapshot contact counts and site default; reprovision audit; template editor save, validation, customize with model children, delete and in-use) |
| `alembic check` | No drift; `downgrade 0010`/`0009` and `upgrade head` clean |
| Installer `tests/test_lib.sh` | **45 passed**; `shellcheck` clean; `upgrade.sh --dry-run` clean (shows the control-socket change) |
| Frontend lint / typecheck / vitest | Clean / clean / **30 passed** |
| Frontend `npm run build` | Passed; `/sites`, `/paging-zones`, `/devices`, `/devices/view`, `/device-profiles`, `/device-profiles/view`, `/firmware` exported |
| **Owner's `upgrade.sh` on dev1** | *Pending* |

### Live checks on dev1

*Pending the owner's upgrade.* From the session afterwards: `verify.sh`
(expect `prov-location`, `prov-auth`, `prov-http`, `firmware-dir`,
`engine-cli`, `engine-stub:pjsip_notify.conf`), create a site, a zone, a
profile and a device for a test extension, fetch the files with `curl`
using the enrollment credential and then the device credential, check the
request log and status on the Devices page, and send a `check_config`
NOTIFY to a registered software phone.

## 4. Not verified

* Real Poly VVX 410/411/450 phones: first boot against the server, the
  certificate (§3.3 of the design), BLF lamps, `**` pickup from a BLF key,
  MWI, DST, group paging between two phones in one zone, a phone in another
  profile not hearing it, firmware update, Reprovision and Reboot. These
  need the owner's handsets (§6).
* Yealink and other brands: no official templates yet; the editor and
  import allow local ones.
* The Poly group-page wire format (needed for the Milestone 9c sender) is
  undocumented; the plan is a packet capture between two of the owner's
  phones.

## 5. Known limitations

* One Poly paging address and port per organization (zones differ by
  group number); zones that disagree are flagged.
* Sending pages, bell schedules and recordings are Milestone 9c; until
  then phone-originated pages reach phones only.
* Firmware is uploaded by the administrator; Veyra does not fetch it from
  the vendor.
* Hot desking, expansion modules, directory and background images are
  later.
* Provisioning over plain HTTP is an explicit opt-in with a visible
  warning; SIP secrets then cross the LAN unencrypted.
* The installer restarts Asterisk once to open the control socket.

## 6. Open items

* Owner: upgrade dev1 from `~/veyra` on `milestone-9` (`sudo
  installer/upgrade.sh --yes`; one Asterisk restart), then the live checks
  of §3 run from the session.
* Owner: decide how the phones trust the server (trusted certificate,
  per-phone CA install, or HTTP on a staging VLAN; design §3.3), then the
  hardware checks of §4 with a VVX 411 and a VVX 450.
* Owner: answers to the paging questions (design §5.3): speaker models and
  whether they can receive Poly group pages, the relay, who originates
  pages, the multicast addresses per building, existing Poly groups.
* From earlier milestones: the M5, M7 and M8 handset checks; the M7 test
  objects on dev1 (extension 22215, prompt `m7-test-tone`, menu "M7 test
  menu").

## 7. Proposed next milestones (awaiting approval)

* **9b — Interface rework** (0.12.0): flyout navigation (categories in
  the left menu, items in a flyout, no scrolling) and dashboard graphs of
  active channels and internal versus external calls.
* **9c — Paging and recordings** (0.13.0): paging zones dialable from any
  phone; the Veyra page sender emitting plain multicast and Poly
  group-page format together (phones in sync with speakers); calendar-driven
  bell schedules (a Veyra calendar linked to Google Calendar or any iCal
  feed, each event start triggering a chosen page); an audio library
  (MP3/WAV) reused by prompts, greetings and bells; shared voicemail
  inboxes; messages to AND clock displays as an installable module.

The owner may take 9b before 9c or the other way round.

## 8. Owner decisions

* 2026-10-14: requirements 1–7 of §1 and the privacy rule (nothing
  identifying the school in the repository or the product wording).
* Approval: *pending*.
