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
| **Destinations** | | Inbound routes, after-hours branches, IVR keys and IVR fallbacks all point at the same kinds of target: an extension, an extension's voicemail, another IVR menu, or hang up |

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
| `host`, `port` | Required; port defaults to 587 |
| `security` | `starttls` (default), `tls` (implicit TLS, usually 465) or `none` (loopback relays only; refused for non-loopback hosts) |
| `username`, `password` | Optional; the password is encrypted at rest with the installation key (purpose `smtp.password`) and never returned |
| `from_address`, `from_name` | The sender; defaults to `veyra@<hostname>` and the installation name |
| `enabled` | Delivery is off until the settings are saved with `enabled: true` |

`GET/PUT /system/smtp` (platform administrators) and
`POST /system/smtp/test` send a test message to the caller's address and
return the result. Settings → Email delivery card.

**Sending** is done by the worker (`veyra worker`), never inside a request:
`core/mail.py` composes RFC 5322 messages (`email` package) and delivers
with `smtplib` (standard library). Queued messages live as files in
`/var/lib/veyra/mailqueue` (`2770 veyra:asterisk`): the worker takes each
file, sends it, deletes it on success, and otherwise retries with growing
delays (1, 5, 15, 60 minutes) up to 24 hours, then moves it to
`mailqueue/failed` and audits `mail.failed`. The queue directory is also
where Asterisk hands over voicemail notifications (§3).

## 3. Voicemail

### 3.1 Boxes

| Field | Notes |
|---|---|
| `extension_id` | Unique: one box per extension; mailbox number = extension number, context `veyra` |
| `pin_ciphertext` | 4–10 digits, encrypted (purpose `voicemail.pin:<box id>`); Asterisk needs it in clear in `voicemail.conf`, so that file is sensitive. Set at creation (random 6 digits unless given) and resettable; never returned |
| `email` | Where messages are delivered; defaults to the extension user's email; empty = no email |
| `attach_audio` | Attach the recording (default on) |
| `delete_after_email` | Remove the message from the box once emailed (default off); only with an email address |
| `ring_seconds` | How long the phone rings before voicemail answers (default 20, 5–120) |
| `greeting` | Recorded by the owner from the phone (`*97`, mailbox options); Asterisk stores it in its spool; the API reports whether one exists is **not** attempted (the spool is Asterisk's) |
| `is_enabled` | A disabled box keeps its settings and messages but calls no longer land in it |

Callers reach a box when the extension does not answer within
`ring_seconds` (busy and unavailable included), when an inbound route or
IVR key points at *voicemail of extension N*, and when a user dials `*97`
(own box, PIN asked) or `*98` (any box, mailbox and PIN asked).

### 3.2 Generated configuration

`voicemail.conf` (**sensitive**), reloaded with `app_voicemail.so`:

```
[general]
format=wav49|gsm|wav        ; wav49 for email attachments
serveremail=<from_address>  fromstring=<from_name>
attach=yes  maxmsg=100  maxsecs=180  minsecs=2  maxgreet=60
maxsilence=10  silencethreshold=128  maxlogins=3
emailsubject=[Veyra] New voicemail ${VM_MSGNUM} in mailbox ${VM_MAILBOX}
emailbody=...  (caller, date, duration, mailbox)
mailcmd=/opt/veyra/current/installer/bin/veyra-mailqueue
[zonemessages]
<org slug>=<org timezone>|'vm-received' Q 'digits/at' IMp
[veyra]
<number> => <pin>,<display name>,<email or empty>,,attach=yes|delete=no|tz=<org slug>|saycid=yes|envelope=yes
```

`mailcmd` makes Asterisk hand each composed notification (headers, body,
attachment) to a tiny script instead of a local sendmail; the script writes
it into the mail queue, which the worker sends through the SMTP settings.
Asterisk therefore needs no mail transport and the message content never
passes through the API process.

Phone endpoints and AORs get `mailboxes=<number>@veyra`, so message waiting
indication (MWI) lights the phone's lamp and clears when messages are
heard. The dialplan for an extension with a box becomes:

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
`VoiceMailMain(@veyra)` in `veyra-features`.

### 3.3 Permissions and API

| Permission | Default roles |
|---|---|
| `voicemail.read` | Organization and site administrators, technicians, read-only users |
| `voicemail.write` | Organization and site administrators |

```
GET    /voicemail?organization_id=&q=        boxes with extension and user
POST   /voicemail                            {extension_id, pin?, email?, attach_audio?, delete_after_email?, ring_seconds?, is_enabled?}
GET    /voicemail/{id}
PATCH  /voicemail/{id}                       pin: a new PIN; omitted = unchanged
DELETE /voicemail/{id}                       409 voicemail_in_use when a route or IVR points at it
POST   /voicemail/{id}/reset-pin             new random PIN, returned once (audited)
GET    /me/voicemail                         the caller's own boxes (number, email, has_email, ring_seconds)
POST   /me/voicemail/{id}/pin                {pin} change your own PIN (me scope)
```

Audit: `voicemail.create/update/delete/pin_reset`, `voicemail.pin_change`
(own). PINs are never written to the audit log (`pin` keys are redacted).
Every write raises the Deploy changes flag. Telephony → Voicemail lists the
boxes; the extension page gets a Voicemail card for the box of that
extension.

## 4. Prompts

Audio that menus play. Stored under `/var/lib/veyra/prompts/<org slug>/`
as 8 kHz 16-bit mono WAV (`<slug>.wav`), the format Asterisk plays without
transcoding; the directory is `2770 veyra:asterisk` so the API writes
uploads and Asterisk writes recordings.

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Slug derived from the name, unique per organization, used as the file name |
| `description` | |
| `source` | `upload` or `recording` |
| `duration_seconds`, `size_bytes` | From the stored file |

* **Upload** (`POST /prompts`, multipart, `ivr.write`): WAV only (PCM 8 or
  16 bit, mono or stereo, any sample rate up to 48 kHz, at most 10 MB and
  5 minutes). Veyra converts to 8 kHz 16-bit mono itself (stereo mixed
  down, linear-interpolation resampling) so no external tool is needed;
  anything else answers `422 unsupported_audio` with the accepted format.
* **Recording from a phone**: dial `*95`, record after the tone, `#` to
  stop, listen, `1` to keep. Asterisk writes
  `prompts/<org>/incoming/rec-<extension>-<timestamp>.wav`; the Prompts
  page lists these under *Recordings from phones* where they are named and
  adopted (moved into place as a prompt) or deleted.
* **Listen** in the browser: `GET /prompts/{id}/audio` streams the WAV.
* **Replace**: `PUT /prompts/{id}/audio` uploads a new recording for an
  existing prompt (menus keep pointing at it).
* **Delete** answers `409 prompt_in_use` while a menu uses it.

Files are written atomically; the deployer never touches them. A deleted
organization slug directory is left in place (the data may be wanted).

## 5. IVR menus

| Field | Notes |
|---|---|
| `organization_id`, `name`, `slug` | Context `veyra-ivr-<slug>`; slug unique per installation |
| `description` | |
| `prompt_id` | The menu prompt (required to be deployable; a menu without one plays `vm-goodbye`… no: it answers with congestion and the interface flags it) |
| `invalid_prompt_id` | Optional; default Asterisk `pbx-invalid` |
| `timeout_seconds` | Wait for a key after the prompt (default 5, 1–30) |
| `max_retries` | Invalid or timed-out attempts before the fallback destination (default 3, 1–9) |
| `allow_direct_dial` | Callers may dial an extension number during the menu |
| `timeout_destination`, `invalid_destination` | A destination (§6) or hang up; default hang up after `max_retries` |
| `entries` | Up to 12: digit `0`–`9`, `*`, `#` → destination |
| `is_enabled` | |

Dialplan (`[veyra-ivr-<slug>]`):

```
exten => s,1,NoOp(Veyra IVR <name>)
 same => n,Set(__VEYRA_IVR_DEPTH=$[0${VEYRA_IVR_DEPTH} + 1])
 same => n,GotoIf($[${VEYRA_IVR_DEPTH} > 8]?toodeep)
 same => n,Answer()
 same => n,Set(VEYRA_IVR_TRIES=0)
 same => n(menu),Background(/var/lib/veyra/prompts/<org>/<slug>)
 same => n,WaitExten(<timeout>)
 same => n(toodeep),Playback(pbx-invalid)  ; menus pointing at each other in a loop
 same => n,Hangup()
exten => 1,1,<destination lines>
exten => _XXXX,1,Goto(veyra-internal,${EXTEN},1)      ; with allow_direct_dial, X repeated extension_length times
exten => i,1,Set(VEYRA_IVR_TRIES=$[${VEYRA_IVR_TRIES} + 1])
 same => n,GotoIf($[${VEYRA_IVR_TRIES} >= <max_retries>]?giveup)
 same => n,Playback(<invalid prompt or pbx-invalid>)
 same => n,Goto(s,menu)
 same => n(giveup),<invalid destination lines or Playback(vm-goodbye) + Hangup>
exten => t,1,...                                         ; same shape for timeouts
```

A one-digit entry and direct dialling can be ambiguous (`2` versus
extension `2214`); Asterisk waits for the inter-digit timeout before taking
the single digit, which is the usual behaviour of auto attendants.

Permissions: `ivr.read` (administrators, technicians, read-only) and
`ivr.write` (organization and site administrators) cover menus and prompts.

```
GET/POST /ivr            GET/PATCH/DELETE /ivr/{id}        409 ivr_in_use when referenced
GET/POST /prompts        GET/PATCH/DELETE /prompts/{id}    GET /prompts/{id}/audio   PUT /prompts/{id}/audio
GET      /prompts/recordings            POST /prompts/recordings/{file}/adopt {name}   DELETE /prompts/recordings/{file}
```

Telephony → IVR (menus, with a key-map editor) and Telephony → Prompts
(uploads, recordings from phones, playback).

## 6. Destinations

Inbound routes gain `destination_type` ∈ `extension | voicemail | ivr` with
`destination_extension_id` (extension and voicemail) or
`destination_ivr_id`; the after-hours branch gets the same three fields
(`after_hours_type`, `after_hours_extension_id`, `after_hours_ivr_id`). IVR
entries and fallbacks use the same shape plus `hangup`. Rendering:

| Type | Dialplan |
|---|---|
| extension | `Goto(veyra-internal,<number>,1)` |
| voicemail | `VoiceMail(<number>@veyra,u)` then `Hangup()`; requires an enabled box |
| ivr | `Goto(veyra-ivr-<slug>,s,1)` |
| hangup | `Playback(vm-goodbye)`, `Hangup()` |

The API validates that the target exists in the same organization and is
usable (an enabled box, an enabled menu); the generator renders a missing
target as congestion and the interface flags it, as for extensions today.
Deleting an extension still leaves routes flagged rather than broken;
deleting a box or a menu that something points at is refused.

## 7. Installer and permissions on disk

* Stub `/etc/asterisk/voicemail.conf` (`#tryinclude veyra/voicemail.conf`),
  installed like the other stubs with the package sample backed up;
  `verify.sh` checks it.
* `/var/lib/veyra` becomes `0750 veyra:asterisk` (Asterisk may traverse
  it); `prompts/` and `mailqueue/` are `2770 veyra:asterisk`, created by
  `do_telephony` on install and upgrade.
* `installer/bin/veyra-mailqueue` (the `mailcmd` target) is shipped in the
  release and executable by Asterisk.
* `*95` recordings and `*97`/`*98` need no new packages; the prompt sounds
  used (`vm-*`, `pbx-invalid`, `beep`, `auth-thankyou`) are in
  `asterisk-core-sounds-en`.
* New Python dependency: `python-multipart` (file uploads; pure Python).

## 8. Known limitations

* Voicemail messages are not visible in the web interface (no inbox);
  users listen by phone or email. Visual voicemail is a later milestone.
* The greeting lives in Asterisk's spool and is managed from the phone.
* Prompt conversion is basic (linear interpolation); studio-quality prompts
  should be exported at 8 kHz mono from an audio tool.
* Email delivery depends on the configured SMTP server; failures are
  audited and the test button is the diagnostic.
