# Milestone 7: Completion Report

**Milestone:** 7 — Voicemail and IVR (voicemail boxes with PIN and voicemail-to-email, message waiting indication, prompts uploaded or recorded from a phone, IVR menus, email delivery settings)
**Date:** 2026-10-13
**Branch:** `milestone-7` (pushed to `manderson20/veyra`)
**Version:** 0.9.0 (0.9.0-dev until approval)
**Status:** Software complete; backend, installer, interface, tests and documentation done (§3). **Awaiting the owner's approval and the upgrade of veyra-dev1** (§4, §6).

## 1. Scope (approved 2026-10-13)

Per the Milestone 6b report §7: voicemail boxes per extension with PIN,
greeting and voicemail-to-email, message waiting indication, voicemail as
an inbound and after-hours destination; IVR menus with recorded prompts,
key mapping to extensions, other IVRs and voicemail, timeout and invalid
handling, direct extension dialling; prompt recording from a phone and
upload from the browser; generated dialplan contexts and `voicemail.conf`.
Design and reference: [VOICEMAIL_IVR.md](../VOICEMAIL_IVR.md).

## 2. Results

| Task | Result | Where |
|---|---|---|
| Voicemail boxes | Done. `voicemail_boxes`, one per extension; PIN encrypted with the installation key (purpose `voicemail.pin:<id>`), returned once on creation and on reset, never otherwise; email (defaults to the extension user's), attach, delete-after-email, ring time 5–120 s, enabled flag. `GET/POST /voicemail`, `GET/PATCH/DELETE /voicemail/{id}` (`409 voicemail_in_use`), `POST /voicemail/{id}/reset-pin`; `GET /me/voicemail`, `POST /me/voicemail/{id}/pin` for users. Telephony → Voicemail (list, create and edit dialog with reset and delete), Voicemail card on the extension page, Voicemail card with PIN change on the account page. | `backend/veyra/api/v1/voicemail.py`, `me.py`, `core/models/voicemail.py`, `frontend/src/app/(app)/voicemail/`, `components/voicemail/`, `components/extensions/VoicemailCard.tsx`, `components/account/MyVoicemailCard.tsx` |
| Generated voicemail configuration and MWI | Done. New managed file `voicemail.conf` (sensitive): `[general]` with formats, limits, sender and `mailcmd`, `[zonemessages]` per organization time zone, `[veyra]` mailbox lines; email addresses only while delivery is enabled. Endpoints and AORs of extensions with a box get `mailboxes=<n>@veyra` (`mwi_subscribe_replaces_unsolicited=yes`). Extension dialplan rings `ring_seconds` then `VoiceMail(u)`/`VoiceMail(b)`; `*97` own box, `*98` any box. Reload scope `app_voicemail.so`; the installer's `voicemail.conf` stub includes the file. | `telephony/asterisk/generator.py` (`_voicemail`, `_endpoints`, `_dialplan`), `installer/templates/asterisk/voicemail.conf` |
| Email delivery | Done. `notifications.smtp` settings (host, port, STARTTLS/TLS/none-loopback, user, password encrypted and write-only, sender); `GET/PUT /system/smtp`, `POST /system/smtp/test` (sends to the caller); Settings → Email delivery card with problems and queue counts. Asterisk pipes each notification into `installer/bin/veyra-mailqueue`, which files it under `/var/lib/veyra/mailqueue`; the worker sends through `smtplib` with retries 1/5/15/60 min and gives up after 24 h into `mailqueue/failed` with a `mail.failed` audit event. No mail transport on the server. | `core/mail.py`, `api/v1/smtp.py`, `cli/main.py` (`process_mail_queue`), `installer/bin/veyra-mailqueue`, `frontend/src/components/account/EmailDeliveryCard.tsx` |
| Prompts | Done. `prompts` per organization; multipart WAV upload converted to 8 kHz 16-bit mono in pure Python (PCM 8/16 bit, mono/stereo, up to 48 kHz, 10 MB, 5 min; `422 unsupported_audio` otherwise); playback (`GET /prompts/{id}/audio`), replace (`PUT .../audio`), rename, delete (`409 prompt_in_use`). Recordings from phones: `*95` records into `prompts/<org>/incoming/rec-<ext>-<epoch>.wav` with review (`1` keep, `2` listen, `3` re-record); listed, played, adopted or discarded under `/prompts/recordings`. The worker and the listing create the folders. Telephony → Prompts. | `telephony/audio.py`, `api/v1/prompts.py`, `generator.py` (`*95`), `frontend/src/app/(app)/prompts/` |
| IVR menus | Done. `ivr_menus` and `ivr_entries`: prompt, invalid prompt, timeout 1–30 s, retries 1–9, direct dialling, typed fallbacks for timeouts and invalid keys, up to 12 keys to extensions, voicemail boxes, other menus or hang-up; `problems` and `in_use_by` in the API; `409 ivr_in_use`. Dialplan: one `veyra-ivr-<slug>` context per enabled menu with a depth guard of 8, `Background` + `WaitExten`, explicit direct-dial extensions (callers cannot reach outbound routes), `i`/`t` handlers with retries. Telephony → IVR Menus (list, create) and a menu page with the key-map editor and an "as deployed" summary. | `api/v1/ivr.py`, `generator.py` (`_ivr_contexts`), `frontend/src/app/(app)/ivr/`, `components/ivr/IvrMenuFields.tsx` |
| Destinations | Done. Shared `DestinationIn/Out` (`api/v1/destinations.py`) with labels and a `missing` flag; inbound routes take `destination_type`/`destination_extension_id`/`destination_ivr_id` and the same for `after_hours_*`; the snapshot carries typed destinations (`missing` when the target is gone, disabled or not deployable) and the generator renders `Goto`, `VoiceMail`, `Goto(veyra-ivr-…)`, `vm-goodbye` or congestion. Interface: one destination picker (kind + target) used by inbound routes and IVR menus. | `api/v1/destinations.py`, `routing.py`, `telephony/snapshot.py`, `frontend/src/components/routing/DestinationPicker.tsx` |
| Installer | Done. `voicemail.conf` stub; `/var/lib/veyra` `0750 veyra:asterisk`, `prompts/`, `mailqueue/`, `mailqueue/failed` `2770 veyra:asterisk` on install and upgrade; `veyra-mailqueue` shipped executable; `verify.sh` checks stub, directories and the script; `installer/tests/test_lib.sh` covers the script. Dry run on dev1 shows the new steps. | `installer/lib/steps.sh`, `installer/verify.sh`, `installer/bin/`, `installer/tests/` |
| Permissions and audit | `voicemail.read` (administrators, technicians, read-only), `voicemail.write`, `ivr.read`, `ivr.write` (organization and site administrators); audit `voicemail.*`, `prompt.*`, `ivr.*`, `smtp.update`, `smtp.test`, `mail.failed`; the sanitizer also redacts keys containing `pin`; every engine-relevant write raises the Deploy changes flag. | `core/security/permissions.py`, `core/audit.py` |
| Database | Migration `0008`: four tables, three columns on `inbound_routes`; `alembic check` clean after fixing two constraint names. | `migrations/versions/0008_voicemail_ivr.py`, `docs/DATABASE_SCHEMA.md` |
| Documentation | `VOICEMAIL_IVR.md` (design and reference), API, schema, engine, extensions, installation, development and architecture docs, changelog, roadmap. | `docs/` |

## 3. Testing (veyra-dev1, 2026-10-13, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (105 files) |
| Backend pytest against PostgreSQL 18.6 | **267 passed** (30 new: voicemail.conf rendering, sensitivity and validation; email left out while delivery is off; MWI and the voicemail dialplan; feature codes; boxes of unknown extensions skipped; IVR contexts with keys, direct dialling, fallbacks, custom invalid prompt, no-prompt congestion and value validation; typed inbound destinations incl. the Milestone 6 form; WAV conversion for five input formats, refusals, duration, atomic write, prompt folders; SMTP settings, sending through a fake `smtplib` with STARTTLS/TLS/login/errors, queue send/retry/give-up; voicemail API CRUD, one-time PIN and redacted audit, own boxes and PIN change incl. a standard user, in-use rule and organization scoping, SMTP settings API and test message, deployment writing `voicemail.conf`, MWI and the dialplan with the PIN absent from readable artifacts and a disabled box leaving the engine; prompt upload/conversion/playback/replace/delete, recordings listed/adopted/discarded with path checks; IVR CRUD, validation, in-use rules, patching keys, disabled menus; inbound routes to menus with time conditions and their deployment) |
| `alembic check` | No drift (migration `0008`) |
| Installer `tests/test_lib.sh` | **38 passed** (7 new for `veyra-mailqueue`); `shellcheck` clean; `sudo installer/upgrade.sh --dry-run --yes` shows the stub, directory and script steps |
| Frontend lint / typecheck / vitest | Clean / clean / **30 passed** (2 new: destination normalisation, prompt lengths) |
| Frontend `npm run build` | Passed; `/voicemail`, `/ivr`, `/ivr/view` and `/prompts` exported |
| **Owner's `upgrade.sh` on dev1** | Done 2026-10-13 16:56 UTC from `~/veyra` on `milestone-7` (9711cf2), again 17:47 UTC at 4f9132c (`verify.sh` clean), and 18:13 UTC to release **0.9.0** from `~/veyra-release` (`verify.sh` clean, 38 checks incl. `service-groups`) |

### Live checks on dev1 (2026-10-13 17:50–18:05 UTC, release 4f9132c)

Driven from the server: calls originated on Local channels from the Asterisk
CLI, DTMF sent through ARI, a loopback SMTP sink on 127.0.0.1:2525 as the
mail server. Test objects from the previous session: extension 22215 "M7
test phone" with a box, prompt `m7-test-tone`, menu "M7 test menu" (1 →
22214, 2 → voicemail 22215).

| Check | Result |
|---|---|
| First upgrade: VoiceMail application | **Failed, fixed**: Ubuntu's `app_voicemail_odbc.so` fails to load beside `app_voicemail.so` and unregisters the applications → installer-managed `modules.conf` (6801d7e), `verify.sh` check (4f9132c) |
| Deposit a message (call to 22215, unanswered → box) | **OK**: three messages of 16 s in `INBOX`, `voicemail show users` counts them; a caller without audio leaves nothing (correct) |
| Voicemail-to-email hand-over (`mailcmd` → `veyra-mailqueue` → queue → worker → SMTP) | **Failed, fixed**: the queued `.eml` is group `asterisk` and the worker could not read it ("Permission denied") → the service account joins group `asterisk` (this commit); after the change the worker sent the message with the WAV attached to the sink within a minute |
| Email left out of `voicemail.conf` while delivery is off | OK (revision 14: "no change"; revision 15 with delivery on: `voicemail.conf` changed) |
| `*95` recording as 22215 (`#` to stop, `1` to keep) | OK: `Record` → `Playback` → `Read` → `vm-msgsaved`; `rec-22215-<epoch>.wav` appears in `prompts/<org>/incoming/` (group `asterisk`, readable by the worker after the fix) |
| IVR key `2` → voicemail of 22215 | OK |
| IVR key `1` → extension 22214 (`Goto(veyra-internal,22214,1)` → `Dial`) | OK |
| IVR no key → `t` handler | **Failed, fixed**: `WaitExten` continues with the next priority when one exists and only goes to `t` otherwise, so timeouts fell into the loop-guard branch (`pbx-invalid`, hang-up) → explicit `Goto(t,1)` after `WaitExten` (d16730f); re-tested on 0.9.0 at 18:14 UTC: timeout → `t` → replay → second timeout → `vm-goodbye` |
| `*97` with PIN, MWI lamp, prompt adoption in the browser, menu behind an inbound route | *Owner, with a handset and the web pages* (PINs are not readable from the session; no trunk on dev1) |

## 4. Not verified

* With a handset: `*97`/`*98` with the PIN, the message-waiting lamp, the
  greeting; a real prompt recorded with `*95` and adopted on the Prompts
  page; a menu behind an inbound route (no trunk on dev1).
* Email through a real SMTP server (the school's relay or Google Workspace
  SMTP): the path was verified end to end against a loopback sink, not a
  real relay.

## 5. Known limitations

* No visual voicemail: messages are heard by phone or email; the greeting
  is managed from the phone.
* Prompt conversion is basic linear-interpolation resampling; export at
  8 kHz mono from an audio tool for the best quality.
* Messages wait in the queue while SMTP is misconfigured and are given up
  after a day; the audit log (`mail.failed`) and the test button are the
  diagnostics.
* One voicemail context for the installation until Milestone 14.
* The reload of `app_voicemail.so` re-reads `voicemail.conf`; messages in
  the spool are untouched.

## 6. Open items

* Owner: upgrade dev1 and run the live checks of §3; answer the three
  questions still open from Milestone 6b (the public address of dev1 for
  `VEYRA_PUBLIC_HOST`, a browser-trusted certificate, and whether Google
  sign-in (6c) comes before Milestone 8). The owner is preparing a
  development domain name and a reverse proxy, which answers the first two
  once in place.
* Owner: the Milestone 5 real-phone checks, a look at the Milestone 6 and 7
  pages in a browser, and loading the Companion.
* A real SMTP relay for voicemail-to-email on dev1.

## 7. Proposed Milestone 8 (awaiting approval)

Ring groups, queues and call pickup (roadmap row 8, 0.10.0): ring groups
(ring all or in sequence, with a failover destination from §6's
destination model), call queues (agents, hold music, announcements,
strategies), and the owner's pickup request (group pickup `*8`, directed
pickup `**<extension>`, pickup-group membership per extension, BLF
friendly). Alternative order if preferred: a short 6c (Google-account
sign-in for the web interface and the Companion) first.

## 8. Owner decisions

* Milestone 7 approved 2026-10-13 after the dev1 upgrade and the live
  checks of §3; version 0.9.0; `main` fast-forwarded to this branch.
* Handset checks (`*97`, MWI, a recorded prompt adopted in the browser) and
  the three open questions of §6 remain with the owner; the order of
  Milestone 8 and 6c is not decided yet.
