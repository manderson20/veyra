# Module Development

Veyra is extended with **modules**: independently versioned packages that
add API endpoints, database tables, permissions, configuration, event
handlers and UI views without modifying the core.

The reference module is [`modules/veyra-example-notes`](../modules/veyra-example-notes/).
Copy it to start a new module.

## 1. Layout

```
my-module/
  module.toml            manifest (required)
  backend/               Python package named by runtime.entrypoint
    __init__.py          defines the entrypoint object
  migrations/            optional Alembic scripts (env.py is two lines; see below)
    env.py
    versions/0001_*.py
  README.md
  SHA256SUMS, SIGNATURE  written by `veyra modules sign` (do not edit)
```

## 2. Manifest specification (`module.toml`, manifest_version 1)

Validate a manifest with `veyra modules validate <dir>`. Print the full JSON
Schema with `veyra modules schema`. Unknown keys are rejected.

```toml
manifest_version = 1
health_check = true                     # module registers health checks

[module]
id = "acme.paging-bridge"               # lower-case, dot/dash segments, ≥ 2 segments, globally unique
name = "Paging Bridge"
description = "…"
version = "1.2.0"                       # semantic version
author = "Acme Inc."
license = "Apache-2.0"                  # SPDX expression
homepage = "https://…"                  # optional

[compatibility]
core_api = ">=1.0.0 <2.0.0"             # range of the Veyra module API (MODULE_API_VERSION)
engines = ["asterisk"]                  # empty = engine independent

[runtime]
type = "in_process"                     # official modules only; others: "service" (planned)
entrypoint = "backend:module"           # <package>[.<submodule>]:<object>

[[dependencies]]
id = "veyra.extensions"
version = "^1.0.0"
optional = false

[[permissions]]                         # must start with "<last id segment>." ("paging_bridge.")
key = "paging_bridge.read"
description = "View paging bridges"
default_roles = ["org_admin", "read_only"]   # system roles that receive it

[[config]]                              # rendered as a settings form by the core UI
key = "max_zones"
label = "Maximum zones"
type = "integer"                        # string | integer | boolean | choice | secret
default = 16
min = 1
max = 256
scope = "installation"                  # or "organization"

[database]
migrations = "migrations"               # Alembic script directory inside the module
table_prefix = "mod_paging_bridge_"     # every table must start with this

[api]
prefix = "paging-bridge"                # mounted at /api/v1/ext/paging-bridge

[events]
subscribes = ["organization.*"]         # patterns the module may subscribe to
publishes = ["paging_bridge.*"]         # must start with the permission namespace

[[ui.nav]]
label = "Paging"
view = "zones"
icon = "speaker"
permission = "paging_bridge.read"

[[ui.views]]
id = "zones"
title = "Paging zones"
type = "resource_table"
endpoint = "zones"                      # relative to the API prefix
permission = "paging_bridge.read"
write_permission = "paging_bridge.write"
delete = true
columns = [{ key = "name", label = "Name" }, { key = "created_at", label = "Created", format = "datetime" }]
create_form = [{ key = "name", label = "Name", type = "text", required = true, max_length = 100 }]
```

Cross-field rules enforced by the validator:

* Permission keys and published events must start with the module's namespace (the last ID segment, with `-` replaced by `_`, followed by `.`).
* UI views may only use permissions the module declares. A view with a create form needs a `write_permission`.
* `ui.nav[].view` must refer to a declared view. Views need an `[api]` section.
* View endpoints are relative lower-case paths, and `..` is rejected.
* `table_prefix` must look like `mod_<name>_`.

## 3. Module API v1 (`veyra.sdk`)

Import **only** from `veyra.sdk`. Everything else under `veyra.*` is internal
and can change without notice.

```python
from veyra.sdk import ModuleContext, HealthResult, Event, Principal, get_db, Page, PageParams, page_params, ProblemError, not_found, forbidden, conflict, utcnow

class MyModule:
    def register(self, ctx: ModuleContext) -> None:     # required
        ctx.register_metadata(metadata)                 # tables must carry the prefix
        ctx.add_router(router)                          # once; needs [api]
        ctx.add_health_check(lambda: HealthResult("ok", "…"))
        ctx.subscribe("organization.created", handler)  # must match events.subscribes

    # optional lifecycle hooks
    def on_install(self, ctx): ...
    def on_enable(self, ctx): ...
    def on_disable(self, ctx): ...
    def on_uninstall(self, ctx, purge: bool): ...

module = MyModule()
```

`ModuleContext` provides:

| Member | Purpose |
|---|---|
| `module_id`, `manifest`, `module_dir`, `data_dir`, `log` | Identity, files, a private data directory (`/var/lib/veyra/modules/<id>`), and a logger |
| `require(permission)` | FastAPI dependency. Only the module's own permissions are allowed. |
| `add_router(router)` | Mounts at `/api/v1/ext/<prefix>`. Routes return 404 while the module is disabled. |
| `register_metadata(md)` | Declares the module's tables (the prefix is checked) |
| `session()` | Transactional database session for hooks and background work |
| `subscribe(pattern, fn)` / `publish(name, payload)` | Event bus, limited to declared patterns |
| `add_health_check(fn)` | Aggregated into `/api/v1/modules/<id>` and `/api/v1/system/health` |
| `get_config(db, org_id)` | Manifest defaults overlaid with stored values |
| `default_organization(db, principal)` | The caller's home organization |
| `audit(db, principal, action, …)` | Audit events prefixed with the module ID |

**Tenant scoping is the module's responsibility.** Filter every query with
`principal.organization_ids_with(<permission>)` (it returns `None` for
platform-wide access), and check `principal.has(<permission>, org_id)`
before writing. The example module shows the pattern.

`MODULE_API_VERSION` follows semantic versioning. A breaking change to
`ModuleContext` bumps the major version, and modules declare the range
they support.

## 4. Database migrations

Each module has its own Alembic history and version table
(`alembic_version_<module_id>`), so modules upgrade independently.
`migrations/env.py` is always:

```python
from veyra.modules.migration_env import run
run()
```

Use unique revision IDs (for example `paging_bridge_0001`). Migrations may
reference core tables (for example a foreign key to `organizations.id`) but
must not alter them. `downgrade()` must drop everything the module created,
because it is used for a confirmed purge.

## 5. Lifecycle

```
available ──install──► installed ──enable──► enabled ◄──enable── disabled
                           │                   │  └──disable──────►┘
                           └──────uninstall────┴── (must be disabled first) ──► removed (data kept)
removed ──install──► installed (data reused)
uninstall --purge (type the module id to confirm) ──► tables dropped, row deleted
```

* **Install** checks trust, compatibility and dependencies, runs migrations, registers permissions, and calls `on_install`.
* **Enable** requires enabled dependencies, loads the code, mounts routes, subscribes to events, and calls `on_enable`.
* **Disable** is refused while enabled modules depend on this one. It unsubscribes events and returns 404 from the module's routes.
* **Update** happens when a newer version is placed on disk by the update service. It checks compatibility, runs the new migrations, records the version, and reports `restart_required` because running code is not hot-swapped.

All operations are available in the API (`/api/v1/modules/...`), the UI
(Module Manager) and the CLI (`veyra modules ...`), and all are audited.

## 6. Signing, packaging and trust

```
veyra modules keygen acme-release --output-dir ~/keys        # once; keep the .key secret
veyra modules sign ./my-module --key-file ~/keys/acme-release.key --key-id acme-release --package ./dist
```

* `sign` writes `SHA256SUMS` (every file) and `SIGNATURE` (Ed25519 over the sums).
* `--package` builds `<id>-<version>.vmod`, a tar.gz. Extraction rejects absolute paths, `..`, links, devices, more than 5,000 files and more than 200 MB.
* Administrators trust a key by placing `<key_id>.pub` in `/etc/veyra/trust/official|community|third_party/`. **The directory decides the trust level.**
* Verification runs at install, enable and every startup. Any modified, added or removed file makes the module fail to load.

| Trust | May run in-process | Notes |
|---|---|---|
| official | yes | Reviewed and released by the Veyra project |
| community | no | Must use the `service` runtime (planned, M11) |
| third_party | no | Must use the `service` runtime (planned, M11) |
| unsigned | development only | Requires `VEYRA_ALLOW_UNSIGNED_MODULES=true` and a non-production environment |

The **service runtime** (planned) runs a module as its own systemd service
under its own account, talking to the core over a restricted, token-scoped
HTTP API. Its routes are proxied by the core and it has no direct database
access.

## 7. UI extension points

Modules do **not** ship JavaScript into the admin UI. This prevents
cross-site scripting and supply-chain risk in the administrative origin.
Instead, modules declare:

* `ui.nav`: entries in the "Modules" navigation section, hidden from users without the permission.
* `ui.views` of type `resource_table`: a paginated table backed by `GET <endpoint>` returning `{items,total,limit,offset}`, an optional create form posting JSON to `POST <endpoint>`, and an optional delete action calling `DELETE <endpoint>/<id>`.

More view types (detail forms, settings, charts) will be added as module API
minor versions.

## 8. Testing a module

* Unit-test your package directly.
* Integration tests can use the core test fixtures (`backend/tests/conftest.py`). `tests/test_api_modules.py` installs, enables, exercises, disables and purges the example module against PostgreSQL.
* During development, run the API with `VEYRA_ENVIRONMENT=development VEYRA_ALLOW_UNSIGNED_MODULES=true VEYRA_MODULE_PATHS=/path/to/modules`.

## 9. Not yet available

* Marketplace or catalogue browsing (deliberately out of scope for early milestones).
* The service runtime for community and third-party modules (M11).
* Download and installation of packages through the UI. M0 installs modules found in the module paths.
* Module settings UI generated from `[[config]]` (M11).
