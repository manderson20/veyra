# Milestone 1: Completion Report

**Milestone:** 1 — Automated Ubuntu installation
**Date:** 2026-10-12
**Branch:** `milestone-1` (pushed to `manderson20/veyra`; not merged to `main`)
**Status:** Complete for veyra-dev1 and Ubuntu 24.04; the veyra-dev2 installation is blocked on host access. **Approved by the project owner on 2026-10-12** ("proceed with the project"); the dev2 installation and report are deferred until the host is reachable and will be added to this report.

## 1. Scope (approved 2026-10-12)

Run and harden the installer on veyra-dev1, then on veyra-dev2 once it is
reachable. Verify with `verify.sh`, produce per-node installation reports,
confirm CI is green, check Ubuntu 24.04 compatibility, and decide between
the Ubuntu Asterisk package and a Veyra-built one.

## 2. Results

| Task | Result | Where |
|---|---|---|
| Run the installer on veyra-dev1 | Done. Three runs: the first two failed verification, the third passed all 18 checks. Then `upgrade.sh` to the fixed revision, with a from-source web build, passed verification. | [Report](../installations/veyra-dev1-2026-10-12.md) |
| Harden the installer | Done. 4 defects fixed (NGINX never served HTTPS; symlinks failed the ownership check; failures not recorded in the state file; version leak and 404-as-200), plus 7 smaller corrections. | `installer/`, CHANGELOG |
| Verify with `verify.sh` | Passed on dev1 after install and after upgrade, and on 24.04 after install and after reinstall. | reports |
| Per-node installation reports | dev1 and the 24.04 container written. dev2: not possible (see §5). | `docs/installations/` |
| Confirm CI is green | Every CI job's commands were run locally on dev1 against the final tree and passed (§3). The GitHub Actions result itself could not be read from dev1: no `gh`, private repository, deploy key only. The owner can confirm on the Actions page after the push. | §3 |
| Ubuntu 24.04 compatibility | Verified in an LXD container: Python 3.12.3, PostgreSQL 16.15, Asterisk 20.6.0, NGINX 1.24.0 all work; install, verify, uninstall, reinstall passed. Ubuntu's Node.js 18 cannot build the UI, so 24.04 needs a prebuilt `frontend/out/` (the installer says so and stops). | [Report](../installations/ubuntu-24.04-container-2026-10-12.md) |
| Asterisk packaging decision | **Ubuntu archive packages** (22.5.2 on 26.04, 20.6.0 on 24.04). Milestone 3 targets the Asterisk 20 feature set. | [ADR 0010](../adr/0010-asterisk-ubuntu-packages.md) |
| Installer on veyra-dev2 | **Not done.** `veyra-dev2` still does not resolve and there is no SSH trust from dev1. | §5 |

## 3. Testing (veyra-dev1, 2026-10-12, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean (88 files) |
| Backend mypy | No issues (71 files) |
| Backend pytest against PostgreSQL 18.6 | **108 passed** |
| Frontend lint / typecheck / vitest | Clean / clean / **18 passed** |
| Frontend `npm run build` | Passed (inside `upgrade.sh` on dev1, Ubuntu npm 9.2) |
| ShellCheck (installer scripts, templates, tests) | Clean |
| Installer helper tests | **29 passed** |
| `install.sh --dry-run --yes`, `preflight.sh` | Complete without errors on the installed host |
| `install.sh --yes` end to end | dev1: passed (third run). 24.04: passed (first run) |
| `upgrade.sh --yes` end to end | dev1: passed, including backup, build, switch, migrate, verify, history record |
| `uninstall.sh --yes` then `install.sh --yes` | 24.04: passed; account, credential, database and certificate reused |
| `verify.sh` | dev1 18/18; 24.04 18/18 |

Not tested: a reboot of an installed host; `uninstall.sh --purge`;
`upgrade.sh` across a real version change or with a failing migration (the
rollback path); HA roles (Milestone 16).

## 4. Defects found by running the installer for real

The dry runs and unit tests of Milestone 0 did not catch any of these.

1. **HTTPS never came up.** NGINX cannot bind Veyra's address-specific
   listeners by reload while the package default site holds wildcard sockets
   on port 80. It retries for two seconds and keeps the old configuration.
   Fixed by restarting in that case and by verifying with a real HTTPS
   request. A first fix that checked only "is 443 bound" passed inside the
   retry window and had to be replaced; the lesson is recorded in the dev1
   report.
2. **Symlinks failed the code-ownership check.** Links report mode 777.
3. **Failures via `die` were not recorded** in the state file (ERR trap not
   triggered by `exit`). An EXIT trap now records `failed:<step>`.
4. **Version disclosure and 404 status** in the NGINX template.
5. Smaller: `started_at` overwritten on resume; duplicate SAN; `-dirty`
   release names; IPv6 URL brackets; reinstall-after-uninstall messaging;
   upgrade summary wording; "Node.js 0 found".

## 5. Blocked and open items

* **veyra-dev2:** needs an address (DNS or `/etc/hosts`) and SSH access from
  dev1, or the owner runs `installer/install.sh` there directly. The dev2
  report is the remaining Milestone 1 deliverable; everything it needs is
  in the dev1 report and `docs/INSTALLATION.md`.
* **CI result on GitHub:** not visible from dev1 (see §2). Options: install
  and authenticate `gh` on dev1, or the owner checks the Actions tab.
* **First-run setup on dev1** has not been completed; the owner has the
  token (24 h) or runs `sudo veyra setup-token`.
* Still open from Milestone 0: license choice. (Branding artwork was supplied and installed on 2026-10-12; see `frontend/public/branding/README.md`.)

## 6. Development environment changes made on veyra-dev1

* Veyra installed by `install.sh`: packages `nginx`, `asterisk`,
  `asterisk-modules`, `asterisk-core-sounds-en`; account `veyra`;
  `/opt/veyra`, `/etc/veyra`, `/var/lib/veyra`, `/var/log/veyra`,
  `/var/backups/veyra`; database and role `veyra`; services `veyra-api`,
  `veyra-worker`; NGINX site `veyra.conf` (default site disabled); Asterisk
  `ari.conf`, `http.conf`, `manager.conf` replaced with backups beside them.
* LXD initialised (`lxd init --auto`); container `veyra-noble` (stopped).
* Two releases in `/opt/veyra/releases`; `/etc/veyra/install-state.json`
  shows `complete`.

## 7. Proposed Milestone 2 (for approval)

Backend, frontend, database and authentication: hardening, password reset,
sessions UI, MFA design (per the roadmap). Before that, or in parallel when
dev2 becomes reachable: install dev2 and write its report to close
Milestone 1 fully.
