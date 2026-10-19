# Milestone 20 Report — User portal

Branch `milestone-20` (from `main` at 0.25.5). Design:
[USER_PORTAL.md](../USER_PORTAL.md). Status: **released as 0.26.0 on 2026-10-19 (slices A–G);
fax (slice H, #77) released as 0.26.3 on 2026-10-19 from branch `fax-0.26.3`**.
Issues #31, #32, #33, #60, #75, #77, #78 under "M20 — User portal". Pull
request #90.

## 1. Scope (roadmap row 20)

The FreePBX UCP in Veyra's style ([FREEPBX_GAP_ANALYSIS.md](../FREEPBX_GAP_ANALYSIS.md)
§4 item 2): voicemail inbox and greetings, self-service controls within the
administrator's limits, own call history with recordings, personal contacts
and speed dials, presence, user-set phone keys with administrator-locked
keys, fax, and a per-user widget canvas with administrator templates.

## 2. Results

| Slice | What a user gets | Where | Issue |
|---|---|---|---|
| A | Voicemail web inbox: folders, play, download, move, forward, delete; shared inboxes too | My Phone → Voicemail widget (Messages); Voicemail page → Messages (administrators) | #31 |
| B | Greetings: unavailable, busy, name, temporary — play, upload, **record in the browser**, remove | Voicemail widget (Greetings) | #32 |
| C | Personal contacts (up to five numbers, email, notes), favourites, speed-dial slots, search, CSV import/export, click-to-dial | Contacts widget | #60 |
| D | Recent calls with the other party named from the contacts, filter, call back, CSV export; recordings of own calls when the organization allows it; forwards respect the class of service | Recent calls widget; organization page switch | #60, #33 |
| E | Presence (available, away, busy, meeting, lunch, out) with a message and automatic actions (DND, forward); colleagues with presence, registration and on-call state | Presence and Colleagues widgets; `/directory` | #60 |
| F | Own phone keys in the slots a profile leaves open ("User's choice"); every other key locked; speed dial from a contact or BLF on a colleague; phone reprovisioned | Phone keys widget; key editor | #75 |
| H | Fax: send a PDF from My Phone (cover sheet, state, retry, cancel, PDF); inboxes "Fax to email" as a destination for DIDs and routes; T.38 per trunk; who may fax per class of service; administrators' Fax page | Fax widget; Telephony → Fax; destination pickers; trunk and class-of-service forms; organization page | #77 |
| G | The canvas: tabs of widgets the user drags, resizes, adds and removes (keyboard arrows too), undo, save, reset; administrators' default layouts by role, department, building, organization or system with locked widgets and "push to users" | My Phone; System → Portal Layouts | #78 |

### Platform pieces

* **`veyra-vmstore.service`**: a small helper that runs as the asterisk user
  and serves Asterisk's voicemail spool over `/run/veyra/vmstore.sock` with a
  fixed set of verbs on validated paths (list, read, move, delete, copy,
  greetings). The API gains no file access. The installer installs it and
  `verify.sh` checks it (`vmstore`); `voicemail.conf` polls mailboxes so MWI
  follows web changes.
* **`me` routes** (bearer scope `me`, own objects only, audited with
  `self_service`): voicemail messages and greetings, contacts, calls export
  and recording, presence, devices and keys, portal layout.
* **Administrator parity**: the same message and greeting routes under
  `/voicemail/{id}`, the user's keys on the device, portal templates under
  `/portal-templates` (permission `portal.templates`).
* **Migrations** `0047`–`0051`: `user_contacts`,
  `organizations.users_play_own_recordings`, presence on `extension_states`,
  `devices.user_keys`, `portal_templates`.
* **Frontend**: `src/portal/layout.ts` (pure grid engine, unit-tested),
  `src/portal/widgets.ts` (registry and the default layout), the canvas and
  the widget components under `components/portal/`.

### Deviations from the design

* Message audio is returned whole (no byte ranges; messages are small); the
  `msg_id` guard travels in the request rather than `If-Match`.
* The Companion keeps its own speed dials; it will read `/me/contacts` in its
  next version (no data migration).
* No engine lamp for presence yet (`Custom:veyra-presence-…` arrives with
  the presence key type); the directory is the presence source.
* Building and department scopes for templates exist in the API and the
  resolution but take an id in the editor until those pages exist.
* The announcement widget's text lives in the template's widget settings.
* **Fax (slice H) shipped as 0.26.3**, not in 0.26.0: the destination kind,
  tables, dialplan, service, worker, installer packages and pages came as a
  patch series (USER_PORTAL.md §9 "Built"). The user's faxes go over the
  organization's outbound routes (no separate fax trunk choice); a call that
  never connects is retried from the hang-up cause, a failed transmission
  once more.

## 3. Testing

Backend: every slice has API tests (`test_vmstore.py`,
`test_api_voicemail_inbox.py`, `test_api_contacts.py`,
`test_api_portal_calls.py`, `test_api_presence.py`, `test_api_user_keys.py`,
`test_api_portal_layout.py`, `test_fax.py` for 0.26.3), the migrations check passes at `0052`, mypy
and ruff are clean; the full suite was run after each slice. Frontend:
typecheck, lint and vitest (the layout engine has its own tests). CI on pull
request #90 per increment.

Lesson recorded: the audit listing filters by `q`, not by an `action`
parameter — the new tests filter events by action themselves.

### Live checks on dev1

To be done after the 0.26.0 install (migrations 0047–0051, unit
`veyra-vmstore`): leave a message on 22215 from a phone and play, move and
delete it from My Phone (MWI follows); record a greeting in the browser and
hear it with `*97`; add a contact and call it; set presence to "In a
meeting" with a DND rule and see the phone's DND lamp; add "User's choice"
slots to a profile, set a speed dial from My Phone and watch the Poly
reprovision; arrange the canvas, save, reload; make an organization template
with a locked announcement and see it on a user's page.

## 4. Not verified

Browser recording on the owner's browsers (MediaRecorder codecs), the
`veyra-vmstore` unit under `ProtectSystem=strict` on a real spool, Poly
rendering of an empty "user" slot, drag and resize on touch devices, the
template resolution with real buildings and departments.

## 5. Known limitations

No call-me-to-play, no voicemail reports, no missed-call email, no WebRTC
phone, no user-group object (roles and departments stand in), modules cannot
contribute widgets yet, no `faxdetect` on voice DIDs, no fax trunk choice
per organization.

## 6. Open items

Companion reading `/me/contacts`; presence lamp with the
key type; buildings and departments pages (M21/M22) to complete the template
editor; #84/#85/#88/#89 Updates cleanup (M22).

## 7. Next milestone

Milestone 21 — provisioning breadth (roadmap row 21), after the owner's go.
