# Update Management

Software updates are a core feature of Veyra. This document describes the
policy model, the security model, the upgrade procedure and recovery. It
also states what is implemented today.

## 1. Status

| Capability | Status |
|---|---|
| Update policy data model and API (`/api/v1/updates/policies`) | Implemented (M0) |
| Signed update metadata format and verification (signature, expiry, rollback protection, official key only) | Implemented (M0) |
| Update check (UI "Check now", `veyra updates check`, worker schedule) | Implemented (M0); **no update source is published yet**, so checks report "not configured" |
| Available updates and update history | Implemented (M0) |
| Core upgrade from a source tree: backup → migrate → verify, with rollback if a migration fails (`installer/upgrade.sh`) | Implemented (M0); used for every upgrade since M1 |
| Module update from files on disk (`POST /modules/{id}/update`) | Implemented (M0) |
| Download, approve, apply from the UI; maintenance windows; unattended installation; release signing | Implemented (M12) for Veyra itself: [SOFTWARE_UPDATES.md](SOFTWARE_UPDATES.md) |
| HA-aware coordinated updates | M16 |

## 2. Components and policies

Each component class has its own policy (`update_policies`):

| Component | Default mode | Why |
|---|---|---|
| `veyra_core` | notify | Check daily and tell administrators; install only when approved |
| `modules` | notify | Same |
| `provisioning_templates` | notify | Official templates only; local templates are never touched |
| `telephony_engine` | manual, checks off | Asterisk is maintained through the OS package manager and needs its own maintenance window |
| `operating_system` | manual, checks off | Managed by the administrator (for example `unattended-upgrades` for security updates) |

**Modes:**

* **A. manual:** no automatic checks; the administrator checks and installs.
* **B. notify:** scheduled checks and administrator notification.
* **C. download_approve:** downloads automatically, installs after approval *(M12)*.
* **D. auto_install_window:** installs approved categories (`security`, `bugfix`, `feature`) only inside a maintenance window *(M12)*.

Policy settings: mode, channel, `check_enabled`, `check_interval_hours`,
`auto_download`, `auto_install_categories`, `require_approval`,
`notify_admins`, and `maintenance_window` (`{days, start "HH:MM",
duration_minutes, timezone}`). Validation rules: mode D requires a window;
categories only apply in mode D; manual mode never downloads.

**Defaults are safe:** nothing downloads or installs unattended. Changing a
policy requires the `updates.manage` permission (platform scope) and is
audited with before and after values.

**Channels:** `stable`, `beta`, `development`. A policy sees its own
channel and the more stable ones: stable sees only stable; beta sees beta
and stable; development sees all three. Development releases never reach a
stable installation unless an administrator changes the channel.

## 3. Update metadata and security

The update source publishes `<url>` (JSON) and `<url>.sig` (a detached
Ed25519 signature document, the same format used for modules):

```json
{
  "schema_version": 1,
  "sequence": 42,
  "generated_at": "2026-10-01T00:00:00Z",
  "expires_at": "2026-10-08T00:00:00Z",
  "releases": [{
    "component": "veyra_core", "target": "veyra", "version": "0.2.0",
    "channel": "stable", "category": "feature",
    "release_notes": "…", "service_impact": "API restarts; calls unaffected",
    "min_from_version": "0.1.0",
    "artifact": {"url": "https://…/veyra-0.2.0.tar.gz", "sha256": "…", "size": 123456}
  }]
}
```

Verification (`veyra/updates/metadata.py`) checks all of the following:

* **Authenticity:** signed by a key in `/etc/veyra/trust/official/` (community and third-party keys are rejected for update metadata).
* **Freshness:** `expires_at` is in the future, which blocks freeze attacks that serve old metadata forever.
* **Rollback protection:** `sequence` is not lower than the last accepted sequence (stored in `system_settings`).
* **HTTPS only.** `file://` is allowed outside production for testing. The size is capped at 2 MB.
* **Artifacts** are verified against `sha256` and `size` from signed metadata before use, and packages are verified again by their own signatures (modules: SHA256SUMS + SIGNATURE).
* **No update scripts from the source are executed.** Upgrades run Veyra's own versioned procedure with verified artifacts.

No official release key or update server exists yet. Publishing one is part
of release engineering (M12/M23).

## 4. Upgrade process

The full process (M12) follows these steps. Steps marked ✔ are already in
`upgrade.sh` or the checker.

1. ✔ Check for available updates (signed metadata).
2. ✔ Validate package authenticity (signature, checksum).
3. Check compatibility (`min_from_version`, module API ranges for installed modules).
4. Check module dependencies.
5. ✔ Check available disk space (2× database size + 2 GB).
6. ✔ Create backups: `pg_dump -Fc` and a tarball of `/etc/veyra`, in `/var/backups/veyra` (0600).
7. ✔ Validate migration requirements. Alembic runs all pending migrations in **one transaction**.
8. ✔ Display the expected service impact: the API and web interface restart; Asterisk is not restarted, so calls continue.
9. ✔ Obtain approval (interactive confirmation or `--yes`; UI approval in M12).
10. ✔ Apply: build the new release beside the current one in `/opt/veyra/releases/<version>-<rev>` and switch the `current` symlink atomically.
11. ✔ Run migrations.
12. ✔ Restart only the necessary services (`veyra-api`, `veyra-worker`, NGINX reload).
13. ✔ Verify application health (`verify.sh`).
14. Verify module health (M12, via `/system/health`).
15. ✔ Verify telephony engine health (ARI check in `verify.sh`).
16. ✔ Record the result in `update_history` and the audit log (`veyra updates record`).
17. Notify administrators (M12, with email in M7).

## 5. Failure handling and recovery

* **Failure before migration:** the previous release stays active, and nothing has changed.
* **Migration failure:** the migration transaction rolls back, `upgrade.sh` switches `current` back to the previous release and restarts it, and the database is unchanged.
* **Failure after migration** (the new release fails verification): the schema has changed, so the old code may not run against it. Veyra does **not** assume migrations can be reversed. The script prints:
  * forward recovery: fix the cause and re-run `upgrade.sh` (preferred), or
  * full restore from the backup taken in step 6, which loses changes made since then:
    ```
    sudo systemctl stop veyra-api veyra-worker
    sudo runuser -u postgres -- pg_restore --clean --if-exists -d veyra /var/backups/veyra/veyra-db-<ver>-<ts>.dump
    sudo ln -sfn <previous release dir> /opt/veyra/current
    sudo systemctl start veyra-api veyra-worker
    ```
* User data is never deleted by an upgrade. Old releases are pruned (three kept by default), and backups are never pruned automatically.

## 6. Module and template updates

* Modules update independently when their `core_api` range allows. The manager runs only that module's migrations and records the new version. A restart is required for new code, and this is reported as `restart_required`.
* Module release notes, dependencies and compatibility are shown before an update (M11/M12).
* Official templates are replaced as a set. Local templates are never overwritten. Local templates whose parent changed are flagged for review. Optional three-way comparison and merge assistance is planned for M9/M12.

## 7. Telephony engine and operating system updates

These have separate policies because they carry different risks. Upgrading
Asterisk restarts it, which drops calls in progress. Veyra will show
available package updates (M12) and can schedule them in a maintenance
window, but never applies them by default. On HA pairs, the secondary is
updated first.

## 8. HA-aware updates (M16)

Update the secondary, then switch over (planned, audited), then update the
former primary. Both nodes are never updated at the same time
([HIGH_AVAILABILITY.md](HIGH_AVAILABILITY.md) §12):

1. On the primary's Updates page, *Install <version> on the standby*
   (`POST /ha/standby-upgrade`): the standby starts its own
   `veyra-upgrade@<version>` with the artifact the file sync already
   brought it, verifies it there, and skips migrations (a replica cannot
   write). The HA page shows the standby's version change.
2. *Switch over* to the standby: the promotion step runs the migrations on
   the new primary before the configuration is deployed.
3. The old primary, now the standby, runs older code against the newer
   schema for the minutes until *Install on <old primary>*; only its HA
   page and read-only status are used in that window.
4. Optionally switch back.

Rolling updates will not be described as safe until the HA test plan
includes them and they pass (stage 2, HA_ARCHITECTURE.md §10).
