# Changelog

All notable changes to Veyra are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.1.0-dev.0 (Milestone 1)

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
