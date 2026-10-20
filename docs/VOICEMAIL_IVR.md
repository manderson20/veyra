# Voicemail, prompts and IVR menus

How Veyra gives extensions a voicemail box, delivers messages by email,
stores and records audio prompts, and routes callers through menus.
Delivered in Milestone 7; ring groups and queues (Milestone 8) become
further destinations without changing the model.

## 1. Objects

| Object | Scope | Purpose |
|---|---|---|
| **Email delivery** (`system_settings` key `notifications.smtp`) | Installation | The SMTP server Veyra sends through (voicemail-to-email now; password resets and alerts later) |
| **Voicemail box** (`voicemail_boxes`) | One per extension | PIN, delivery options, greeting recorded from the phone; the mailbox number is the extension number |
| **Prompt** (`prompts`) | Organization | An audio file (uploaded or recorded from a phone) played by IVR menus |
| **IVR menu** (`ivr_menus`, `ivr_entries`) | Organization | A prompt plus key mapping, timeout and invalid handling, optional direct extension dialling |
| **Destinations** | | Inbound routes, after-hours branches, IVR keys and IVR fallbacks all point at the same kinds of target: an extension, an extension's voicemail, another IVR menu, or (menus only) hang up |

Everything is stored in the database and reaches Asterisk through a
generated and deployed revision ([TELEPHONY_ENGINE.md](TELEPHONY_ENGINE.md)
§4). New in this milestone: a generated `voicemail.conf` (and the stub
that includes it), a prompt directory Asterisk can read and write, and a
mail queue between Asterisk and Veyra's SMTP sender.

## 2. Email delivery

Veyra has no mail transport of its own and the server has none installed,
so messages go out through an SMTP server the administrator configures:

| Setting | Notes |
|---|---|
| `host`, `port` | Required when enabled; port defaults to 587 |
| `security` | `starttls` (default), `tls` (implicit TLS, usually 465) or `none` (loopback relays only; refused for non-loopback hosts) |
| `username`, `password` | Optional; the password is encrypted at rest with the installation key (purpose `smtp.password`) and never returned (`has_password`) |
| `from_address`, `from_name` | The sender; default `veyra@<hostname>` and the installation name (`effective_*` in the API) |
| `enabled` | Delivery is off until the settings are saved with `enabled: true` |

`GET/PUT /system/smtp` (platform settings permission; omitting `password`
keeps it, an empty one removes it) and `POST /system/smtp/test` send a test
message to the caller's own address and return the result; both are
audited (`smtp.update`, `smtp.test`). Settings → Email delivery card, with
the queue counts. Saving a change to `enabled`, `from_address` or
`from_name` raises the Deploy changes flag because those reach
`voicemail.conf`.

**Sending** is done by the worker (`veyra worker`), never inside a request:
`core/mail.py` composes RFC 5322 messages (`email` package) and delivers
with `smtplib` (standard library). Queued messages are `.eml` files in
`/var/lib/veyra/mailqueue` (`2770 veyra:asterisk`), each with a `.json`
sidecar holding its attempts: every minute the worker sends what is due,
deletes a sent message, and otherwise retries with growing delays (1, 5,
15, 60 minutes) until 24 hours have passed, then moves it to
`mailqueue/failed` and audits `mail.failed`. The queue directory is also
where Asterisk hands over voicemail notifications (§3).

## 3. Voicemail

### 3.1 Boxes

| Field | Notes |
|---|---|
| `extension_id` | Unique: one box per extension; mailbox number = extension number, context `veyra`. **Null for a shared inbox** (Milestone 9c, [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §5): the box then has its own `number` (shared number space) and `name`, and `voicemail_box_members` lists the extensions whose message lamp follows it |
| PIN (`pin_ciphertext`) | 4–10 digits, encrypted (purpose `voicemail.pin:<box id>`); Asterisk needs it in clear in `voicemail.conf`, so that file is sensitive. Set at creation (random 6 digits unless given) and **returned once**; resettable (`reset-pin`, returned once); changeable by the user; never returned otherwise |
| `email` | Where messages are delivered; defaults to the extension user's email at creation; empty = no email |
| `attach_audio` | Attach the recording (default on) |
| `delete_after_email` | Remove the message from the box once emailed (default off); only with an email address and the recording attached. Deleted only after the SMTP server accepted the email (issue #148): Asterisk keeps it (`delete=no`), `emailbody` ends with `[veyra-vm:${VM_MESSAGEFILE}]`, `veyra-mailqueue` turns that into an `X-Veyra-Voicemail` header with the message's `msg_id`, and the worker strips both, sends, then deletes the message by `msg_id` (audited `voicemail.deleted_after_email`). A failed or given-up email keeps it |
| `keep_days` | Messages older than this many days are deleted from every folder, once a day by the worker (store verb `prune`; issue #142, 0.27.36); empty keeps them |
| `ring_seconds` | How long the phone rings before voicemail answers (default 20, 5–120) |
| `greeting` | Recorded by the owner from the phone (`*97`, mailbox options); Asterisk stores it in its spool; the API does not report whether one exists |
| `is_enabled` | A disabled box keeps its settings and messages but calls no longer land in it, and it leaves the engine configuration |

Callers reach a box when the extension does not answer within
`ring_seconds` (unavailable greeting; busy gets the busy greeting), when an
inbound route or IVR key points at *voicemail of extension N*, and when a
user dials `*97` (own box, PIN asked) or `*98` (any box, mailbox and PIN
asked). The API reports `email_delivery_enabled` (the installation switch
of §2) and `in_use_by` (routes and keys pointing at the box).

**Shared inboxes** (9c) belong to no phone. Callers reach one by dialling
its number (`exten => <number>` in `veyra-internal` goes straight to
`VoiceMail(<number>@veyra,u)`), from routes, menus and group failovers of
kind `voicemail_box`, and members open it with `*98` (its number and PIN).
Member phones get the inbox appended to their endpoint's `mailboxes=` so
their lamp lights for the shared inbox as well as their own box. A shared
inbox cannot take an extension's number and an extension cannot take an
inbox's (the numbering plan of [EXTENSIONS.md](EXTENSIONS.md) §2).

### 3.2 Generated configuration

`voicemail.conf` (**sensitive**), reloaded with `app_voicemail.so`:

```
[general]
format=wav49|gsm|wav        ; wav49 for email attachments
serveremail=<from_address>  fromstring=<from_name>
attach=yes  maxmsg=100  maxsecs=180  maxgreet=60
maxsilence=10  silencethreshold=128  maxlogins=3  pbxskip=yes
emailsubject=New voicemail ${VM_MSGNUM} in mailbox ${VM_MAILBOX} (${VM_NAME})
emailbody=...  (name, mailbox, caller, date, duration)
mailcmd=/opt/veyra/current/installer/bin/veyra-mailqueue
[zonemessages]
<org slug>=<org timezone>|'vm-received' Q 'digits/at' IMp
[veyra]
<number> => <pin>,<display name>,<email or empty>,,attach=yes|delete=no|tz=<org slug>|saycid=yes|envelope=yes
```

`mailcmd` makes Asterisk hand each composed notification (headers, body,
attachment) to a tiny POSIX shell script instead of a local sendmail; the
script writes it into the mail queue (§2) and the worker sends it through
the SMTP settings. Asterisk therefore needs no mail transport and the
message content never passes through the API process. While email
delivery is **disabled**, addresses are left out of `voicemail.conf` and
`delete=no` is forced, so messages are never deleted after an email that
could not be sent.

Phone endpoints and AORs get `mailboxes=<number>@veyra` (and the endpoint
`mwi_subscribe_replaces_unsolicited=yes`), so message waiting indication
(MWI) lights the phone's lamp and clears when messages are heard. The
dialplan for an extension with a box becomes:

```
exten => N,1,NoOp(Veyra extension N)
 same => n,Dial(PJSIP/<endpoint>,<ring_seconds>)
 same => n,GotoIf($["${DIALSTATUS}"="BUSY"]?busy)
 same => n,VoiceMail(N@veyra,u)
 same => n,Hangup()
 same => n(busy),VoiceMail(N@veyra,b)
 same => n,Hangup()
```

`*97` → `VoiceMailMain(${CALLERID(num)}@veyra)`, `*98` →
`VoiceMailMain(@veyra)` in `veyra-features`. The default `voicemail.conf`
of the Asterisk package (sample mailboxes in `[default]`) is replaced by the
stub, so no sample boxes exist.

### 3.3 Permissions and API

| Permission | Default roles |
|---|---|
| `voicemail.read` | Organization and site administrators, technicians, read-only users |
| `voicemail.write` | Organization and site administrators |

```
GET    /voicemail?organization_id=&extension_id=&shared=&q=   boxes with extension, user, members and in_use_by
POST   /voicemail                            {extension_id, pin?, email?, attach_audio?, delete_after_email?, ring_seconds?, is_enabled?} → 201 with pin (once)
POST   /voicemail                            shared inbox: {organization_id, number, name, members?: [extension ids], pin?, email?, …} → 201 with pin (once)
GET    /voicemail/{id}
PATCH  /voicemail/{id}                       pin: a new PIN; omitted = unchanged; shared inboxes also number, name, members
DELETE /voicemail/{id}                       409 voicemail_in_use when a route or IVR points at it
POST   /voicemail/{id}/reset-pin             new random PIN, returned once (audited)
GET    /me/voicemail                         the caller's own boxes (number, email, ring_seconds)
POST   /me/voicemail/{id}/pin                {pin} change your own PIN (me scope; 204)
```

Audit: `voicemail.create/update/delete/pin_reset`, `voicemail.pin_change`
(own). PINs are never written to the audit log (keys containing `pin` are
redacted by the sanitizer, so details use `generated` and `code_changed`).
Every write raises the Deploy changes flag. Telephony → Voicemail lists the
boxes (row click edits, with PIN reset and delete); the extension page gets
a Voicemail card; the account page lists the user's own boxes with a PIN
change.

## 4. Prompts

Audio that menus play. Stored under `/var/lib/veyra/prompts/<org slug>/`
as 8 kHz 16-bit mono WAV (`<slug>.wav`), the format Asterisk plays without
transcoding; `prompts/` is `2770 veyra:asterisk` so the API writes uploads
and Asterisk writes recordings.

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Slug derived from the name (numbered when taken), unique per organization, used as the file name and stable afterwards |
| `description` | |
| `source` | `upload` or `recording` |
| `duration_seconds`, `size_bytes`, `file_present` | From the stored file |

* **Upload** (`POST /prompts`, multipart `organization_id`, `name`,
  `description?`, `file`; `ivr.write`): WAV only (PCM 8 or 16 bit, mono or
  stereo, any sample rate from 8 to 48 kHz, at most 10 MB and 5 minutes).
  Veyra converts to 8 kHz 16-bit mono itself (stereo mixed down,
  linear-interpolation resampling, `telephony/audio.py`) so no external tool
  is needed; anything else answers `422 unsupported_audio` naming the
  accepted format.
* **Recording from a phone**: dial `*95`; after the tone speak, `#` stops
  (or 5 seconds of silence, 5 minutes at most); the recording is played
  back and `vm-review` asks: `1` keep, `2` listen again, `3` re-record.
  Asterisk writes `prompts/<org>/incoming/rec-<extension>-<epoch>.wav`
  (the organization comes from the endpoint's `VEYRA_ORG`); the Prompts
  page lists these under *Recordings from phones* where they are played,
  named (adopted: converted and moved into place as a prompt with
  `source=recording`) or discarded. The worker creates every active
  organization's `incoming` folder each minute (and the recordings listing
  does the same; `0770`, group inherited from the setgid `prompts/`), so
  recording works before the first upload.
* **Listen** in the browser: `GET /prompts/{id}/audio` streams the WAV;
  `GET /prompts/recordings/{file}/audio?organization_id=` for recordings.
* **Replace**: `PUT /prompts/{id}/audio` (multipart `file`) uploads a new
  recording for an existing prompt (menus keep pointing at it).
* **Delete** answers `409 prompt_in_use` while a menu uses it.

Files are written atomically; the deployer never touches them. A deleted
organization's slug directory is left in place (the data may be wanted).

## 5. IVR menus

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Context `veyra-ivr-<slug>`; name unique per organization, slug unique per installation and stable |
| `description` | |
| `prompt_id` | The menu prompt; a menu without one is rendered as congestion and listed in `problems` |
| `invalid_prompt_id` | Optional; default Asterisk `pbx-invalid` |
| `timeout_seconds` | Wait for a key after the prompt (default 5, 1–30) |
| `max_retries` | Invalid or timed-out attempts before the fallback destination (default 3, 1–9) |
| `allow_direct_dial` | Callers may dial an extension number of the organization during the menu |
| `timeout_destination`, `invalid_destination` | A destination (§6) or hang up (default) after `max_retries` |
| `entries` | Up to 12: digit `0`–`9`, `*`, `#` → destination (table `ivr_entries`) |
| `is_enabled` | A disabled menu leaves the engine and is no longer a valid destination; routes pointing at it are flagged |

Dialplan (`[veyra-ivr-<slug>]`):

```
exten => s,1,NoOp(Veyra IVR <name>)
 same => n,Set(__VEYRA_IVR_DEPTH=$[0${VEYRA_IVR_DEPTH} + 1])
 same => n,GotoIf($[${VEYRA_IVR_DEPTH} > 8]?toodeep)
 same => n,Answer()
 same => n,Set(VEYRA_IVR_TRIES=0)
 same => n(menu),Background(/var/lib/veyra/prompts/<org>/<slug>)
 same => n,WaitExten(<timeout>)
 same => n,Goto(t,1)                        ; WaitExten only goes to t by itself when nothing follows it
 same => n(toodeep),Playback(pbx-invalid)  ; menus pointing at each other in a loop
 same => n,Hangup()
exten => 1,1,<destination lines>
exten => 2214,1,Goto(veyra-internal,2214,1)   ; one line per extension of the organization (direct dialling)
exten => i,1,Set(VEYRA_IVR_TRIES=$[${VEYRA_IVR_TRIES} + 1])
 same => n,GotoIf($[${VEYRA_IVR_TRIES} >= <max_retries>]?giveup)
 same => n,Playback(<invalid prompt or pbx-invalid>)
 same => n,Goto(s,menu)
 same => n(giveup),<invalid destination lines or Playback(vm-goodbye) + Hangup>
exten => t,1,...                               ; same shape without the prompt: the menu is simply replayed
```

Direct dialling renders the organization's extension numbers explicitly
(not a pattern), so callers can never reach outbound routes or feature codes
from a menu; a mapped key wins over an extension starting with the same
digit, and Asterisk waits for the inter-digit timeout before taking a single
digit, which is the usual behaviour of auto attendants.

Permissions: `ivr.read` (administrators, technicians, read-only) and
`ivr.write` (organization and site administrators) cover menus and prompts.

```
GET/POST /ivr            GET/PATCH/DELETE /ivr/{id}        409 ivr_in_use when a route or another menu points at it
GET/POST /prompts        GET/PATCH/DELETE /prompts/{id}    GET /prompts/{id}/audio   PUT /prompts/{id}/audio
GET      /prompts/recordings?organization_id=
GET      /prompts/recordings/{file}/audio?organization_id=
POST     /prompts/recordings/{file}/adopt   {organization_id, name, description?}
DELETE   /prompts/recordings/{file}?organization_id=
```

Menus return `problems` (no prompt, missing targets, no keys and no direct
dialling), `in_use_by`, and labelled destinations. Audit:
`ivr.create/update/delete`, `prompt.create/update/replace_audio/delete`,
`prompt.recording_delete`. Telephony → IVR Menus (list, create, and a page
with the key-map editor and fallbacks) and Telephony → Prompts (uploads,
recordings from phones, playback).

## 6. Destinations

Inbound routes gain `destination_type` ∈ `extension | voicemail |
voicemail_box | ivr | ring_group | queue` with `destination_extension_id`
(extension and voicemail), `destination_voicemail_box_id` (a shared inbox,
9c), `destination_ivr_id`, `destination_ring_group_id` or
`destination_queue_id`; the after-hours branch gets the same fields
(`after_hours_type`, `after_hours_extension_id`, …). IVR entries and
fallbacks use the same shape (`{type, extension_id, voicemail_box_id,
ivr_id, ring_group_id, queue_id}`) plus `hangup`. The API returns every
destination as `{type, extension_id, ivr_id, ring_group_id, queue_id,
voicemail_box_id, label, missing}` (`api/v1/destinations.py`). Rendering:

| Type | Dialplan |
|---|---|
| extension | `Goto(veyra-internal,<number>,1)` |
| voicemail | `VoiceMail(<number>@veyra,u)` then `Hangup()`; requires an enabled box |
| voicemail_box | the same with the shared inbox's number; requires an enabled inbox |
| ivr | `Goto(veyra-ivr-<slug>,s,1)`; requires an enabled menu |
| hangup | `Playback(vm-goodbye)`, `Hangup()` |
| announcement | `Goto(veyra-ann-<slug>,s,1)`; requires an enabled announcement (Milestone 19, [CALL_FEATURES.md](CALL_FEATURES.md) §4.1) |
| conference | `Goto(veyra-conf-<slug>,s,1)`; requires an enabled conference room (§4.3) |
| directory | `Goto(veyra-directory,s,1)`: the organization's dial-by-name directory (§4.2) |
| call_flow | `Goto(veyra-flow-<slug>,s,1)`; the flow then takes its normal or override destination (§4.5) |
| missing | `Congestion(5)`, `Hangup()` |

The API validates that the target exists in the same organization and is
usable (an enabled box, an enabled menu); the snapshot marks a target that
is gone, disabled or not deployable as `missing` and the generator renders
congestion while the interface flags it, as for extensions today. Deleting
an extension cascades to its box and leaves routes flagged rather than
broken; deleting a box or a menu that something points at is refused.

## 7. Installer and permissions on disk

* Stub `/etc/asterisk/voicemail.conf` (`#tryinclude veyra/voicemail.conf`),
  installed like the other stubs with the package sample backed up;
  `verify.sh` checks it.
* `/var/lib/veyra` becomes `0750 veyra:asterisk` (Asterisk may traverse
  it); `prompts/`, `mailqueue/` and `mailqueue/failed` are `2770
  veyra:asterisk`, created by `do_telephony` on install and upgrade;
  `verify.sh` checks them. The `veyra-api` and `veyra-worker` units already
  allow writing under the data directory.
* The service account is a member of group `asterisk` (`usermod -aG`, done
  by `do_telephony`; `verify.sh` checks it): the files Asterisk creates in
  those folders (queued notifications, `*95` recordings) belong to group
  `asterisk`, and without the membership the worker cannot read them
  (found on dev1: "Mail queue: cannot read ...: Permission denied").
* `installer/bin/veyra-mailqueue` (the `mailcmd` target) ships in the
  release, root-owned and executable; it writes `<timestamp>-<pid>-<random>.eml`
  with mode `0660` so the worker can read and remove it.
* `*95` recordings and `*97`/`*98` need no new packages; the sounds used
  (`vm-*`, `pbx-invalid`, `beep`) are in `asterisk-core-sounds-en`;
  `app_voicemail`, `app_record`, `app_read` and `res_pjsip_mwi` are core
  modules loaded by default.
* The installer now manages `/etc/asterisk/modules.conf` (the package list
  plus `noload` for `app_voicemail_odbc.so`, `app_voicemail_imap.so`,
  `cdr_radius.so`, `cel_radius.so`): Ubuntu ships all voicemail backends and
  the ODBC one, failing to load beside `app_voicemail.so`, unregisters the
  `VoiceMail` applications on its way out (seen on dev1: `No application
  'VoiceMail'` with the module "Running"). A changed `modules.conf` makes the
  installer restart Asterisk once; `verify.sh` checks that the application is
  registered.
* New Python dependency: `python-multipart` (file uploads; pure Python).

## 8. Known limitations

* Voicemail messages are visible in the web interface since 0.26.0
  (My Phone and the administrator's Voicemail page, through the store
  helper that runs as the asterisk user; [USER_PORTAL.md](USER_PORTAL.md)
  §2). "Call me to play" and voicemail reports are not built.
* The greetings live in Asterisk's spool; the phone menu (`*97`) records
  them, and since 0.26.0 the web interface lists, plays, uploads, records
  (browser microphone) and removes them (USER_PORTAL.md §3).
* Prompt conversion is basic (linear interpolation); studio-quality prompts
  should be exported at 8 kHz mono from an audio tool.
* Email delivery depends on the configured SMTP server; failures are
  audited and the test button is the diagnostic. Messages wait in the queue
  while delivery is misconfigured and are given up after a day.
* A recording abandoned on the phone (hang-up before `1`) stays in the
  incoming folder until it is discarded on the Prompts page.
* One voicemail context per organization since Milestone 14: `veyra` for
  the original organization, `veyra_<namespace>` for the others
  ([MULTI_TENANCY.md](MULTI_TENANCY.md) §2).
