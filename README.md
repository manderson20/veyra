<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/branding/logo-dark.png">
    <img src="frontend/public/branding/logo-light.png" alt="Veyra — Open Communications Platform" width="360">
  </picture>
</p>

# Veyra

**Open Communications Platform** · pronounced *VAY-ruh*

Veyra is a modern, modular, self-hosted communications platform: a
professional management layer around an established open-source telephony
engine (Asterisk). It targets schools and districts, municipalities,
businesses, MSPs and IT departments. It needs no cloud service and no
subscription for self-hosted use.

> **Status: early development (Milestone 1 — automated installation).** Not for production use.
> The `companion/` directory holds the Veyra Companion browser extension (docs/COMPANION.md).
> Telephony features (extensions, trunks, routing, voicemail…) arrive in later milestones;
> see the [roadmap](docs/ROADMAP.md).

## What's here

| Area | State |
|---|---|
| Architecture, HA design, engine evaluation | [docs/](docs/) |
| Backend API (FastAPI + PostgreSQL): auth, RBAC, tenancy, audit, health | Working, tested |
| Module framework (signed packages, lifecycle, per-module migrations, example module) | Working, tested |
| Provisioning templates (sandboxed, inheritance; Poly VVX 411/450 experimental) | Working, tested; phone delivery in M9 |
| Update management (policies, signed metadata, checks) | Foundation; installs in M12 |
| Admin web UI (Next.js static export, design system) | Foundation |
| Ubuntu installer (preflight, install, verify, upgrade, uninstall) | Installed, verified and upgraded on veyra-dev1 (26.04); installed, verified, uninstalled and reinstalled on Ubuntu 24.04 ([reports](docs/installations/)) |
| High availability (active/passive) | Designed; implemented and tested in M16 |

## Quick links

- [Installation](docs/INSTALLATION.md) · [Development](docs/DEVELOPMENT.md) · [Architecture](docs/ARCHITECTURE.md)
- [HA architecture](docs/HA_ARCHITECTURE.md) · [Engine evaluation](docs/ENGINE_EVALUATION.md) · [ADRs](docs/adr/)
- [Module development](docs/MODULE_DEVELOPMENT.md) · [Provisioning templates](docs/PROVISIONING_TEMPLATES.md) · [Update management](docs/UPDATE_MANAGEMENT.md)
- [API](docs/API.md) · [Database schema](docs/DATABASE_SCHEMA.md) · [Networking](docs/NETWORKING.md)
- [Security](SECURITY.md) · [Changelog](CHANGELOG.md) · [Licensing evaluation](docs/LICENSING.md)
- [Installation reports](docs/installations/) · [Milestone reports](docs/milestones/)

## Repository layout

```
backend/      Python API, CLI, module framework, migrations, tests
frontend/     Next.js admin interface and design system
modules/      Official modules (example: veyra-example-notes)
provisioning/ Official phone provisioning templates
installer/    Ubuntu installer, verification, upgrade, uninstall
docs/         Documentation, ADRs, milestone reports
```

## License

Veyra is licensed under the **GNU Affero General Public License v3.0 or later** (see [LICENSE](LICENSE), [docs/LICENSING.md](docs/LICENSING.md) and [ADR 0013](docs/adr/0013-license-agpl.md)).
The repository is private during development.
