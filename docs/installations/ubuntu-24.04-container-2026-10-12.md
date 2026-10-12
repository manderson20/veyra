# Installation report: Ubuntu 24.04 compatibility check

**Date:** 2026-10-12 · **Milestone:** 1 · **Outcome:** installed and verified with a prebuilt web interface; from-source build not possible with Ubuntu's Node.js.

## Environment

| | |
|---|---|
| Container | LXD `veyra-noble` on veyra-dev1 (`lxc launch ubuntu:24.04 veyra-noble`), 10.227.92.10 |
| OS | Ubuntu 24.04.5 LTS (secondary target), systemd running |
| Source | Tarball of the working tree at `0e72d9b` plus patches, including the prebuilt `frontend/out/` from dev1; no `.git`, so the release is named `0.1.0-dev.0-local` |

A container differs from a VM: no kernel of its own, no real NICs, and
`timedatectl` reports the host's clock. Package installation, service
behaviour and Veyra's own checks are representative; performance is not.

## Versions installed by `install.sh`

| Component | 24.04 | 26.04 (dev1) |
|---|---|---|
| Python | 3.12.3 | 3.14.4 |
| PostgreSQL | 16.15 | 18.6 |
| Asterisk | 20.6.0 | 22.5.2 |
| NGINX | 1.24.0 | 1.28.3 |
| Node.js | 18.19 (not installed; too old to build the UI) | 22.22.1 |

## Results

| Step | Result |
|---|---|
| `preflight.sh` | Exit 2: one warning (secondary target). All other checks passed. |
| `install.sh --yes` (prebuilt UI) | Completed in about 70 s including package installation. Asterisk 20.6 started with Veyra's ARI/HTTP/AMI configuration; ARI authenticated. NGINX needed the wildcard-listener restart (detected and handled). **All verification checks passed.** Setup token and URLs printed, including a bracketed IPv6 URL after the fix. |
| `verify.sh` | 18/18 passed on a second, separate run. |
| `uninstall.sh --yes` (keep data) | Services, release and NGINX site removed; `/etc/veyra`, database and credentials kept; state `uninstalled`. |
| `install.sh --yes` again | Reused the account, ARI credential, database and certificate; completed and verified. |
| `install.sh --dry-run --yes` without `frontend/out` | Stops at the version check with the documented message: Node.js 20.9 or newer is needed; use a release bundle with a prebuilt frontend. |

## Conclusions for Ubuntu 24.04

* Veyra 0.1.0 runs on Python 3.12, PostgreSQL 16 and Asterisk 20 without
  code changes. CI already tests Python 3.12.
* A 24.04 host needs a **prebuilt web interface**. Release bundles will
  include `frontend/out/`; until then, build it on a machine with Node.js
  20.9+ (for example dev1) and copy it into the source tree before running
  the installer. Installing Node.js from NodeSource was not tested and is
  not recommended by the installer.
* Asterisk 20 is two major versions behind 26.04; see ADR 0010 for why the
  Ubuntu package is still the right choice and when to revisit it.

## Clean-up

The container is stopped and kept for reproduction. Remove it with
`lxc delete veyra-noble`. LXD was initialised on dev1 with
`lxd init --auto` for this test (bridge `lxdbr0`, default storage pool).
