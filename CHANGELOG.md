# Changelog

All notable changes to Veyra are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/). Before 1.0 the minor
version counts completed milestones in roadmap order (Milestone 4 → 0.4.0,
Milestone 4b → 0.5.0, Milestone 5 → 0.6.0, …); patch versions carry fixes
between milestones; `-dev` marks work in progress. Milestones 0 to 3 all
shipped as `0.1.0-dev.0` before this scheme was adopted.

## [Unreleased] — 0.8.0-dev (Milestone 6b)

### Added
- **Veyra Companion** browser extension (Chrome/Edge, Manifest V3) under `companion/`: sign in with Veyra credentials and the second factor, click-to-dial from a popup, the context menu or `tel:` links (the desk phone rings first), directory search, incoming and missed-call notifications, speed dials and settings stored in the user's profile (`docs/COMPANION.md`).
- **Scoped bearer tokens** (ADR 0015): `POST /auth/companion/login` and `/verify` reuse the web sign-in checks and issue a `vyc_…` token limited to `calls.originate`, `calls.read`, `directory.read` and own-account routes; tokens expire 30 days after last use (180 days at most), are listed and revoked on the account page ("Connected apps"), by administrators (`/users/{id}/tokens`) and by `veyra sessions revoke`. Migration `0007`.
- `GET /me/extensions`, `GET/PUT /me/preferences`, `GET /directory` (new permission `directory.read` for every role).
- **Call-event stream**: the API keeps one WebSocket to Asterisk's ARI events and serves `WS /events/calls` (ticket from `POST /events/ticket`) with `call.ringing`, `call.dialing`, `call.answered` and `call.ended` for the caller's own extensions; the engine page reports the listener state. NGINX proxies the WebSocket path. New dependency `websockets`.

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
