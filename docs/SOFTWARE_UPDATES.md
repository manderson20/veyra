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

### 1.2 Where releases live (open question §9)

The `manderson20/veyra` repository is **private**, so anonymous servers
cannot download from it. Two options, both supported:

* **A public releases repository** (proposed `manderson20/veyra-releases`)
  holding `stable.json`, `stable.json.sig` and the tarballs as GitHub
  release assets. Simple for every server; the release tarballs are then
  public (the code is AGPL-licensed and meant to be published at M18).
* **The private repository with a token**: the update source stores a
  read-only GitHub token (fine-grained, contents read) encrypted with the
  installation key and sends it with every request.

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

## 3. Approve and apply

### 3.1 Approval

An administrator with `updates.manage` reviews the release notes, the
service impact and the checks (§3.3) and clicks **Install now** or
**Install in the next maintenance window**. Both are audited.

### 3.2 The privileged step

The API and worker run without privileges; installing needs root. The
installer adds:

* `veyra-upgrade@.service`: a oneshot **root** unit; the instance is the
  version (`veyra-upgrade@0.18.0.service`), and it runs
  `/usr/local/sbin/veyra-upgrade-run <version>`.
* A polkit rule (added to M11's) letting the `veyra` account **start**
  `veyra-upgrade@*.service` and nothing else.

`veyra-upgrade-run` (root):

1. reads `<data>/updates/<version>/` but **trusts none of it blindly**:
   it re-verifies the stored metadata against the official keys in
   `/etc/veyra/trust/official/` (root-owned), checks the version is the one
   asked for and newer than the installed one, and checks the artifact's
   SHA-256 and size;
2. copies and unpacks the artifact into a root-only directory
   (`/var/lib/veyra-upgrade/<version>`, 0700), so the service account cannot
   change it between the check and the run;
3. runs **that release's own** `installer/upgrade.sh --yes`, exactly as an
   administrator does today (backups, migrations, verify, recovery on
   failure, `veyra updates record`);
4. writes progress to `<data>/updates/status.json` (step, time, outcome,
   log tail) so the interface can show it while the API restarts.

A compromised service account can therefore only start an upgrade to a
release the official key signed, never run its own code as root.

### 3.3 Checks before approval

Shown on the update and enforced again by the runner: `min_from_version`,
disk space (2× database + 2 GB), installed modules' `core_api` against the
new release's module API, a backup directory with space, and whether
another upgrade is running.

### 3.4 During and after

The interface shows the progress page; the API restarts during the
upgrade, so the page polls `status.json` through a small read-only
endpoint that answers from the file and reconnects when the new API is up.
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
GET/PUT  /updates/source                      metadata URL, token (write-only), last result
POST     /updates/{id}/download
POST     /updates/{id}/approve                 {when: "now" | "window"}
POST     /updates/{id}/cancel                  (before it starts)
GET      /updates/status                       status.json (works while the API restarts: served by NGINX from the file)
GET      /updates/system-packages              apt summary
```

## 8. Installer

`veyra-upgrade@.service`, `/usr/local/sbin/veyra-upgrade-run`, the polkit
rule extended, `<data>/updates` (0750 veyra) and `/var/lib/veyra-upgrade`
(0700 root); NGINX serves `status.json` read-only at
`/api/v1/updates/status` so it answers during the API restart. `verify.sh`:
`upgrade-unit`, `update-source` (configured or not).

## 9. Open questions for the owner

1. **Hosting**: a public `manderson20/veyra-releases` repository (simplest),
   or the private repository with a read-only token on each server?
2. **Release key**: the official key that signs releases (and modules)
   stays offline with you? (Proposed; `veyra release sign` runs on your
   machine.)
3. **Default policy**: notify only (proposed), or download automatically
   and wait for approval?
4. **Maintenance window**: if you want unattended installs, which days and
   hours (for example Saturday 02:00-04:00)?

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

* 2026-10-15: milestone started on the owner's "go ahead with M12".
