# Changelog

All notable changes to Veyra are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.1.0-dev.0 (Milestone 0)

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
