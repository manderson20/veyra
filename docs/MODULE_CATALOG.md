# Module Catalog and Module Management (Milestone 11)

Design for Milestone 11 (roadmap row 11, 0.17.0). Owner request of
2026-10-14: "a free online module catalog hosted on GitHub (an index file
plus packages as GitHub release assets, signed; Veyra lists, installs,
updates and uninstalls from it), and upload of custom modules from the
interface". The roadmap row adds module settings and independent module
updates.

## 1. What exists

* Modules are directories with `module.toml`, `SHA256SUMS` and an Ed25519
  `SIGNATURE`; `.vmod` packages are signed tar.gz archives with safe
  extraction ([MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) §6).
* The manager discovers modules in `VEYRA_MODULE_PATHS` (the release's
  `modules/` and `<data>/modules`), and installs, enables, disables,
  uninstalls and updates them; signatures are checked at install, enable
  and every start; the trust level comes from the directory of the key in
  `/etc/veyra/trust/{official,community,third_party}`.
* Modules run **in the core process** with database access; only
  `official` modules may do so. Community and third-party modules need the
  planned *service runtime*.
* Manifests declare `[[config]]` fields, stored in `module_configs`, but no
  interface edits them.
* A newer version takes effect only after the services restart, which an
  administrator must do on the server.

## 2. The catalog

### 2.1 Layout on GitHub

A public repository, proposed **`manderson20/veyra-modules`**:

```
catalog/index.json         the catalog (§2.2)
catalog/index.json.sig     Ed25519 signature of index.json (catalog key)
modules/<id>/...           sources (optional; the catalog only needs packages)
```

Packages (`<id>-<version>.vmod`) are **assets of GitHub releases** of that
repository; the index points at them by URL with their SHA-256. A small
GitHub Action can build, sign and publish (§2.4), or the owner publishes by
hand with the `veyra modules` commands.

### 2.2 `index.json`

```json
{
  "catalog_version": 1,
  "name": "Veyra modules",
  "generated_at": "2026-10-20T12:00:00Z",
  "modules": [
    {
      "id": "veyra.and-clocks",
      "name": "AND Clock Messages",
      "summary": "Messages to Advanced Network Devices clocks and signs.",
      "publisher": "Veyra",
      "homepage": "https://github.com/manderson20/veyra-modules/tree/main/modules/veyra-and-clocks",
      "versions": [
        {
          "version": "1.1.0",
          "core_api": ">=1.1.0 <2.0.0",
          "url": "https://github.com/manderson20/veyra-modules/releases/download/veyra.and-clocks-1.1.0/veyra.and-clocks-1.1.0.vmod",
          "sha256": "…",
          "size": 48213,
          "released": "2026-10-20",
          "notes": "Editing of clocks; message templates."
        }
      ]
    }
  ]
}
```

### 2.3 Trust: two separate signatures

* **The index** is signed with the **catalog key**. Veyra accepts an index
  only when `index.json.sig` verifies against a key in
  `/etc/veyra/trust/catalog/` (the installer ships the Veyra catalog key's
  public half). A tampered index (wrong URLs or checksums) is refused.
* **Each package** is signed by its **publisher key**, exactly as today;
  the trust directory of that key decides official / community /
  third-party. The index cannot raise a package's trust.
* Downloads are HTTPS only, at most 200 MB, and must match the index's
  SHA-256 before the package is even opened.

### 2.4 Publishing (owner's side)

```
veyra modules sign ./veyra-and-clocks --key-file official.key --key-id veyra-official --package dist/
veyra catalog add dist/veyra.and-clocks-1.1.0.vmod --url <release asset URL> --index catalog/index.json
veyra catalog sign catalog/index.json --key-file catalog.key --key-id <key id>
```

`veyra catalog add` reads the package's manifest and computes the size and
SHA-256, so the index cannot drift from the package. The **keys stay with
the owner**, offline or as GitHub Action secrets (open question §9).

## 3. Using the catalog in Veyra

* **Catalog sources** (Module Manager → Sources): a list of index URLs; the
  dialog suggests the Veyra catalog's address, but nothing is added until an
  administrator does (and a catalog is used only once its key is trusted).
  Each source is fetched by the worker once a day and on demand, verified,
  and cached in the database (so the page works offline).
* **Modules → Catalog**: every module with its latest compatible version,
  publisher, trust level (once downloaded: from its signature), what it
  needs (core API, dependencies) and release notes; *Install* or *Update*.
  Incompatible versions are listed with the reason.
* **Install** downloads the package into `<data>/module-store/<id>/<version>/`
  (a new entry in `VEYRA_MODULE_PATHS`; the store keeps the current and the
  previous version), verifies it as above, then runs the existing install
  (migrations, permissions) and, if asked, enable.
* **Upload** (Modules → Upload): a `.vmod` from the administrator's
  computer, with the same checks. Unsigned uploads are refused in
  production, as today.
* **Uninstall** works as today (data kept, or purged after typing the id);
  the store directory is removed with *purge*.

Only platform administrators (`modules.manage`) do any of this; every step
is audited with the version, URL and checksum.

## 4. Module updates and restarts

* The daily catalog refresh marks installed modules with a newer
  compatible version; the dashboard's "Updates" item and the Module Manager
  show them.
* **Update** downloads and verifies the new version next to the current one,
  runs its migrations, and switches the active version. New code needs the
  services to restart.
* **Restart from the interface.** The installer adds a polkit rule that lets
  the `veyra` account restart **only** Veyra's own units
  (`veyra-api`, `veyra-worker`, `veyra-deployer`, `veyra-pager`,
  `veyra-firewall`); the worker performs the restart when an administrator
  confirms "Restart Veyra services now" (the web interface reconnects; calls
  are not affected: Asterisk is not restarted). The same button appears after
  enabling or disabling a module.
* **Rollback**: the previous version stays in the store; "Roll back" switches
  to it when its migrations allow (a module whose migration is not
  reversible says so and cannot be rolled back).
* Policy: modules are **never updated automatically**; the catalog only
  notifies (an option for "automatic for official modules" can come later).

## 5. Module settings

A **Settings** tab on each module's page, generated from its `[[config]]`
fields (string, integer, boolean, choice, secret), installation-wide or per
organization as the field says; secrets are encrypted with the installation
key and never shown again; saved to `module_configs`; the module reads them
with `ctx.get_config` (exists). Validation from the manifest (required,
min/max, length, choices).

## 6. Not in this milestone: the service runtime

Running community and third-party modules out of process (their own systemd
service and account, no database access, a token-scoped API) changes the
module API itself: today's modules use the database directly. It deserves
its own milestone (**proposed row 11b**). Until then the catalog lists such
modules with "needs the service runtime (planned)" and does not install
them; official modules (the owner's own) work fully.

## 7. API

```
GET/POST/DELETE /modules/catalog-sources[/{id}]
POST /modules/catalog/refresh
GET  /modules/catalog                     modules, versions, compatibility, installed state
POST /modules/catalog/install             {module_id, version, enable}
POST /modules/upload                      multipart .vmod
POST /modules/{id}/update                 {version}
POST /modules/{id}/rollback
GET/PUT /modules/{id}/config              (?organization_id=)
POST /modules/restart-services            (modules.manage; the worker restarts the units)
```

## 8. Installer

* `/etc/veyra/trust/catalog/` with the Veyra catalog public key;
  `<data>/module-store` (0750 veyra); `VEYRA_MODULE_PATHS` gains it.
* The polkit rule `/etc/polkit-1/rules.d/50-veyra-services.rules` (restart
  of the five Veyra units by `veyra` only).
* `verify.sh`: `catalog-trust` (a catalog key is present), `module-store`,
  `services-restart` (polkit rule present).

## 9. Open questions for the owner

1. **Repository**: `manderson20/veyra-modules` for the catalog and packages?
2. **Keys**: keep the catalog and official signing keys offline on your
   machine (you run `veyra catalog sign` when publishing), or as GitHub
   Action secrets (publishing on a tag push, but the keys live on GitHub)?
3. **Community modules**: do you expect other people's modules soon (then
   row 11b, the service runtime, should follow directly), or only your own
   for now?
4. **Updates**: notify only (proposed), or automatic for official modules?

## 10. Testing

Unit: index parsing and signature (good, tampered index, unknown key),
compatibility filtering, download with checksum mismatch and size limits
(local HTTP fixture), store layout and current/previous switching, upload
validation, update and rollback with migrations, config validation and
secret handling, the restart request. Live on dev1: a local catalog (a
directory served on loopback) with the AND clocks module as a new version,
installed, updated, rolled back; services restarted from the interface.

## 11. Decisions

* 2026-10-15: milestone started on the owner's "go ahead with M11"; built
  with the proposed defaults of §9 while the questions are open (no keys are
  created for the owner: Veyra uses a catalog only after its public key is
  placed in `/etc/veyra/trust/catalog/`).
