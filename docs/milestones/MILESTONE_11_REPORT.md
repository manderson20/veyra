# Milestone 11 Report — Module Catalog and Module Management

Branch `milestone-11` (from `main` at 0.16.0). Design:
[MODULE_CATALOG.md](../MODULE_CATALOG.md). Status: **approved 2026-10-15, released as 0.17.0.**

## 1. Scope (roadmap row 11; owner request of 2026-10-14)

A free online module catalog on GitHub (a signed index plus packages as
release assets) from which Veyra lists, installs, updates and uninstalls;
upload of custom modules from the interface; module settings; independent
module updates.

## 2. Results

* **Catalogs**: signed `index.json` files; Veyra accepts one only when its
  signature verifies against a key in `/etc/veyra/trust/catalog/` (none is
  created for the owner). Sources are checked once a day and on demand; the
  last verified index is kept, so the catalog works offline.
* **Install and update** from a catalog (Module Manager → Catalog): the
  download must match the index's size and SHA-256, and the package must
  carry a valid publisher signature, whose trust directory decides the
  trust level (the index cannot raise it). Modules go into
  `<data>/module-store`, searched before the release's own modules, so a
  catalog update can replace a bundled module.
* **Upload** of `.vmod` packages with the same checks.
* **Rollback** to the kept previous version, refused when the newer version
  changed the module's database.
* **Settings** generated from each module's `[[config]]` fields; secrets
  stored encrypted for the module and decrypted by `ctx.get_config`.
* **Restart Veyra services** from the interface: a polkit rule lets the
  service account restart Veyra's five units only; the worker carries out
  the request. Asterisk and calls are not affected.
* **Publishing**: `veyra catalog add` (computes size and checksum from the
  package, validates the index), `veyra catalog sign`, `veyra catalog
  verify` (local file or URL).
* Uninstall with "delete data" also removes the store copies.
* Migration `0024`.

## 3. Testing (final tree, 2026-10-15)

| Suite | Result |
|---|---|
| Backend ruff / mypy | Clean / no issues (164 files) |
| Backend pytest | **367 passed** (incl. the dependency check and the unloadable-module refusal added after the owner's report); before that, **365 passed** (M11 added 5 test functions with a real signed catalog served on loopback: signature and tampering, HTTPS rule, install, update, rollback and the migration guard, upload, refusal of older versions, settings validation, purge removing store copies, checksum mismatch, a source without a trusted key, the restart request committed before systemctl and marked done by the next worker, and `catalog add` checksums) |
| `alembic check` | No drift (migration `0024`) |
| Frontend lint / typecheck / vitest / build | Clean / clean / **39 passed** / passed |
| Installer library tests | **46 passed** |
| **Owner's `upgrade.sh` on dev1** | 0.16.0-b6934fec2a → 0.16.0-88ee843ff9 (04:36 UTC: schema `0024`, module store, polkit rule; `catalog-trust` warned as expected) → **0.16.0-45ec4dea45** (04:44 UTC, the restart fix) |

### Live checks on dev1 (2026-10-15 04:37-04:50 UTC)

| Check | Result |
|---|---|
| Publishing | Temporary catalog and publisher keys; AND Clock Messages re-signed as 0.1.1 and 0.1.2; `veyra catalog add` ×2, `sign`, `verify` ("Valid, signed by m11-live-catalog") |
| Source | Catalog served on 127.0.0.1: accepted, "1 module, signed by m11-live-catalog" |
| Install, update | 0.1.1 installed and enabled from the catalog (trust official from the publisher key); updated to 0.1.2, `restart_required` |
| Restart | All five Veyra units restarted through the polkit rule; Asterisk untouched |
| **Bug found** | The restart request was removed in the same transaction as the `systemctl` call; systemd stopped the worker (one of the units) before it committed, so every new worker restarted everything again: a **restart loop**, stopped after about 20 seconds by deleting the request. Fixed (45ec4de): the request is committed away before the restart starts; tested from a second session. After the upgrade: one restart, stable for 75 seconds |
| Rollback | Back to 0.1.1; 0.1.2 kept in `versions/` |
| Cleanup | Module disabled and uninstalled with its data, store emptied, source deleted, test keys, local server and helper files removed; services restarted once (stable) |

### Owner's report after the live check (2026-10-15 04:55 UTC)

Installing **AND Clock Messages** from Module Manager failed with an error
500: `ModuleNotFoundError: No module named 'httpx'`. The module's clock
delivery uses `httpx`, which was in `requirements-dev.txt` only, so tests
and the live check (which put `httpx` on a temporary path for its test
client) passed while production lacked it. Fixed before the release:
`httpx==0.28.1` is a runtime dependency; `test_module_dependencies.py`
fails when a bundled module imports a library that is not in
`requirements.txt` (checked to catch exactly this import); and a module
whose code cannot load is now refused with a 409 naming the error, without
leaving anything half-installed.

## 4. Not verified

* A catalog on GitHub (the repository does not exist yet; the live check
  used a local server, which the HTTPS rule allows only on loopback).
* The new Module Manager pages in a browser.

## 5. Known limitations

* Community and third-party modules are listed but cannot be installed:
  they need the isolated service runtime (proposed row 11b).
* Updates are never automatic; the catalog only notifies.
* The store keeps one previous version per module.

## 6. Open items

* **Owner: the four questions of [MODULE_CATALOG.md](../MODULE_CATALOG.md) §9**
  (repository, key custody, community modules soon, automatic updates).
* **Owner: to publish the first catalog**: create the repository, generate
  the catalog and official keys (`veyra modules keygen`), place the public
  halves in `/etc/veyra/trust/catalog/` and `/etc/veyra/trust/official/`,
  then `veyra modules sign`, `veyra catalog add`, `veyra catalog sign` and
  upload; add the source in Module Manager → Sources.
* **Owner: browser check** of Module Manager → Catalog, Upload, Sources and a
  module's Settings.
* Everything open from earlier milestones.

## 7. Next milestone

Milestone 12 — software update management (0.18.0), or the service runtime
(row 11b) first if the owner wants community modules soon.

## 8. Owner decisions

* 2026-10-15: milestone started ("go ahead with M11"); built with the
  proposed defaults while the §9 questions are open.
* 2026-10-15: approved ("M11 approved, go ahead with 0.17.0"), together
  with the report that installing the AND module failed; the fix is part of
  0.17.0.
