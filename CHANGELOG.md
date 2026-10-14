# Changelog

All notable changes to Veyra are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/). Before 1.0 the minor
version counts completed milestones in roadmap order (Milestone 4 → 0.4.0,
Milestone 4b → 0.5.0, Milestone 5 → 0.6.0, …); patch versions carry fixes
between milestones; `-dev` marks work in progress. Milestones 0 to 3 all
shipped as `0.1.0-dev.0` before this scheme was adopted.

## 0.13.0-dev — unreleased (Milestone 9c)

### Added
- **AND Clock Messages module** (`veyra.and-clocks`, Modules → install; [modules/veyra-and-clocks](modules/veyra-and-clocks/README.md), [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §6): the first real module. Text messages to Advanced Network Devices clocks and signs, like AND's Clockwise: to all clocks, a group or one clock; colour, flashers, priority and display time with AND's inline markup; sent now or at a set time; a message log; reachability checks; messages shown with bells (`{summary}` = the calendar event's name). The clock's own web request is described once under Clock Delivery (method, path, body template, sign-in; the password is encrypted). Permissions `and_clocks.read`/`send`/`write`.
- **Module API 1.1** ([MODULE_DEVELOPMENT.md](docs/MODULE_DEVELOPMENT.md) §3): periodic tasks run by the worker, which now loads enabled modules and delivers their events; `encrypt`/`decrypt` with the installation key; `organization_timezone`; `password` form fields. Core event `bell.rang`.
- **Calendars and bell schedules** (Telephony → Calendars, Bell Schedules; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §4): subscribe to an iCal feed (Google Calendar's secret address or any feed; the address is encrypted at rest and never shown again), fetched every few minutes with recurring rules expanded; a bell schedule rings a recorded page at the start or end of matching events, once per event, within a tolerance; next rings, ring history and a "Ring now" test. Migration `0015`; permissions `bells.read`/`bells.write`; dependencies `icalendar`, `python-dateutil`, `tzdata`.
- **Paging** (Telephony → Pages and Paging Zones; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §2): zones can be dialled by a number from the shared number space, with a policy of who may page (everyone, listed phones, only Veyra) and a longest page; **pages** combine zones with live audio or a recording from the library, a pre-tone, repeats and a Poly priority, are dialable, startable from the interface and the API (`POST /pages/{id}/send`, permission `paging.send`) for external triggers such as a door-held-open alarm, and logged. The **page sender** service (`veyra-pager`) takes one stream from Asterisk per zone and emits the speakers' multicast after the Poly phones' buffering delay together with the Poly group-page datagram, so phones and speakers play in step (the Poly header itself waits for a capture from the phones; until then the Poly leg carries plain RTP). Migration `0014`.
- **Hold music sets** (Telephony → Hold Music; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §3.2): ordered or shuffled sets of library recordings, played as the organization's default when a phone puts a caller on hold, per call queue, and per ring group (which can now play music instead of ringing; existing groups keep ringing). Veyra writes `musiconhold.conf` (new installer stub keeping the built-in class) and copies the recordings to `<data>/moh/`; recordings in a set cannot be deleted. Migration `0017`.
- **Shared voicemail inboxes** (Telephony → Voicemail → New shared inbox; [VOICEMAIL_IVR.md](docs/VOICEMAIL_IVR.md) §3.1): a mailbox that belongs to no phone, with its own number from the shared number space, a name and member phones whose message lamp follows it; dialable directly, a destination of its own kind (`voicemail_box`) for inbound routes, IVR keys and fallbacks, ring group and queue failovers (migration `0016`).
- **Audio library** (Telephony → Audio, the former Prompts page; `/prompts` with `kind`, `license`, `credit` and a `kind` filter): recordings are classed as menu prompt, bell, announcement, greeting or hold music; MP3, OGG, FLAC and M4A uploads are decoded by `ffmpeg` (installer package; WAV only without it, `verify.sh` warns) ([PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §3; migration `0013`).

### Fixed
- **Bells on time**: the worker ran bell schedules once per housekeeping pass (every 60 seconds), so a bell could ring up to a minute late; calendars, bells and module tasks now run on a 5-second tick (`veyra worker --tick`).
- **Compressed audio uploads**: `ffmpeg` now decodes to a temporary file rather than a pipe; a WAV written to a pipe carries placeholder sizes, which made every MP3, OGG, FLAC or M4A upload fail as "longer than 5 minutes".

### Installer
- Modules shipped with a release are signed with this server's own key (`/etc/veyra/secrets/bundled-modules.key`, trusted from `/etc/veyra/trust/official/bundled-modules.pub`), so they can be installed in production; `verify.sh` checks them (`modules-signed`).

## 0.12.0 — 2026-10-14 (Milestone 9b)

### Changed
- **Navigation**: the sidebar is a rail of six categories that never scrolls; clicking or hovering a category opens a flyout panel with its pages (keyboard: Enter opens, arrows move, Escape closes); in the mobile drawer a category expands inline; the top bar shows a breadcrumb (category › page) ([INTERFACE_REWORK.md](docs/INTERFACE_REWORK.md) §1).

### Added
- **Dashboard graphs**: two cards, Channels (with registered phones) and Calls internal vs external, with a 1 h / 6 h / 24 h / 7 d range, refreshed every 30 s, drawn by a dependency-free SVG chart with a screen-reader table. The worker records one engine reading per iteration (every 30 s, `call_samples`, kept 14 days); `GET /system/metrics/calls` serves it downsampled to at most 300 points per range (migration `0012`).

## 0.11.0 — 2026-10-14 (Milestone 9)

### Added
- **Device provisioning** ([DEVICE_PROVISIONING.md](docs/DEVICE_PROVISIONING.md)): phones registered by MAC address (`/devices`, Provisioning → Devices) fetch their configuration from `https://<host>/provisioning/` with HTTP Basic authentication: an enrollment credential per organization for the first fetch (Organization page), then a credential per phone set by its own configuration. Files are rendered on request from the profile's template; every request is logged, unregistered phones that asked for configuration are listed for one-click registration, and the device page shows status, last request, configuration preview, Reprovision and Reboot (SIP NOTIFY).
- **Device profiles** (`/device-profiles`): a template family or model plus settings, line keys (line, BLF with `**` pickup, speed dial, page), paging-zone memberships and firmware; one profile per building when only the paging differs. The phone's model picks the concrete template under a family.
- **Paging zones** (`/paging-zones`, Telephony → Paging Zones, permissions `paging.read`/`paging.write`): the speakers' multicast address and port paired with the Poly group number (1–24, 25 emergency), kind and codec; rendered into the phones' group paging settings.
- **Sites** (`/sites`, Directory → Sites): buildings with time zone, address and a default emergency caller ID for their extensions.
- **Firmware** (`/provisioning/firmware`, Provisioning → Firmware): upload vendor images (up to 512 MB), assign per profile or phone; served by NGINX; the device page compares the running version.
- **Template editor**: local templates are edited in place (manifest and sources, validated on save); **Customize** creates an editable copy of an official template, with local model templates under a customized family. `/provisioning/models` lists the catalog's manufacturers and models.
- **Templates spec version 2**: structured facts (`device`, `organization`, `lines`, `keys`, `paging`, `server`, `features`) with daylight-saving rules from the zone database; Poly VVX templates 0.2.0 (every line, line keys, BLF, voicemail indication, group paging, DST, VLAN, polling, device credential; the VVX 411 template also serves the VVX 410).
- Extensions carried by several phones get `max_contacts` in the engine; Asterisk `pjsip_notify.conf` is now Veyra-managed (`veyra-check-config`, `veyra-reboot`).
- **Emergency caller ID per extension** (`emergency_caller_id_number` on `/extensions`, Extensions form and page): presented on emergency routes instead of the regular caller ID, ahead of the route's and the trunk's numbers; the Outbound Routes page warns when extensions have none and the emergency route has no number of its own ([TRUNKS_ROUTING.md](docs/TRUNKS_ROUTING.md) §7; migration `0010`, snapshot version 6).

## 0.10.0 — 2026-10-14 (Milestone 8)

### Added
- **Ring groups** (`/ring-groups`, Telephony → Ring Groups): a number from the numbering plan that rings an ordered list of extensions all at once or one after the other, with a ring time, an optional caller-ID prefix shown on the phones, skipping of members already on a call (or call waiting), and a failover destination when nobody answers. Generated `veyra-rg-<slug>` contexts with a loop guard; a `hint` per group so BLF keys follow it. Permissions `groups.read`, `groups.write`.
- **Call queues** (`/queues`, Telephony → Call Queues): a number that holds callers with music on hold or ringing, an optional announcement on joining and a repeated one while waiting (prompts), position announcements, and distributes them to agents (extensions with a penalty) by strategy (ring all, round robin, least recent, fewest calls, random, linear) with per-attempt ring time, retry pause, wrap-up, maximum wait, maximum callers and whether callers may wait with no agent available; a failover destination for every way a caller leaves unconnected. New managed file `queues.conf` (reload `app_queue.so`), installer stub `/etc/asterisk/queues.conf`, and the `asterisk-moh-opsound-wav` package so the default hold music has files; `verify.sh` checks the stub, the `Queue`/`Pickup`/`PickupChan` applications and the music class.
- **Call pickup** (`/pickup-groups`, Telephony → Pickup Groups): pickup groups whose members answer each other's ringing calls with `*8` (named call and pickup groups on the endpoints); directed pickup `**<extension>` of any phone in the caller's organization (also for calls ringing through a group or queue); a `hint` per extension so busy lamp fields and BLF pickup work.
- **Group destinations**: inbound routes (destination and after-hours branch), IVR keys and fallbacks, ring-group failovers and queue failovers can point at a ring group or a queue; IVR direct dialling reaches group and queue numbers; groups and queues in use cannot be deleted (`409 ring_group_in_use`, `409 queue_in_use`). The extension API and page list the groups an extension belongs to; the next-number suggestion and the `409 number_in_use` check cover extensions, ring groups and queues together. Migration `0009`. Design and reference: `docs/RING_GROUPS_QUEUES.md`.

### Installer
- NGINX serves `/provisioning/` (rate-limited) and `/provisioning/firmware/` (from `/var/lib/veyra/firmware`); an opt-in plain-HTTP provisioning block (`VEYRA_PROVISIONING_HTTP=1` in `/etc/veyra/installer.conf`, with a warning); `VEYRA_PUBLIC_HOST` and `VEYRA_PROVISIONING_HTTP` written to `veyra.env`; a Veyra-managed `pjsip_notify.conf` stub; the Asterisk control socket opened to group `asterisk` (`asterisk.conf`, backed up; Asterisk restarts once) so the service account can send NOTIFY requests; `verify.sh` checks `prov-location`, `prov-auth`, `prov-http`, `firmware-dir` and `engine-cli`.
- Package `asterisk-moh-opsound-wav` (hold music for queues) and a Veyra-managed `/etc/asterisk/queues.conf` stub; `verify.sh` checks the stub, the `Queue`, `Pickup` and `PickupChan` applications and the `default` music-on-hold class. When the class is missing after an upgrade (Asterisk started before the music files existed), the installer unloads and loads `res_musiconhold.so`.

## 0.9.0 — 2026-10-13 (Milestone 7)

### Added
- **Voicemail boxes** (`/voicemail`, Telephony → Voicemail, Voicemail card on the extension page): one box per extension with a PIN encrypted at rest (shown once on creation or reset), ring time before voicemail answers, email delivery with the recording attached and optional deletion after sending; unanswered and busy calls land in the box; `*97` (own box) and `*98` (any box) from the phone; message waiting indication on the phone (`mailboxes=` on the endpoint and AOR). Users change their own PIN on the account page (`/me/voicemail`). Permissions `voicemail.read`, `voicemail.write`.
- **Email delivery** (`/system/smtp`, Settings → Email delivery): the SMTP server Veyra sends through (STARTTLS, TLS or unencrypted to a loopback relay; password encrypted with the installation key, write-only), a test message to yourself, queue counts. Asterisk hands voicemail notifications to `installer/bin/veyra-mailqueue`, which writes them into `/var/lib/veyra/mailqueue`; the worker sends them with retries (1, 5, 15, 60 minutes) and gives up after a day (`mail.failed` in the audit log). No mail transport is needed on the server.
- **Prompts** (`/prompts`, Telephony → Prompts): WAV uploads converted to 8 kHz 16-bit mono in pure Python (stereo mixed down, resampled), playback in the browser, replace and rename; **recordings from phones** with `*95` (record, `#` to stop, `1` keep / `2` listen / `3` re-record) appear on the page to be named or discarded. Files live under `/var/lib/veyra/prompts/<organization>/`.
- **IVR menus** (`/ivr`, Telephony → IVR Menus): prompt, keys `0`–`9`, `*`, `#` mapped to an extension, a voicemail box, another menu or hang-up, direct extension dialling, timeout and retry limits with separate fallbacks for timeouts and invalid keys, an optional custom invalid-key prompt; the page lists why a menu will not work (`problems`). Generated `veyra-ivr-<slug>` contexts with a loop guard. Permissions `ivr.read`, `ivr.write` (also cover prompts).
- **Typed destinations**: inbound routes (destination and after-hours branch) and IVR keys point at an extension, the voicemail of an extension or an IVR menu; the API returns a label and a `missing` flag, the generator renders missing targets as congestion, and boxes or menus in use cannot be deleted (`409 voicemail_in_use`, `409 ivr_in_use`, `409 prompt_in_use`).
- The installer manages `/etc/asterisk/modules.conf` (package list plus `noload` for `app_voicemail_odbc.so`, `app_voicemail_imap.so`, `cdr_radius.so`, `cel_radius.so`): on Ubuntu the ODBC voicemail module failed to load beside `app_voicemail.so` and unregistered the `VoiceMail` applications; `verify.sh` checks that the application is registered. Asterisk restarts once when the file changes.
- New managed file `voicemail.conf` (sensitive; reload `app_voicemail.so`), installer stub `/etc/asterisk/voicemail.conf`; `/var/lib/veyra` becomes `veyra:asterisk` with `prompts/` and `mailqueue/` shared with Asterisk, and the service account joins group `asterisk` so the worker can read what Asterisk writes there; `verify.sh` checks them. Migration `0008`. Design and reference: `docs/VOICEMAIL_IVR.md`.

### Changed
- Audit details redact keys containing `pin` as well as passwords, secrets, tokens and keys.
- The worker drains the mail queue and keeps the per-organization prompt folders on every iteration.
- `python-multipart` added for multipart uploads (pure Python).

## 0.8.1 — 2026-10-13

### Added
- **Managed deployment of the Companion** (`docs/COMPANION.md` §5.1): the installer signs the extension into `veyra-companion.crx` with a server-held key (stable extension ID), NGINX serves it at `/downloads/veyra-companion.crx`, and the API serves the update manifest at `/api/v1/companion/update.xml`; Settings → Companion extension deployment shows the ID, update URL, install-source pattern, policy JSON and the Google Admin Console steps; the account page gains an *Add to Chrome* button and clearer manual steps. `GET /companion/info`. Setting `VEYRA_COMPANION_DIR`; installer variable `VEYRA_PUBLIC_HOST` overrides the host name used for the packaged host permission.
- The extension reads policy-provided settings (`chrome.storage.managed`: `serverUrl`, `dialPrefix`), preloading and locking the server address.

## 0.8.0 — 2026-10-13 (Milestone 6b)

### Added
- **Veyra Companion** browser extension (Chrome/Edge, Manifest V3) under `companion/`: sign in with Veyra credentials and the second factor, click-to-dial from a popup, the context menu or `tel:` links (the desk phone rings first), directory search, incoming and missed-call notifications, speed dials and settings stored in the user's profile (`docs/COMPANION.md`).
- The installer packages the extension as `veyra-companion.zip`, served at `/downloads/veyra-companion.zip`; the account page's Connected apps card links to it with the install steps.
- **Scoped bearer tokens** (ADR 0015): `POST /auth/companion/login` and `/verify` reuse the web sign-in checks and issue a `vyc_…` token limited to `calls.originate`, `calls.read`, `directory.read` and own-account routes; tokens expire 30 days after last use (180 days at most), are listed and revoked on the account page ("Connected apps"), by administrators (`/users/{id}/tokens`) and by `veyra sessions revoke`. Migration `0007`.
- `GET /me/extensions`, `GET/PUT /me/preferences`, `GET /directory` (new permission `directory.read` for every role).
- **Call-event stream**: the API keeps one WebSocket to Asterisk's ARI events and serves `WS /events/calls` (ticket from `POST /events/ticket`) with `call.ringing`, `call.dialing`, `call.answered` and `call.ended` for the caller's own extensions; the engine page reports the listener state. NGINX proxies the WebSocket path. New dependency `websockets`.

### Development
- `tools/fakephone.py` answers digest challenges when it places a call, so it can dial as a registered phone.

## 0.7.0 — 2026-10-13 (Milestone 6)

### Added
- **SIP trunks** (`/trunks`, Telephony → SIP Trunks): registration and IP-authenticated carrier connections with write-only passwords encrypted at rest, codec and caller-ID options, channel caps and live reachability from the engine's qualify ping. Generated `pjsip.trunks.conf` (the installer's `pjsip.conf` stub includes it).
- **Inbound routes** (`/routing/inbound`, Telephony → Inbound Routes): DIDs to extensions per organization, optionally restricted to one trunk, with North American `1`/`+1` aliases, a caller-ID name prefix and a catch-all (`any`) route per trunk or shared.
- **Outbound routes** (`/routing/outbound`, Telephony → Outbound Routes): dial patterns (prefix, match, prepend) to an ordered list of trunks with failover on CHANUNAVAIL/CONGESTION, per-route caller ID, drag-free reordering, and emergency routes that are always evaluated first; warnings when no emergency route exists.
- **Time conditions** (`/routing/time-conditions`, Telephony → Time Conditions): weekly ranges and yearly holidays in a time zone, used by inbound routes to pick an in-hours or after-hours destination; `open_now` in the API.
- Loop detection: calls arriving from a trunk may not leave through a trunk; trunk channel caps enforced with `GROUP_COUNT`.
- Permissions `trunks.read`, `trunks.write` (platform), `routing.read`, `routing.write`. Migration `0006`.
- Design and reference: `docs/TRUNKS_ROUTING.md`; emergency routing status in `docs/EMERGENCY_CALLING.md`.

### Changed
- Phone endpoints carry `set_var=VEYRA_ORG=<organization>` for later per-tenant routing; `veyra-internal` now includes `veyra-outbound` between the feature codes and the invalid-number catch-all.

### Development
- `tools/fakephone.py` can act as a carrier (`--no-register`, `--call`, `--from-user`, `--header`, `--hangup-after`) and bind to a chosen address (`--local-ip`).

## 0.6.0 — 2026-10-13 (Milestone 5)

### Added
- Live registration state per extension (badge in the list and on the page, refreshed every 15 s) from the engine's endpoint status.
- Telephony → **Active Calls**: channels that are up, with the owning extension and real durations, scoped to the caller's organizations (`GET /calls`, permission `calls.read`).
- **Click-to-dial**: "Call from this phone" on the extension page and `POST /calls/originate` ring the extension first and place the call when answered (ARI originate); users dial from their own extensions (`calls.originate`), administrators from any extension they manage. Internal numbers and feature codes until trunks exist.
- **Deploy when no calls are active**: a drop-down on the Deploy changes button (and `{"mode": "when_idle"}` on apply/deploy, `veyra config deploy --when-idle`); the deployer waits while the engine reports active calls, up to `VEYRA_DEPLOY_IDLE_TIMEOUT_MINUTES` (30), then deploys and records the wait; the top bar shows "Waiting for N calls to end". Migration `0005`.

### Changed
- Active call durations are computed from the channel creation time (they were reported as 0).

### Fixed
- Feature codes `*43` (echo test) and `*60` (speaking clock) were unreachable from phones: the invalid-number catch-all lived in `veyra-internal` itself and Asterisk matches a context's own patterns before its includes. The catch-all now lives in `veyra-invalid`, included after `veyra-features`. Takes effect on the next generated and deployed revision.

### Development
- `tools/fakephone.py`: a standard-library SIP phone for exercising registration, calls, click-to-dial and deploy-when-idle on a server without a handset (`docs/DEVELOPMENT.md` §3b).

## 0.5.0 — 2026-10-12 (Milestone 4b)

### Added
- Two-factor authentication (`docs/MFA_DESIGN.md`): authenticator apps (TOTP, RFC 6238) with ten single-use recovery codes; sign-in answers 202 and opens a 5-minute pre-authentication session that can reach only the second-step routes; codes accept one step of clock drift and are never accepted twice; five wrong codes lock the attempt. Enrolment with a server-rendered QR code or manual key, device labels, recovery codes shown once with download and copy; devices removed and codes regenerated behind the password. Account page card, sign-in second step with inline enrolment, grace notice in the shell.
- Two-factor policy (`/auth/mfa/policy`, Settings → Two-factor policy): which roles must use it (Platform and Organization Administrators by default) and how many days they have (14); saving re-evaluates every user and is audited. Administrators reset a user's factors from the user page (`POST /users/{id}/mfa/reset`); `veyra users mfa-reset <email>` on the server is the escape hatch for the recovery administrator.
- `GET /auth/session` and `GET /users/{id}` report the two-factor status (`mfa`, `mfa_enabled`). NGINX rate-limits code verification like sign-in.
- Migration `0004`: `mfa_methods`, `mfa_recovery_codes`, `users.mfa_required_at/mfa_grace_until`, `sessions.mfa_verified_at/mfa_failures` (existing sessions stay valid).
- Roadmap: click-to-dial API (Milestone 5) and the Veyra Companion browser extension (Milestone 6b).

### Changed
- **Deploy changes** now appears after any save that may affect the engine (extensions, SIP settings) and stays until a deployment runs, whether or not the generated files differ; the engine status reports who saved and when (`pending_since`, `pending_by`).
- Dependency: `segno` 1.6.6 for QR codes.

## 0.4.0 — 2026-10-12 (Milestone 4)

### Added
- Installation key (`/etc/veyra/secrets/installation.key`, ADR 0014): a 256-bit key generated by the installer (also on upgrade, never replaced) that encrypts secrets at rest with AES-256-GCM and purpose binding. `veyra installation-key generate|check`; `verify.sh` checks it; `VEYRA_INSTALLATION_KEY_FILE`.
- Extensions (`docs/EXTENSIONS.md`): `/extensions` CRUD scoped by organization, optional assigned user, caller ID, enable/disable, delete; SIP user name `<org>-<number>`; server-generated SIP secrets stored encrypted, shown and rotated only through audited endpoints (`extension.secret_reveal`, `extension.secret_rotate`); global search finds extensions.
- Numbering plan (`/telephony/numbering`): length, range and reserved leading digits (`0`, `9`, `911`, `933` by default), enforced on create and renumber; `GET /extensions/next-number` suggests the lowest free number; a numbering step in the setup wizard.
- Extensions pages: list with search and organization filter, create dialog with "Suggest next free", detail page with SIP credentials (show, copy, rotate), delete with typed confirmation, numbering plan card; notices when changes are waiting to be deployed or the installation key is missing.
- `GET /telephony/engine` reports `changes_pending` and `installation_key_present`; the engine page shows both.
- **Deploy changes** button in the top bar for platform administrators whenever changes are pending (`POST /telephony/apply` generates and deploys in one step, discards a no-change revision, reports generation problems); other users see a "changes pending" badge.
- The running version is shown next to the logo (the installed release name in its tooltip); `GET /auth/session` carries `version` and `release`.
- Versioning scheme adopted (see the top of this file); version 0.4.0 marks Milestone 4.
- Migration `0003`: `extensions.sip_secret_changed_at`.

### Changed
- Configuration snapshots now contain the enabled extensions of active organizations with decrypted SIP secrets; the generator refuses duplicate numbers; sensitive revision files are stored encrypted in `config_revisions.artifacts` and decrypted by the deployer (a deployer without the key fails the revision and restores the previous files).
- The `Extensions` navigation entry is live (needs `extensions.read`) instead of "coming later".

### Fixed
- The logo appeared twice side by side on the sign-in, setup and account pages, and the emblem showed next to the wordmark in the sidebar: inline styles overrode the CSS that hides the unused artwork.
- `upgrade.sh` now records `upgrade_status: complete`, so a failure marker from an earlier attempt does not linger in the install state.

## 0.1.0-dev.0 (Milestone 3)

### Added
- Telephony engine integration (`docs/TELEPHONY_ENGINE.md`): Asterisk configuration generated from the database (PJSIP transports and endpoint templates, dialplan with `*43` echo test and `*60` speaking clock, RTP settings) into `/etc/asterisk/veyra/`, which Veyra-managed stub files include.
- Configuration revisions: generate, preview diffs, deploy, discard, and roll back by redeploying an older revision (`/telephony/revisions`, `veyra config`). Failed deployments restore the previous files.
- `veyra-deployer` service: the only process that writes engine files; targeted module reloads over ARI (`res_pjsip.so`, `pbx_config.so`, `res_rtp_asterisk.so`) and post-reload verification.
- SIP and media settings (`/telephony/settings`, System → Telephony Engine): bind address, ports, TLS, NAT addresses, local networks, RTP range, codecs, language, with validation.
- Engine status (`/telephony/engine`): version, start and reload times, module status, endpoint and channel counts; `/system/health` now reports real `registrations` and `active_calls` counts. The setup wizard shows the engine state.
- Installer: Asterisk stubs replace the package samples (backed up), `/etc/asterisk/veyra` is `2750 veyra:asterisk`, the deployer unit is installed and verified; upgrades reload Asterisk only when its managed files changed and never restart it.

## 0.1.0-dev.0 (Milestone 2)

### Added
- Sessions: `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others`; administrators: `GET/DELETE /users/{id}/sessions`. "Your account" page with profile, password change and active sessions; the user page shows a user's sessions with "Sign out everywhere".
- Password reset links (ADR 0011): `POST /users/{id}/password-reset-link`, public `/reset-password/` page, `POST /auth/password-reset/check` and `POST /auth/password-reset`; `veyra users reset-password` and `veyra users unlock` on the server; `POST /users/{id}/unlock` and an "Unlock now" button.
- Forced password change: passwords set by an administrator (on creation or reset) are temporary unless `require_password_change` is false; the user is taken to the account page and can reach nothing else until they choose a password. `password_changed_at` and `must_change_password` on users (migration `0002`).
- Password policy: at least four distinct characters, no weak words however padded, no personal information (name, email local part), new password must differ from the current one.
- Fetch-metadata check: mutations labelled `cross-site` or `same-site` by the browser are refused (`403 cross_site_request`). `Clear-Site-Data` on sign-out. NGINX rate limits the password-reset endpoints like sign-in.
- Worker purges expired and revoked sessions and used reset tokens after the retention period (`VEYRA_SESSION_RETENTION_DAYS`, default 30); `veyra sessions purge` and `veyra sessions revoke`.
- MFA design (`docs/MFA_DESIGN.md`, ADR 0012): TOTP with recovery codes first, passkeys second, pre-auth session at sign-in; implementation scheduled later.

### Changed
- `UserOut` includes `locked_until`, `password_changed_at` and `must_change_password` (administrators only see these through the users API; the sign-in form stays generic).
- The user menu links to the account page instead of a password dialog.

## 0.1.0-dev.0 (Milestone 1)

### Added
- Approved branding artwork (raster exports supplied by the owner) replaces the placeholder SVGs: compact and full logos for light and dark backgrounds, emblem, app icon, favicons, touch icon, a web manifest, and the owner's ASCII wordmark for the CLI and installer. The branding board is kept in `docs/branding/`.
- First real installations: veyra-dev1 (Ubuntu 26.04) installed, verified and upgraded; Ubuntu 24.04 installed, verified, uninstalled and reinstalled in an LXD container. Reports in `docs/installations/`.
- ADR 0010: Asterisk is installed from the Ubuntu archive (22.5.2 on 26.04, 20.6.0 on 24.04), not built by Veyra.
- Installer: reinstalling after `uninstall.sh` is recognised and reported as a reinstall over kept data.

### Fixed
- Installer: NGINX is restarted instead of reloaded when its listen sockets change (the package default site's wildcard sockets blocked Veyra's address-specific listeners, so HTTPS never came up), and the step verifies an HTTPS request before reporting success.
- Installer: `verify.sh` no longer flags the venv's symbolic links as world-writable code.
- Installer: failures that exit through `die` are recorded in the state file (`failed:<step>`); the original `started_at` survives resumed runs.
- Installer: the HTTP redirect no longer reveals the NGINX version; unknown paths return 404 instead of 200; IPv6 setup URLs are bracketed; the self-signed certificate lists a hostname once when it equals the FQDN; a missing Node.js is reported as missing rather than as version 0; the upgrade summary names releases when the version number is unchanged.

### Changed
- Installer: release names carry a `-dirty` suffix when installed from a source tree with uncommitted changes.

## 0.1.0-dev.0 (Milestone 0)

### Added
- Architecture and design documentation: architecture, HA, engine evaluation (Asterisk selected), module development, provisioning templates, update management, installation, development, networking, database schema, licensing evaluation, emergency calling notes and ADRs 0001–0009.
- Backend foundation (FastAPI, SQLAlchemy, Alembic, PostgreSQL): tenancy and identity schema, local authentication (Argon2id, server-side sessions, CSRF, rate limiting, lockout), scoped RBAC, append-only audit log, first-run setup with a console token, health and HA status APIs, global search.
- Module framework: manifest specification and validator, Ed25519-signed packages with trust levels, per-module migrations, lifecycle (install/enable/disable/update/uninstall with data retention), event bus, health checks, declarative UI views, and the `veyra.example-notes` example module.
- Provisioning template framework: specification, inheritance, sandboxed rendering, validation, preview with secret masking, import/export, and experimental Poly VVX 411/450 templates.
- Update management foundation: per-component policies, channels, signed update metadata verification, update checks and history.
- Telephony adapter interface with an Asterisk ARI health check.
- `veyra` CLI with color/monochrome/ASCII terminal branding.
- Frontend foundation: Next.js static export, design system, application shell and pages backed by the API.
- Installer: `preflight.sh`, `install.sh`, `verify.sh`, `upgrade.sh`, `uninstall.sh`, systemd/NGINX/Asterisk templates.
- CI: backend tests (PostgreSQL), lint and type checks, frontend lint/typecheck/test/build, ShellCheck, dependency audit, secret scan; Dependabot.
