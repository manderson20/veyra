# User Portal (Milestone 20)

Design for roadmap row 20 ([ROADMAP.md](ROADMAP.md);
[FREEPBX_GAP_ANALYSIS.md](FREEPBX_GAP_ANALYSIS.md) §4 item 2, §3.6, §3.8,
§3.10): the self-service area for standard users, FreePBX's UCP in Veyra's
style, web first and Companion second. Milestone 18 built the first slice
([CALL_FEATURES.md](CALL_FEATURES.md) §3.9): **My Phone** with the `me` API
(own extensions, Do Not Disturb, forwards, find me / follow me, voicemail
PIN, feature codes, Companion speed dials, own call history). This
milestone adds the voicemail web inbox and greetings (#31, #32), confirms
the self-service controls within administrator limits (#33), own call
history with recordings (#60), personal contacts and speed dials (#60),
presence (#60), user-set phone keys with administrator-locked keys (#75),
fax (#77) and the widget canvas with administrator templates (#78).
Version 0.26.0.

Scrubbing note: examples use the organization slug `example`.

## 1. Principles

1. **Own objects only, through the `me` scope.** Everything a user reaches
   is tied to their account: extensions with `user_id` = the caller,
   voicemail boxes of those extensions plus shared boxes they are a member
   of, devices assigned to those extensions, their own contacts and
   layouts. The `me` routes never take an organization or a permission;
   `_own_*` helpers return 404 for anything else (CALL_FEATURES §3.9).
2. **Administrator parity.** Whatever a user can do to their own objects,
   an administrator with the matching permission can do for any user
   (voicemail inbox and greetings under `/voicemail/{box}`, keys under
   `/devices/{id}`, layouts under `/portal-templates`), so support staff can
   help without the user's password.
3. **Limits are the administrator's.** Class of service (CALL_FEATURES
   §3.8) decides external forwards and follow-me legs; the device profile
   decides which key slots are the user's (§8); an organization setting
   decides whether users may play their own recordings (§5); the portal
   template decides which widgets a user cannot remove (§10).
4. **Audited like the administrator's actions**, with `self_service: true`
   (`voicemail.message_play`, `voicemail.message_delete`,
   `voicemail.greeting_set`, `device.user_keys`, `contact.*`,
   `portal.layout`, `fax.send`), and visible on the account's own
   "Recent activity".
5. **No new privileges for the service account.** Voicemail files belong to
   the asterisk user; the API reaches them through a small helper that runs
   as that user (§2.2), the same way backups and captures use root units
   through polkit. The API process itself gains no file access.
6. **State lives in the database** (CALL_FEATURES §1): presence, contacts,
   user keys and layouts are rows; the engine and the phones are derived.

## 2. Voicemail web inbox (#31)

### 2.1 What the user sees

A **Voicemail** widget/page per box the user may see (own extensions'
boxes and shared boxes they are a member of): folders (New, Old, Work,
Family, Friends, Urgent — Asterisk's `INBOX`, `Old`, `Work`, `Family`,
`Friends`, `Urgent`), messages with date, caller ID (looked up against the
directory and the user's contacts), duration and a flag for urgent;
in-browser playback (`<audio>` with range requests), download (WAV),
move to a folder, delete, forward to another box the user may see (a copy
with a "forwarded by" note), mark as heard (move New → Old). Counts refresh
every 15 s while the widget is visible and on the `voicemail.message`
webhook event. "Call me to play" and voicemail reports stay P2.

### 2.2 The voicemail store helper

Messages live in Asterisk's spool, `/var/spool/asterisk/voicemail/<context>/
<mailbox>/<folder>/msgNNNN.{txt,wav,WAV,gsm}`, owned by the asterisk user;
on Ubuntu the spool root is `0750 asterisk:root`, so the service account
cannot even list it, and message directories are not group-writable.
Rather than loosening those modes, a helper runs **as the asterisk user**:

* `veyra-vmstore.service`: `User=asterisk`, `Group=veyra`, a Unix socket
  `/run/veyra/vmstore.sock` (0660 asterisk:veyra) served by
  `veyra vmstore serve` (the `veyra.voicemail.store` module, a line-oriented
  JSON protocol like the HA agent's). Operations: `list(context, mailbox,
  folder)` → message index entries parsed from `msgNNNN.txt` (`callerid`,
  `origdate`, `origtime`, `duration`, `flag`, `category`, `msg_id`);
  `read(context, mailbox, folder, n)` → the audio file (format preference
  wav, WAV, gsm) streamed back; `move(...)`, `delete(...)`, `copy(...)` for
  forwarding; `greeting_get/put/delete(context, mailbox, kind)` (§3). Every
  argument is validated against fixed patterns (`[a-z0-9-]` context, digits
  mailbox, the six folder names, `msg\d{4}`, the four greeting kinds) and
  the resolved path must stay under the spool root (no links followed).
* **Locking and renumbering**: Asterisk locks a folder with `.lock` in the
  folder directory (`ast_lock_path`); the helper takes the same lock for
  move/delete/copy and renumbers `msgNNNN.*` afterwards so the sequence
  stays contiguous (Asterisk's `resequence_mailbox` expects that), writing
  the new `.txt` first and removing the old files last.
* **MWI**: `voicemail.conf` gets `pollmailboxes=yes` and `pollfreq=10`, so
  the engine notices external changes and refreshes the lamps and the
  `externnotify` counts (the `voicemail.message` webhook follows as today).
* The installer (steps.sh) installs the unit, creates `/run/veyra` for it
  (`RuntimeDirectory=veyra` is shared with the HA agent), adds a
  `vmstore` check to `verify.sh` (socket present, `list` of a known box
  answers), and the HA sync of the spool (HIGH_AVAILABILITY.md) is
  unaffected.
* The API client (`veyra.voicemail.client`) is used by the `me` routes and
  the administrator routes; without the socket (helper not running) the
  inbox shows "not available on this server" and the API answers 503
  `vmstore_unavailable`.

### 2.3 API

```
GET    /me/voicemail/{box_id}/messages?folder=INBOX     index (newest first)
GET    /me/voicemail/{box_id}/messages/{n}/audio?folder=  WAV, ranges, ?download
POST   /me/voicemail/{box_id}/messages/{n}/move          {folder}
POST   /me/voicemail/{box_id}/messages/{n}/forward       {box_id}
DELETE /me/voicemail/{box_id}/messages/{n}?folder=
```

The same five under `/voicemail/{box_id}/messages…` for administrators
(`voicemail.read` to list and play, `voicemail.write` to move, forward and
delete), audited with the box and message id. Message identity across a
renumbering uses the `msg_id` line of the `.txt` file (Asterisk writes one
since 11): the API accepts `{n}` and checks the `msg_id` the client sends
as `If-Match`, answering 409 `message_moved` when the index changed.

*Built 2026-10-19 (slice A):* `veyra.voicemail.store` (helper, verbs
`ping|list|read|move|delete|copy|greetings|greeting_get|greeting_put|
greeting_delete`), `veyra.voicemail.client`, `veyra.voicemail.service`
(index, errors → problems), routes under `/me/voicemail/{id}/messages…` and
`/voicemail/{id}/messages…`, unit `veyra-vmstore.service` (asterisk:veyra,
`ProtectSystem=strict` with the spool and `/run/veyra` writable), `verify.sh`
check `vmstore`, `pollmailboxes=yes`/`pollfreq=10`. Deviations: message
audio is returned whole (no byte ranges; messages are small) and the `msg_id`
guard is sent in the request body or query rather than `If-Match`. Not in
this slice: call-me-to-play, Companion playback.

### 2.4 Companion

The Companion shows the New count and the latest five with play; it
already receives the `voicemail.message` webhook-derived events over the
WebSocket. Not in this slice: playing in the extension's popup (P2).

## 3. Voicemail greetings (#32)

Four greetings per box, as Asterisk names them: `unavail` (unavailable),
`busy`, `greet` (the name) and `temp` (temporary, played instead of the
others while present). The user's **Greetings** card shows each with its
state (recorded or not, duration), play, upload, record in the browser,
delete, and "record from your phone" (the `*97` menu, as today).

* **Upload** goes through the existing audio pipeline
  (`telephony/audio.convert_any`: ffmpeg for compressed formats, output
  8 kHz mono WAV), checked against `maxgreet` (60 s; the API answers 422
  `greeting_too_long` with the duration).
* **Record in the browser**: `MediaRecorder` (webm/opus or ogg/opus, which
  ffmpeg converts), a level meter, 60 s limit, preview before saving. The
  page asks for the microphone only when the user clicks Record; the
  Content-Security-Policy stays as it is (no external origins).
* The helper writes `<kind>.wav` into the mailbox directory and removes
  other formats of that greeting (`<kind>.gsm`, `.WAV`), so the engine plays
  the new one; `greeting_delete` removes all of them.
* API: `GET /me/voicemail/{box_id}/greetings` (state per kind),
  `GET …/greetings/{kind}/audio`, `PUT …/greetings/{kind}` (multipart
  upload or the recorded blob), `DELETE …/greetings/{kind}`; the same under
  `/voicemail/{box_id}/greetings…` for administrators (`voicemail.write`).
  The box's `GET` now reports `greetings: {unavail: true, …}`
  (VOICEMAIL_IVR.md §3.3 asked for it).

*Built 2026-10-19 (slice B):* routes `GET /me/voicemail/{id}/greetings`,
`GET …/greetings/{kind}/audio`, `PUT …/greetings/{kind}` (multipart `file`;
`service.greeting_save`: `audio.convert_any` → 8 kHz mono WAV, 415
`unsupported_audio`, 422 `greeting_too_long` above 60 s), `DELETE
…/greetings/{kind}`; the same under `/voicemail/{id}/greetings…`
(`voicemail.read`/`voicemail.write`). Frontend `GreetingsPanel`
(MediaRecorder with a counter and preview; the recording is uploaded as
webm/opus and converted by ffmpeg) inside `VoicemailBoxPanel` (Messages |
Greetings). Deviation: the box's `GET` does not report greeting presence (it
would query the helper per box in lists); the greetings route does.

## 4. Self-service controls (#33)

Built in Milestone 18 (CALL_FEATURES §3.9). This milestone verifies and
closes the gaps: the `me` state route enforces the extension's class of
service like the administrator's route (no external forward when
`allow_external_forwards` is off → 422 `cos_denied`, same for follow-me
legs), the Companion exposes DND and the forwards, and call waiting is
documented as a phone-side setting (Poly `call.callWaiting.enable`) that the
provisioning template controls — not a Veyra toggle in this milestone.

## 5. Call history and recordings (#60)

`GET /me/calls` exists (last 30 days, outcome filter). This milestone adds
the **Recent calls** widget with the direction, the other party resolved
against the directory and the user's contacts, click-to-dial
(`calls.originate`, already a standard-user permission) and "add to
contacts"; and recordings the user took part in: `GET /me/calls/{id}/
recording` streams the recording when the organization allows it
(`organizations.users_play_own_recordings`, default **off**; the owner's
schools treat recordings as sensitive) and the user's extension was a
party. Playback is audited (`recording.play`, `self_service: true`) exactly
like the administrator's. Export to CSV of own calls: `GET /me/calls/
export.csv`.

## 6. Personal contacts and speed dials (#60)

Table `user_contacts`: `user_id`, `name`, `company`, `numbers` JSONB
(`[{label: work|mobile|home|other, number}]`, up to 5), `email`,
`favourite`, `speed_dial` (1–99, unique per user, nullable), `notes`,
timestamps; up to 500 per user. API `GET/POST /me/contacts`,
`GET/PATCH/DELETE /me/contacts/{id}`, `POST /me/contacts/import` (CSV:
name, company, numbers…, speed_dial), `GET /me/contacts/export.csv`.
Contacts resolve caller names on the user's call history and voicemail
list and feed the Companion (`/me/contacts?favourite=true` replaces
`companion.speed_dials`; a data migration turns existing Companion speed
dials into favourite contacts with the slot as `speed_dial`, and the
`companion.speed_dials` preference becomes read-only mirror for older
Companion versions until 0.27). Speed-dial **keys on the phone** come from
§8 (a user key of type `speed_dial` can pick a contact). The
organization-wide directory (`GET /directory`) stays separate.

## 7. Presence (#60)

`extension_states.presence` (`available`, `away`, `busy`, `meeting`,
`lunch`, `out`) and `presence_message` (60 chars), set from the portal and
the Companion (`PUT /me/extensions/{id}/presence`) and shown to colleagues
in the **Colleagues** widget and the directory (`GET /directory` adds
`presence`, `on_call` and `registered` for extensions the caller may see —
`directory.read`). Automatic actions per state are the user's choice
(`user_preferences.portal.presence_rules`: for each state optionally
`dnd: true`, `cf_always: <number or empty>`), applied through
`extension_state.apply` when the state changes, so the engine sees them
immediately (no deployment). A BLF hint `Custom:veyra-presence-<org>-<ext>`
(INUSE for busy/meeting, ONHOLD for away/lunch, UNAVAILABLE for out,
NOT_INUSE for available) lets a phone key show a colleague's presence
(key type later, with #40's park type). Not in this slice: phone-side
presence menus, calendar integration.

## 8. Phone keys set by the user, locked by the administrator (#75)

Owner requirement (2026-10-18): staff set their own speed dials and
similar keys, but keys like the district's **all-call line** must stay on
every phone no matter what the user does.

* **Profile**: a device profile's key list gains the type `user` — a slot
  left to the user, empty unless the user fills it. Every other key in the
  profile is the administrator's and is **locked**: the user sees it with a
  lock icon and cannot change or remove it. Existing profiles are unchanged
  (no `user` slots → nothing is editable), so the new behaviour is opt-in
  per profile. A device's own key override (`devices.keys`, administrator)
  keeps working and is equally locked for the user.
* **User keys**: `devices.user_keys` JSONB (migration): `{ "<slot index>":
  {type: speed_dial|blf, label, value, contact_id?} }`, only for slots the
  effective profile marks `user`; `blf` values must be an extension of the
  user's organization, `speed_dial` values a dialable number or a contact of
  the user. `GET /me/devices` lists the phones of the user's extensions with
  the slot map (locked keys read-only, user slots editable);
  `PUT /me/devices/{id}/keys` saves the user's slots, audits
  `device.user_keys` and reprovisions the phone (the existing
  `device.reprovision` path: check-sync; the phone reloads its
  configuration within a minute). Administrators see and edit the same map
  under `/devices/{id}` (`devices.write`).
* **Rendering**: `provisioning/facts._keys` builds the final key list:
  profile keys in order, a `user` slot replaced by the device's user key for
  that index (or an empty key when none), `devices.keys` (administrator
  override) still replacing the whole list when set. Templates need no
  change.
* Portal widget **Phone keys**: a picture of the key layout per phone
  (rows of keys with labels), locked ones greyed with the lock icon, user
  slots editable (type, label, target with a contact/extension picker).

## 9. Fax (#77)

Owner requirement (2026-10-18): a user uploads a PDF on My Phone and it is
faxed; inbound faxes arrive as PDF by email. `res_fax` and
`res_fax_spandsp` are loaded on dev1 already; Ghostscript and
`libtiff-tools` are not installed yet (installer adds them).

* **Model** `fax_jobs`: `organization_id`, `user_id`, `direction`
  (`out|in`), `number` (destination or caller), `pages`, `state`
  (`queued|dialling|sending|sent|failed|received`), `error`, `file`
  (TIFF path in `<data>/fax/<org>/<job>.tiff`, PDF beside it), `remote_id`
  (the remote station id), `trunk_id`, timestamps. Retention class `fax`
  (90 days default, `core/retention.py`).
* **Sending**: `POST /me/fax {number, file (PDF ≤ 20 MB, ≤ 50 pages),
  cover?: {to, from, subject, note}}` → Ghostscript renders the PDF (and the
  generated cover page) to a 204 dpi TIFF-G4 → the job is queued → the
  worker originates through ARI a `Local/<job>@veyra-fax-out` channel that
  the dialplan sends over the organization's outbound routes with the
  user's outbound caller ID (CALL_FEATURES §3.5) and runs
  `SendFAX(<tiff>,d)`; `FAXOPT(headerinfo/localstationid)` from the
  organization's fax header; a `UserEvent(VeyraFax, Job, Status, Pages,
  Error)` and `FAXSTATUS/FAXERROR/FAXPAGES` on hangup update the job (3
  attempts with backoff for busy/no answer). T.38 is used when the trunk's
  endpoint has `t38_udptl=yes` (new trunk flag `fax_t38`), audio (G.711)
  otherwise. The user sees their jobs (`GET /me/fax`) with state and reason
  and gets an email on sent/failed (mail queue).
* **Receiving**: a destination type `fax` (an inbound route or a DID
  pointed at "Fax to email": `fax_inboxes` with recipients and a name) →
  context `veyra-fax-in-<slug>`: `ReceiveFAX(<tiff>)` → `tiff2pdf` → the PDF
  is emailed to the recipients and filed as an `in` job. Optional
  `faxdetect=yes` on voice DIDs stays P2.
* **Administration**: Fax page (jobs of the organization, `fax.read`;
  retry/cancel with `fax.manage`), who may send (class of service flag
  `allow_fax`, default on), the organization's fax header, the trunk flag.
  Installer: packages `ghostscript`, `libtiff-tools`; `verify.sh` checks
  `res_fax_spandsp` loaded and the two tools present.
* This is the largest slice and comes last; if the milestone runs long it
  ships as 0.26.x right after, with the destination type and the tables in
  place from 0.26.0.

## 10. The portal canvas and templates (#78)

Owner requirement (2026-10-18): users arrange, resize, add and hide the
portal's modules and keep tabs; administrators build default layouts
assigned by group, building or system-wide, with widgets the user cannot
remove.

* **Widgets** are the portal's capabilities wrapped with a manifest in the
  frontend registry (`frontend/src/portal/widgets.ts`): `key`, `title`,
  `description`, default and minimum size in grid units, `settings` schema,
  and the data it needs (an extension, a box, a device). Set:
  `phone` (registration, DND, forwards, follow-me), `voicemail`,
  `greetings`, `calls`, `contacts`, `colleagues` (presence), `keys`, `fax`,
  `codes` (feature codes), `directory`, `announce` (paging a zone the user
  may page; `paging.send`). Modules can contribute widgets in a later
  version (MODULE_CATALOG.md); the manifest shape is designed for it.
* **Canvas**: a 12-column grid with 40 px rows, breakpoints at 1200/900/
  600 px (12/8/4 columns; widgets reflow by order below 600). Drag by the
  widget header, resize by the corner handle, both implemented in-house
  with pointer events (no new dependency); every drag action has a keyboard
  alternative in the widget menu (move up/down/left/right, grow/shrink,
  hide) and the grid announces positions for screen readers. Tabs across
  the top (add, rename, reorder, remove); an "Add widget" drawer; undo of the
  last change; "Reset to the default layout".
* **Storage**: the user's layout is one JSON document in
  `user_preferences.data.portal` (`{version, tabs: [{id, name, widgets:
  [{key, instance, x, y, w, h, settings}]}], template_id, hidden: [keys]}`,
  validated by a pydantic model, ≤ 64 KB), read and written through
  `GET/PUT /me/portal/layout`; `POST /me/portal/layout/reset` drops it.
* **Templates**: `portal_templates` (`organization_id` nullable for the
  system scope, `name`, `scope` = `system|organization|building|department|
  role`, `scope_id`, `layout` JSONB in the same shape, `locked_widgets`
  (keys that stay on the first tab and cannot be removed), `priority`,
  timestamps), edited with the same canvas on **System → Portal layouts**
  (`portal.templates`, organization-scoped, platform admins for the system
  scope). Resolution for a user: role → department (of their primary
  extension) → building (of that extension) → organization → system; the
  nearest wins; the user's own document layers on top (positions and
  hidden widgets), locked widgets are re-inserted if missing. "Push to
  users" resets the user documents under the template's scope (audited).
  Buildings and departments exist (`tenancy.py`); a user-group object
  stays P2 (roles and departments cover "groups" for now).
* **My Phone becomes the canvas**: the current page is the default
  template (phone, voicemail, calls, codes), so existing users see what
  they have today until they rearrange it.

## 11. Permissions and API summary

New permissions: `portal.templates` (org admins by default),
`fax.read`/`fax.manage` (org and site admins), `fax.send` is a class of
service flag, not a permission. `standard_user` keeps `calls.originate`
and `directory.read`; everything else rides on the `me` scope (bearer
tokens need `me`). New organization settings:
`users_play_own_recordings` (off), `fax_header` / `fax_station_id`.

```
me:        /me/voicemail/{box}/messages…, /me/voicemail/{box}/greetings…,
           /me/calls/{id}/recording, /me/calls/export.csv,
           /me/contacts…, /me/extensions/{id}/presence, /me/devices…,
           /me/fax…, /me/portal/layout…
admin:     /voicemail/{box}/messages…, /voicemail/{box}/greetings…,
           /devices/{id} (user_keys), /portal-templates…, /fax…
directory: GET /directory (+presence, on_call, registered)
```

Migrations: `0047` user_contacts, `0048` presence columns, `0049`
devices.user_keys, `0050` portal_templates, `0051` fax tables + trunk and
organization fields (last slice).

## 12. Testing

Unit and API tests as in Milestones 18/19 (FakeAdapter; a fake vmstore
server over a temporary socket for the inbox and greetings; generated
`voicemail.conf` with polling; facts `_keys` with user slots; template
resolution order; presence rules → engine state; fax job state machine
with a fake ARI). Live on dev1: the helper unit, inbox over a real
mailbox (leave a message from a phone), greeting upload and browser
recording, user keys on a Poly, presence on the directory, a fax to a
test number once a trunk exists.

## 13. Slices and order

A. Voicemail store helper + web inbox (§2) — B. Greetings (§3) —
C. Contacts and speed dials (§6), Companion migration — D. Call history
widget and own recordings (§5), self-service limits (§4) — E. Presence (§7)
— F. User keys with locked keys (§8) — G. Canvas and templates (§10),
My Phone as canvas — H. Fax (§9). Each slice lands as its own commit with
tests, docs "Built" notes and issue comments; 0.26.0 at the end (H may
follow as 0.26.x).

## 14. Known limitations (planned)

No WebRTC browser phone (P2), no call-me-to-play, no phone-side presence
menu, no user-group object (roles and departments instead), no missed-call
email yet (the `voicemail.message` webhook and the call-history widget
cover the need in part), Companion widgets only for the inbox counts.
