# Software Update Management (Milestone 12)

Design for Milestone 12 (roadmap row 12, 0.18.0): download, approve and
apply Veyra updates from the interface, maintenance windows, and release
signing. It completes [UPDATE_MANAGEMENT.md](UPDATE_MANAGEMENT.md), which
already defines the policies, the signed update metadata (expiry, sequence,
official key only) and `upgrade.sh` (backups, migrations in one
transaction, verify, recovery).

Today an administrator updates by fetching the new source on the server
and running `sudo installer/upgrade.sh`. After this milestone the same
upgrade runs from System → Updates, after a signed download and an
approval, optionally by itself inside a maintenance window.

## 1. Releases

### 1.1 The artifact

A release is one file, `veyra-<version>.tar.gz`: the source tree as the
installer needs it (backend, installer, modules, provisioning, docs,
companion) **with the prebuilt web interface and Companion extension**
(`frontend/out`, `companion/dist`), so servers never need Node.js. It is
exactly what `~/veyra-release` holds today.

```
veyra release build  --out dist/          # from a clean checkout of the release commit
veyra release add    dist/veyra-0.18.0.tar.gz --url <where it will be downloaded> \
                     --metadata updates/stable.json --channel stable --category feature \
                     --notes "…" --impact "API restarts; calls unaffected"
veyra release sign   updates/stable.json --key-file official.key --key-id veyra-official
```

`release build` refuses a dirty tree and records the commit; `release add`
computes size and SHA-256 and increases the metadata `sequence` and
`expires_at` (default 30 days; a later `release refresh` re-signs to extend
it without a release).

### 1.2 Where releases live (decided 2026-10-18)

The `manderson20/veyra` repository is public, so releases live in it:

* **Tarballs** are assets of the GitHub release for the tag
  (`https://github.com/manderson20/veyra/releases/download/v<version>/veyra-<version>.tar.gz`).
  GitHub redirects the download to a signed address; the downloader follows
  it as long as it stays on HTTPS and then checks size and SHA-256.
* **Metadata** is the orphan branch `updates` of the same repository:
  `stable.json` and `stable.json.sig`, served as
  `https://raw.githubusercontent.com/manderson20/veyra/updates/stable.json`
  (and `.sig`). The branch holds only the feed and a README. A repository
  ruleset blocks deletion and force-pushes; only an administrator updates it.
* **Servers** get the address from `VEYRA_UPDATE_METADATA_URL` in
  `veyra.env`, which the installer now writes by default (the interface's
  System → Updates → Source still overrides it), and the public half of
  the release key from `installer/trust/official/veyra-official.pub`, which
  the installer copies to `/etc/veyra/trust/official/` on every install and
  upgrade. `verify.sh` reports both (`release-key`, `update-source`).

Publishing a release (after the tag and the GitHub release exist; the
private key stays with the owner, outside the repository):

```
veyra release build --source ~/veyra-release --out ~/.veyra-release/dist
gh release upload v<version> ~/.veyra-release/dist/veyra-<version>.tar.gz
veyra release add ~/.veyra-release/dist/veyra-<version>.tar.gz \
    --url https://github.com/manderson20/veyra/releases/download/v<version>/veyra-<version>.tar.gz \
    --metadata stable.json --channel stable --category <security|bugfix|feature> \
    --notes "…" --impact "The web interface and API restart (under a minute); calls are not interrupted." \
    --expires-days 90
veyra release sign stable.json --key-file ~/.veyra-release/veyra-official.key --key-id veyra-official
# commit stable.json and stable.json.sig on the `updates` branch and push
```

The metadata expires 90 days after the last `add` or `refresh`; a quiet
quarter needs `veyra release refresh` + `sign` + push before then, or every
server reports the feed as rejected.

A release that can only be installed from a given version onwards (because
an intermediate release performed a one-off step outside the migration
chain) is added with `--min-from <version>`: the server shows the
requirement, refuses approval below it and the runner refuses again (§3.3).
Ordinary releases need no `--min-from`: migrations chain, and `upgrade.sh`
takes a server from any earlier version in one step, so skipping releases
is safe and the skipped ones are then marked superseded (§2).

### 1.3 Trust

Update metadata is accepted only when signed by a key in
`/etc/veyra/trust/official/` (unchanged). The owner keeps that key; the
module catalog key (M11) is separate. Downloads are HTTPS only and must
match the signed size and SHA-256 before they are kept.

## 2. Download

* **Update source** (System → Updates → Source): the metadata URL and the
  optional token (§1.2). The worker checks per the core policy (default
  daily, mode *notify*).
* **Download** happens when an administrator clicks *Download*, or by
  itself in modes *download_approve* and *auto_install_window*. The
  artifact goes to `<data>/updates/<version>/` (veyra-owned) with the signed
  metadata entry beside it; the list shows *available → downloaded →
  approved → installing → installed / failed*.
* Only one core version is kept downloaded at a time (the newest
  compatible); older downloads are removed.
* The list shows Veyra's releases newest first. A release that is not newer
  than the installed version (one skipped by installing a later release, or
  a failed attempt at an older one) becomes *superseded* after the next check
  or a successful installation and leaves the list; its download is removed.
  Releases that must be installed from a given version onwards say so with
  `min_from_version` (§3.3), which blocks approval and the runner alike.

## 3. Approve and apply

### 3.1 Approval

An administrator with `updates.manage` reviews the release notes, the
service impact and the checks (§3.3) and clicks **Install now** or
**Install in the next maintenance window**. Both are audited. *Install
now* starts the root unit from the API in the same request (0.25.4: the
API runs as the service account the polkit rule allows, like the worker),
so the installer begins within a second or two; window approvals, and a
"now" approval the API could not start, are started by the worker's
housekeeping pass (every 60 s).

**From the console** (owner request 2026-10-20): `sudo veyra updates
install [VERSION] [--no-check] [--no-wait] [--timeout S]` checks the feed,
downloads and verifies the newest offered release (or `VERSION`), approves
it for "now" and starts the same root unit, then prints the installer's
steps until the new worker has recorded the result. It goes through the
same rows and checks as the web interface, so System → Updates shows the
progress and the history; the approval is audited `updates.approve` by
`cli (<sudo user>)` with `via: cli`. No password or second factor is asked
(root on the server is already required); the web interface keeps its
re-authentication.

### 3.2 The privileged step

The API and worker run without privileges; installing needs root. The
installer adds:

* `veyra-upgrade@.service`: a oneshot **root** unit; the instance is the
  version (`veyra-upgrade@0.18.0.service`), and it runs
  `veyra updates run <version>` from the installed release (root-owned).
* A polkit rule (added to M11's) letting the `veyra` account **start**
  `veyra-upgrade@*.service` and nothing else.

The runner (`veyra.updates.runner`, root):

1. reads `<data>/updates/<version>/` but **trusts none of it blindly**:
   it re-verifies the stored metadata against the official keys in
   `/etc/veyra/trust/official/` (root-owned), checks the version is the one
   asked for and newer than the installed one, and checks the artifact's
   SHA-256 and size;
2. copies the artifact into a root-only directory
   (`/var/lib/veyra-upgrade/work/<version>`, 0700), checks size and SHA-256
   on that copy (so the service account cannot change it between the check
   and the run; files are opened without following links), and unpacks it
   refusing absolute paths, `..`, links leaving the tree and special files;
   the unpacked version must equal the signed one;
3. runs **that release's own** `installer/upgrade.sh --yes`, exactly as an
   administrator does today (backups, migrations, verify, recovery on
   failure, `veyra updates record`);
4. writes progress to `/var/lib/veyra-upgrade/status.json` (root-owned,
   0640 group veyra: step, time, outcome, last 40 lines; the full log is
   `/var/log/veyra/upgrade-run-<version>-<time>.log`) and records a failure in
   the update history (`upgrade.sh` records successes).

A compromised service account can therefore only start an upgrade to a
release the official key signed, never run its own code as root.

### 3.3 Checks before approval

Shown on the update and enforced again by the runner: `min_from_version`,
disk space (2× database + 2 GB), installed modules' `core_api` against the
new release's module API, a backup directory with space, and whether
another upgrade is running.

### 3.4 During and after

The Updates page follows the installation from the approval on as a
timeline: it polls `GET /updates/status` every 3 seconds (and the update
list every 5). The endpoint returns the runner's status file (`run`) and,
while an installation is approved or starting, `pending` with the stage
before the installer prints anything (`manager.install_progress`):
`queued` (approved for "now" but not started by the API, waiting for the
worker's next housekeeping pass; the worker's last heartbeat and its 60 s
interval say how long),
`window` (approved for the maintenance window, with the next window),
`starting` (pre-checks done, root unit started, release being verified and
unpacked), `running` (installer step and output) and `finishing` (the new
worker records the result). The page shows these as stages — approved,
picked up by the worker, release verified and unpacked, installer running
(current step), finished — with the time since the approval and the
installer output scrolled to the newest line; while the API restarts the requests fail and the page says
"Veyra is restarting" and keeps polling. A status file left by an earlier
run (another version, or finished before this approval) is not shown as
this installation's progress. Since 0.26.2 "Install now" keeps the review
dialog open on this same progress and ends it with a *Reload the page*
button; closing the dialog leaves the callout on the page, and opening the
release again while it installs shows the progress. The page doing the
watching belongs to the version being replaced, so a change to this view is
seen one release later (0.25.2). The new worker finishes the update's state
from the status file and sends the email.
History records the outcome and the log; failures keep the previous
release running (or print the recovery steps when the database was
already migrated, as today).

## 4. Maintenance windows

Policy mode **D (auto_install_window)** with a window (`days`, `start`,
`duration_minutes`, `timezone`) and categories (`security`, `bugfix`,
`feature`). The worker starts an approved or auto-approved upgrade only
when the window is open **and** no call is in progress (the same idle rule
as "deploy when idle"); it does not start one in the last 15 minutes of the
window. Outside a window nothing installs by itself.

## 5. Notifications

Email (SMTP settings of M7) to the update recipients: *update available*,
*downloaded*, *installed*, *failed* (with the log tail). Recipients are a
list on the core policy; the dashboard's Updates item shows the same.

## 6. Operating system and Asterisk packages

Shown, not applied: the worker reads `apt list --upgradable` (no
privileges needed) daily and the Updates page lists the count, security
updates first, Asterisk separately ("upgrading Asterisk restarts it and
drops calls"). Applying them stays with the administrator
(`unattended-upgrades` or `apt`).

## 7. API

```
GET/PUT  /updates/source                         metadata URL, token (write-only), email recipients
GET      /updates/available/{id}                 notes, impact, size, checks, window
POST     /updates/available/{id}/download        download and verify
POST     /updates/available/{id}/approve         {when: "now" | "window"}
POST     /updates/available/{id}/cancel          withdraw an approval before it starts
GET      /updates/status                         installed version and the runner's status.json
GET      /updates/system-packages                apt summary
```

The update source in the interface overrides `VEYRA_UPDATE_METADATA_URL`
of veyra.env; the token is encrypted with the installation key (purpose
`updates:source-token`), sent as `Authorization: Bearer` only to the source
itself (not to redirect targets), and never returned.

## 8. Installer

`veyra-upgrade@.service`, the polkit rule extended (start of
`veyra-upgrade@<version>.service` only), `<data>/updates` (0750 veyra) and
`/var/lib/veyra-upgrade` (0750 root:veyra; its `work/` 0700). Release
archives carry a `REVISION` file that install.sh and upgrade.sh use when
there is no git checkout. `verify.sh`: `upgrade-unit`. uninstall.sh removes
the unit and the polkit rule.

## 9. Owner decisions (answered 2026-10-18)

1. **Hosting**: the public `manderson20/veyra` repository itself: tarballs
   as release assets, the feed on the `updates` branch (§1.2).
2. **Release key**: `veyra-official`, an Ed25519 key generated on dev1 in
   the owner's home directory (`~/.veyra-release/veyra-official.key`, mode
   0600) and never committed; the owner may move it to an offline place.
   Its public half ships with the installer.
3. **Default policy**: notify only (unchanged).
4. **Maintenance window**: none yet; installs are approved from the interface.

## 10. Testing

Unit: release build contents (prebuilt files present, `.git` and
`node_modules` absent), metadata add/sign/refresh (sequence, expiry),
download with checksum and size checks and the token header, state
transitions, approval rules, window and idle rules, the runner's
verification (wrong signature, older version, changed artifact after
download, path tricks in the tarball), status file parsing, apt output
parsing. Live on dev1: a local update source (loopback) offering a release
built from this branch; download, approve, the root runner upgrading dev1
from the interface, history and email; a refused tampered artifact.

## 11. Decisions

* 2026-10-18: the repository became public and the first feed was published (0.24.1) as decided in §9; the installer ships the official public key and the feed address so every server verifies and finds updates without manual setup (§1.2).
* 2026-10-15: milestone started on the owner's "go ahead with M12"; built
  with the proposed defaults of §9 while the questions are open (both
  hosting options work; no keys are created for the owner: Veyra accepts
  releases only once the official public key is in
  `/etc/veyra/trust/official/`).
* Status during the restart: polled through the API (which may be briefly
  unreachable) instead of an unauthenticated NGINX file, since the log tail
  can contain server details.
* Policies: download and window modes apply to Veyra itself only; modules
  keep updating from the module catalog (notify only).
