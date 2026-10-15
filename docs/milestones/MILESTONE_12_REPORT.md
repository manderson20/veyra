# Milestone 12 Report — Software Update Management

Branch `milestone-12` (from `milestone-11` at 0.17.0). Design:
[SOFTWARE_UPDATES.md](../SOFTWARE_UPDATES.md). Status: **complete, awaiting
owner approval** (to be released as 0.18.0).

## 1. Scope (roadmap row 12)

Download, approve and apply Veyra updates from the interface, maintenance
windows, release signing.

## 2. Results

* **Releases**: `veyra release build` makes `veyra-<version>.tar.gz` from a
  clean checkout (`git archive`) plus the prebuilt web interface and
  Companion extension and a `REVISION` file (install.sh and upgrade.sh use
  it when there is no git checkout); `veyra release add` writes the entry
  (size, SHA-256, module API, commit) and a new sequence and expiry;
  `release refresh` extends the expiry; `release sign` signs with the
  official key.
* **Update source** (System → Updates): metadata address (overrides
  `VEYRA_UPDATE_METADATA_URL`), optional read-only token for a private
  source (encrypted, sent only to the source, never shown), email
  recipients.
* **Download** into `<data>/updates/<version>/`, kept only when size and
  SHA-256 match the signed metadata; one core version kept.
* **Review** (notes, impact, size, checks: newer, minimum version, module
  API compatibility, disk space, no other installation) and **approval**:
  install now, or in the maintenance window; withdraw before it starts.
* **Policies** for Veyra itself: mode C downloads automatically; mode D
  also approves the chosen categories and installs inside the window (not
  in its last 15 minutes) when no call is in progress. Modules keep
  notify-only (the catalog updates them).
* **Root runner** `veyra-upgrade@<version>.service`: polkit lets the service
  account *start* only that unit. The runner verifies the stored metadata
  against `/etc/veyra/trust/official`, refuses older versions, copies the
  artifact into `/var/lib/veyra-upgrade/work` (root, 0700) without following
  links and checks size and SHA-256 on the copy, unpacks it refusing path
  tricks and special files, checks the unpacked version, and runs that
  release's `installer/upgrade.sh --yes`. Progress (step, last 40 lines) in
  `/var/lib/veyra-upgrade/status.json`; the full log in `/var/log/veyra`;
  failures recorded in the update history.
* The Updates page shows the progress live and keeps polling while the API
  restarts; the new worker finishes the update's state and sends the
  email (available, downloaded, installed, failed).
* **Operating system packages**: `apt list --upgradable` once a day, shown
  with security updates and Asterisk marked; not applied.
* Installer: unit, polkit rule, directories, `verify.sh` check
  `upgrade-unit`; uninstall.sh removes the unit and the polkit rule (and now
  also the pager and firewall units it used to leave behind). Migration
  `0025`.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (167 files) |
| Backend pytest | **379 passed** (M12 added 12 tests: release contents and metadata, download with tampering and token, approval rules, worker start committed before systemctl, finish from the status file, failed start, modes C/D with the window and the call rule, windows past midnight and the last 15 minutes, the runner end to end with a failing and a succeeding `upgrade.sh`, a changed artifact, a planted link, an unknown key, path tricks, older versions, apt parsing) |
| `alembic check` | No drift (migration `0025`) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **39 passed** / passed |
| Installer library tests | **52 passed** (REVISION, the unit template, the polkit rule evaluated with node: start of the upgrade unit only, by veyra only) |
| **Owner's `upgrade.sh` on dev1** | 0.17.0-10da4ffcad → **0.17.0-c04e58e07c** (05:42 UTC: schema `0025`, `upgrade-unit` OK) |

### Live check on dev1 (2026-10-15 05:45-05:50 UTC)

A throwaway build of this branch versioned **0.17.1-dev.1** (local commit,
not pushed), signed with a temporary key the owner trusted in
`/etc/veyra/trust/official/`, served on loopback.

| Check | Result |
|---|---|
| Untrusted key | Before the key was installed: "rejected: Signing key 'm12-live-test' is not trusted on this installation" |
| Check | "1 update(s) available" |
| Tampered artifact | One byte appended on the server: "The download is larger than the signed size", nothing kept |
| Download | Verified and stored; checks all OK |
| Approval "now" | The worker started `veyra-upgrade@0.17.1-dev.1.service` at 05:49:27 |
| Upgrade | Runner verified and ran the release's `upgrade.sh`: backups, migrations, verify "Installation verified", **finished 05:49:56** (29 s). `/opt/veyra/current` → `0.17.1-dev.1-81ced39239` (revision from the REVISION file); new worker "Veyra 0.17.1-dev.1" |
| Finish | Update `installed`; history "0.17.0 → 0.17.1-dev.1, success, Veyra updates"; download directory removed; HTTPS ping OK |
| Cleanup | Local server stopped, update source cleared, throwaway branch and worktree deleted |

dev1 now runs 0.17.1-dev.1, identical to this branch except the version
number; the 0.18.0 release upgrades from it normally.

## 4. Not verified

* The Updates page in a browser (review dialog, live progress through the
  API restart, policy window editor).
* Email notifications (dev1 has no update recipients configured).
* A source on GitHub, and the token option against a private repository.
* Mode D waiting for a real window (tested with fixed times only).

## 5. Known limitations

* Veyra itself only: modules update from the catalog, OS packages are only
  listed.
* The runner's status directory is readable by the veyra group only, so
  the server's own administrators read it with sudo.
* No "install a specific older version": downgrades stay refused (database
  migrations are not reversible).

## 6. Open items

* **Owner: remove the test key** — `sudo rm /etc/veyra/trust/official/m12-live-test.pub`.
* **Owner: the four questions of [SOFTWARE_UPDATES.md](../SOFTWARE_UPDATES.md) §9**
  (hosting, release key custody, default policy, maintenance window).
* **Owner: browser check** of System → Updates.
* Everything open from earlier milestones.

## 7. Next milestone

The roadmap's next row after 12 (or 11b, the module service runtime, if
community modules are wanted soon).

## 8. Owner decisions

* 2026-10-15: milestone started ("go ahead with M12"); built with the
  proposed defaults while the §9 questions are open.
