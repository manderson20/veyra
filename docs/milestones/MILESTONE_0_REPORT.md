# Milestone 0: Completion Report

**Milestone:** 0 — Architecture, repository foundation and modular framework
**Date:** 2026-10-12
**Branch:** `milestone-0` (pushed to `manderson20/veyra`; not merged to `main`)
**Status:** Complete. Approved by the project owner on 2026-10-12 and merged to `main`.

## 1. Scope

The 21 tasks of directive §37: repository inspection, engine evaluation,
architecture, database schema, repository structure, backend, frontend,
design system and shell, CLI branding, module manifest, registration
framework and example module, provisioning template specification,
installer and verification scripts, update management architecture, tests,
CI, documentation, commits, and this report.

## 2. Results by task

| # | Task | Result | Where |
|---|---|---|---|
| 1 | Inspect the repository | Done. It contained only an initial commit with a one-line README and a **GPL-3.0** LICENSE (flagged in §6). | — |
| 2 | Evaluate Asterisk vs FreeSWITCH | Done. **Asterisk 22 LTS selected**, with package availability verified on veyra-dev1. | `docs/ENGINE_EVALUATION.md`, ADR 0001 |
| 3 | Design the architecture | Done: standalone, multi-tenant model, central management, adapter, HA, modules, updates, config management, security boundaries | `docs/ARCHITECTURE.md`, `docs/HA_ARCHITECTURE.md`, ADRs |
| 4 | Initial database schema | Done: 25 tables, Alembic migration `0001`, append-only audit trigger | `docs/DATABASE_SCHEMA.md` |
| 5 | Repository structure | Done | `README.md` |
| 6 | Backend foundation | Done: FastAPI with `/api/v1`, auth, RBAC, tenancy scoping, audit, setup, health, search, modules, updates, HA status, provisioning | `backend/` |
| 7 | Frontend foundation | Done: Next.js 16 static export, TypeScript strict | `frontend/` |
| 8 | Design system and app shell | Done: tokens (light and dark), about 25 components, sidebar, global search, theme toggle, user menu, real pages | `frontend/src/components` |
| 9 | CLI branding | Done: truecolor, 256-color, 16-color, monochrome and ASCII forms; honours NO_COLOR and non-TTY output; shared with the installer | `backend/veyra/cli/branding.py`, `installer/lib/branding.sh` |
| 10 | Module manifest specification | Done: `module.toml` v1 with validator and JSON Schema | `docs/MODULE_DEVELOPMENT.md` |
| 11 | Module registration framework | Done: discovery, signing and trust, compatibility checks, lifecycle, per-module migrations, events, health, declarative UI | `backend/veyra/modules/` |
| 12 | Example module | Done: `veyra.example-notes`, exercised end to end in tests | `modules/veyra-example-notes/` |
| 13 | Provisioning template specification | Done: spec, sandboxed renderer, inheritance, import and export, Poly VVX 411/450 (experimental) | `docs/PROVISIONING_TEMPLATES.md` |
| 14 | Automated Ubuntu installer | **Written, not yet run for real** (see §4) | `installer/` |
| 15 | Installation verification scripts | Written: `verify.sh`; `preflight.sh` run on veyra-dev1 | `installer/` |
| 16 | Update management architecture | Done: design, policy model and API, signed metadata verification, checker, history; upgrade procedure in `upgrade.sh` | `docs/UPDATE_MANAGEMENT.md` |
| 17 | Automated tests | Done (see §3) | `backend/tests`, `frontend/src/**/*.test.ts`, `installer/tests` |
| 18 | GitHub Actions | Written (see §4) | `.github/workflows/ci.yml` |
| 19 | Document the dev environment and HA | Done | `docs/DEVELOPMENT.md`, `docs/HA_ARCHITECTURE.md` |
| 20 | Commit using the authorized workflow | Done: 5 commits on `milestone-0`, pushed through a repository-scoped deploy key | — |
| 21 | Completion report | This document | — |

## 3. Testing (all results observed on veyra-dev1, 2026-10-12)

| Suite | Result |
|---|---|
| Backend pytest against PostgreSQL 18.6 | **108 passed** |
| Backend ruff (lint and format) | Clean |
| Backend mypy (71 files) | No issues |
| Alembic: upgrade → downgrade → upgrade, and `alembic check` (models match migrations) | Passed |
| Frontend `npm ci` (Ubuntu npm 9.2) / lint / typecheck / vitest | Passed / clean / clean / **18 passed** |
| Frontend `npm run build` (static export, 19 pages) | Passed |
| `npm audit --omit=dev` | 0 vulnerabilities (after the Next.js 16.3.8 security update) |
| ShellCheck (all installer scripts) | Clean |
| Installer helper tests | **29 passed** |
| `preflight.sh` on veyra-dev1 | Ready, with 2 warnings (unallocated LVM space; PostgreSQL already running) |
| `install.sh --dry-run`, `uninstall.sh --dry-run` | Complete without errors; no changes made |
| Rendered systemd units with `systemd-analyze verify` | No issues |
| Manual smoke test (API plus `next dev`): all 18 routes, setup, module install and enable, CSRF rejection, preview masking | Passed (frontend agent's run) |

What the backend tests cover: the setup token flow and one-time setup;
login and logout; generic failure messages; account lockout; IP rate
limiting; CSRF; cookie flags; password change revoking other sessions;
organization admins confined to their own organization (including attempted
privilege escalation); denials being audited; deactivated users being signed
out immediately; last-admin protection; the full module lifecycle (data kept
on uninstall, purge needing confirmation, unsigned modules refused in
production); module tampering, untrusted keys and path traversal in packages;
the template sandbox blocking code execution; secret masking and export;
signed update metadata (tampering, expiry, rollback, wrong trust level); and
the append-only audit log.

## 4. Not verified

* **CI has not been observed running.** The workflow is pushed, but this machine has no GitHub API credentials, so I could not see the Actions results. Please check the Actions tab. Some failure points are plausible on a first run: the `postgres:18` service image tag, Python 3.12 compatibility (only 3.14 was tested locally), and gitleaks behaviour on a private personal repository.
* **The installer has not been executed for real.** Running it installs NGINX and Asterisk, creates the service account and changes system state. That is the scope of Milestone 1 ("Automated Ubuntu installation"), so per the directive it was not done in Milestone 0. `nginx -t` on the generated site configuration therefore has not run yet either.
* **Ubuntu 24.04 compatibility has not been verified.** No 24.04 host was available. Ubuntu's Node.js on 24.04 is known to be too old to build the UI (documented).
* **No browser-based UI testing.** No browser is installed on the server, so accessibility follows WCAG 2.2 AA in how it was built but has not been audited with a tool.
* **veyra-dev2 was not inspected.** It does not resolve in DNS, and there is no SSH trust from dev1.

## 5. Known limitations (by design for Milestone 0)

* There are no telephony features yet. Extensions, trunks, routing, voicemail and the rest appear as "coming later" with their milestone. The dashboard shows active calls and registrations as "not available yet" rather than inventing numbers.
* The Asterisk adapter only checks health. Configuration generation and deployment come in M3.
* Module packages cannot yet be installed through the UI (modules are discovered in the module paths). The isolated service runtime for community and third-party modules is M11.
* The update system checks for updates but never installs them. No release signing key or update server exists yet. Unattended modes are refused.
* The Poly VVX templates have not been tested on hardware and use a fixed UTC offset (no DST rules).
* HA is status reporting only. Automatic failover is disabled.
* The API runs as a single process (documented), and the rate limiter is per process.
* The CSP allows `'unsafe-inline'` scripts because of how Next.js static export works.
* Version policy exception: `next` 16.3.8 is 12 days old, for security reasons. ESLint stays on 9.x because of `eslint-config-next` peer ranges.

## 6. Decisions needed from the project owner

1. **License.** The repository's LICENSE is GPL-3.0; the directive's candidates are AGPL-3.0 and Apache-2.0. See `docs/LICENSING.md`.
2. **Engine choice.** Please confirm Asterisk (ADR 0001).
3. **veyra-dev2 access.** Its address (or a DNS or `/etc/hosts` entry), and whether to set up key-based SSH from dev1.
4. **Disk.** veyra-dev1 has about 49 GB of unallocated LVM space. Extend it with `sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv`.
5. **Branding.** Approved logo artwork can replace the placeholder files in `frontend/public/branding/` (no code changes needed).
6. **Merge.** Review `milestone-0` and merge it to `main` (a pull request can be opened from the branch on GitHub). PR creation was not possible from the server without an API token.

## 7. Development environment changes made on veyra-dev1

* Packages: `python3-venv`, `python3-dev`, `build-essential`, `libpq-dev`, `postgresql` (18.6, listening on localhost only), `nodejs`, `npm`, `shellcheck`.
* PostgreSQL role `veyra_dev` (password `veyra_dev`, CREATEDB) with databases `veyra_dev` and `veyra_test`, for local development only. The `veyra_dev` database contains a development administrator (`admin@veyra.local`), an organization "Development" and the example module with one note, all created during UI smoke testing.
* `~/.ssh/veyra_deploy` deploy key and the `github-veyra` SSH host alias.
* `/etc/sudoers.d/90-veyra-dev` (created by the owner). Remove it when no longer needed.

## 8. Proposed Milestone 1 (for approval)

Run and harden the installer on veyra-dev1, then on veyra-dev2 once it is
reachable. Verify with `verify.sh`, produce per-node installation reports,
confirm CI is green, check Ubuntu 24.04 compatibility, and decide between
the Ubuntu Asterisk package and a Veyra-built one.

## 9. Owner decisions (2026-10-12)

* Asterisk confirmed as the telephony engine.
* veyra-dev1 root volume extended to the full disk (97 GB).
* `milestone-0` merged to `main` (fast-forward).
* Milestone 1 approved.
* Still open: license choice; veyra-dev2 address and SSH access; approved branding artwork.
