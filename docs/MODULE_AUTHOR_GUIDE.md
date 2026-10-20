# Module author guide

This page answers issue #94. Read it before you build a Veyra module, or
give it to an AI coding agent as its starting prompt (§6). It explains the
Veyra concepts a module touches, lists what a module can and cannot do
today, and walks through a small module end to end.

The reference specification is [MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md)
(manifest, module API, lifecycle, signing). The catalog is described in
[MODULE_CATALOG.md](MODULE_CATALOG.md). Where this guide and the code
disagree, the code wins. Please report the difference.

## 1. What a module is

A module is a directory with a manifest (`module.toml`), a Python package
and, optionally, Alembic migrations. The core loads it at run time. A module
adds API endpoints, database tables, permissions, settings, event handlers,
periodic tasks and declarative UI pages without changing the core.

| Piece | Where it lives | What to know |
|---|---|---|
| Manifest | `module.toml`, validated by `backend/veyra/modules/manifest.py` | Unknown keys are rejected. Check it with `veyra modules validate <dir>`, and print the JSON Schema with `veyra modules schema`. |
| Module API | `backend/veyra/modules/context.py` (`ModuleContext`), re-exported by `backend/veyra/sdk.py` | Import **only** from `veyra.sdk`. Everything else under `veyra.*` is internal. |
| API version | `MODULE_API_VERSION` in `backend/veyra/version.py`, currently **1.3.0** | The manifest declares a range in `[compatibility] core_api`. A module that uses `edit_form` declares `">=1.2.0 <2.0.0"`. Install is refused when the range does not contain the running version. |
| Loader | `backend/veyra/modules/manager.py` (`ModuleManager`) | Imports the entrypoint package as `veyra_ext_<id>` and calls `register(ctx)`. A failing module is marked `failed` and never stops the core. |
| Migrations | `backend/veyra/modules/migrations.py`, `migration_env.py` | One Alembic history per module, version table `alembic_version_<id>`. |
| Signing | `backend/veyra/modules/packages.py` | `SHA256SUMS` lists every file and `SIGNATURE` is an Ed25519 signature over it. Any added, changed or removed file makes the module fail to load. |
| Catalog | `backend/veyra/modules/catalog.py`, `backend/veyra/api/v1/module_catalog.py` | A signed `index.json` that lists `.vmod` packages. Packages can also be uploaded. |

### 1.1 Lifecycle

```
available → install → installed → enable → enabled ⇄ disable → disabled
uninstall (must be disabled; data kept) → removed      uninstall + purge → tables dropped
```

* **Install** checks trust, compatibility and dependencies, runs the
  migrations, registers the permissions, imports the code and calls
  `on_install`.
* **Enable** loads the code, mounts the router at `/api/v1/ext/<prefix>` in
  the running API process, subscribes the event handlers and calls
  `on_enable`. The worker picks up the change within about a minute.
* **Disable** unsubscribes the handlers. The routes then answer 404
  (`module_disabled`).
* **Update** (a newer version from the catalog, an upload or the disk) runs
  the new migrations and reports `restart_required`. Running code is never
  swapped in place, so after an update the administrator uses "Restart Veyra
  services" (`POST /api/v1/modules/restart-services`). The previous version
  stays in the store for **rollback** (`POST /api/v1/modules/{id}/rollback`).

Where to run each operation:

| Operation | API (`/api/v1/modules/...`) | CLI (`veyra modules ...`) |
|---|---|---|
| List | `GET /modules` | `list` |
| Install / enable / disable | `POST /{id}/install`, `/enable`, `/disable` | `install`, `enable`, `disable` (then restart `veyra-api`) |
| Uninstall, purge | `POST /{id}/uninstall` `{"purge_data": true, "confirm_module_id": "<id>"}` | `uninstall <id>`, `uninstall <id> --purge --confirm <id>` |
| Update, rollback | `POST /{id}/update`, `POST /{id}/rollback` | `update <id>`, `rollback <id>` |
| Upload a `.vmod` | `POST /upload` | `upload <file.vmod> [--enable]` (the file must be readable by the `veyra` account) |
| Settings | `GET/PUT /{id}/config` (`?organization_id=`) | `config <id>` shows them; `config <id> key=value … [--secret key] [--organization <org id>]` changes them |
| Validate, schema, keygen, sign, package | — | `validate`, `schema`, `keygen`, `sign --package` |

The Module Manager page in the web interface uses the same API. Every
operation is audited.

### 1.2 Trust: who may run a module

The trust level comes from the directory that holds the signing key's public
half: `/etc/veyra/trust/official|community|third_party/<key_id>.pub`.

* Only **official** modules may use `runtime.type = "in_process"`, which
  is the only runtime that exists today. Community and third-party modules
  need the planned `service` runtime (issue #110), so the manager refuses
  them.
* For a custom module, the administrator generates a key, places its
  `.pub` file in `/etc/veyra/trust/official/`, and so vouches for the code.
  The module runs inside the core process with full database access.
* **Unsigned** modules load only with `VEYRA_ALLOW_UNSIGNED_MODULES=true` in a
  non-production environment, which is how development and the test suite
  run.
* Modules in the release's `modules/` directory, except `veyra-example-*`,
  are signed by the installer with the server's own `bundled-modules` key
  (`installer/lib/steps.sh`). Do not edit them on a server: the signature
  would break.

## 2. Core concepts in one page

**Organizations and sites.** Every tenant-owned row carries
`organization_id` (`TenantScoped` in `backend/veyra/core/models/base.py`).
Organizations (`organizations` table) contain sites, buildings and
departments (`backend/veyra/core/models/tenancy.py`). Each organization has
an **engine namespace** (`organizations.engine_namespace`), and every
Asterisk name is built from it: for example `veyra-internal` for the first
organization and `veyra_acme-internal` for namespace `acme`. With more than
one namespace, an isolation verifier
(`backend/veyra/telephony/asterisk/isolation.py`) refuses any revision in
which one organization could reach another. See
[MULTI_TENANCY.md](MULTI_TENANCY.md). **A module must scope every query and
every write to the caller's organizations itself** (see Permissions below).

**Extensions and devices.** An extension (`extensions` table,
`backend/veyra/core/models/telephony.py`) is a number in an organization
(`organization_id` + `number` is unique), with a SIP endpoint named
`<org slug>-<number>` and an encrypted secret. A device (`devices`) is a
physical phone known by its MAC address, with lines and keys, provisioned
from templates ([DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md)).
Modules have no SDK access to these tables (§3.2).

**Destinations.** Inbound routes, IVR menus, ring groups, queues and
announcements send calls to a *destination*: one of `extension`,
`voicemail`, `voicemail_box`, `ivr`, `ring_group`, `queue`, `announcement`,
`conference`, `call_flow`, `fax`, `directory` or `hangup`
(`DestinationType` in `backend/veyra/api/v1/destinations.py`). A module
cannot add a destination type.

**Snapshot → generated files → deploy.** Configuration is never written by
hand. `build_snapshot()` (`backend/veyra/telephony/snapshot.py`) reads the
database into plain JSON in one transaction. `generate()`
(`backend/veyra/telephony/asterisk/generator.py`) turns that snapshot into
Asterisk files as a pure function, so the same data gives byte-identical
files. A **revision** stores the files (`backend/veyra/configmgmt/`).
Saving a telephony object calls `configmgmt.service.mark_changed`, which
shows "Deploy changes". `POST /api/v1/telephony/apply` (or
`/telephony/revisions` followed by `/revisions/{id}/deploy`) queues a
revision, and the separate `veyra deployer` service writes the files, reloads
Asterisk, verifies, and restores the previous files on failure. **Modules
take no part in this pipeline** (§3.2).

**Event bus.** `backend/veyra/core/events.py`: an in-process `EventBus`
with glob subscriptions (`organization.*`). Handlers run synchronously after
the publisher commits. A failing handler is logged and never breaks the
publisher. Events are **not** sent between processes: a handler runs only in
the process where the event was published. Examples:

| Event | Published in | Payload |
|---|---|---|
| `organization.created` | API | `organization_id`, `slug` |
| `extension.created` | API | `extension_id`, `organization_id`, `number` |
| `extension.updated` | API | `extension_id`, `organization_id`, `number`, `changes` (since 0.27.23) |
| `<object>.created/updated/deleted` for ring groups, queues, IVRs, pages, trunks, routes, conferences, prompts, … | API | the object's `id` (and often `number`) |
| `bell.rang` | worker | `organization_id`, `schedule_id`, `schedule_name`, `summary`, `trigger`, `due_at`, `outcome` |
| `module.enabled`, `module.disabled` | API | `module_id` |

Search for `Event("` under `backend/veyra/` to see the exact payload before
you rely on it.

**Permissions and audit.** Permissions are strings `<area>.<action>`
(`backend/veyra/core/security/permissions.py`). The system roles are
`platform_admin`, `org_admin`, `site_admin`, `technician`, `standard_user`
and `read_only`. A module declares its own permissions in the manifest
(prefixed with its namespace) with `default_roles`. A `Principal`
(`backend/veyra/core/security/principal.py`) holds grants at platform,
organization or site scope:

* `principal.organization_ids_with(perm)` returns the organizations where
  the caller holds `perm`, or `None` for platform-wide access. Filter every
  list with it.
* `principal.has(perm, org_id)` checks one organization. Use it before every
  read of one object (answer 404 when it fails) and before every write
  (answer 403 when it fails).

Every state-changing operation writes an audit event
(`backend/veyra/core/audit.py`). A module calls `ctx.audit(db, principal,
"<thing>.<verb>", organization_id=…, target_type=…, target_id=…,
details=…)`, and the action is stored as `<module id>:<thing>.<verb>`.

**Processes and the worker's ticks.** `veyra-api` serves the API and loads
the enabled modules with their routes. `veyra-worker` (`cmd_worker` in
`backend/veyra/cli/main.py`) runs a loop:

* every `--tick` seconds (default 5): bells, calendars, mail, webhooks,
  then `ModuleManager.run_periodic()`;
* every 60 seconds: `sync_worker()` loads or unloads modules that were
  enabled or disabled since the last pass;
* every `--interval` seconds (default 30): housekeeping.

A periodic task registered with an interval of N seconds therefore runs on
the first tick after N seconds, and never more often than every 5 seconds.
On an HA standby the worker does nothing. Keep state in the database, not
in memory: the same module code runs in both processes.

**Frontend conventions.** Modules do not ship JavaScript (§3.1). These
conventions matter only when you change the core interface, for example to
add a new view type: Next.js static export under `frontend/src/app/(app)/`;
UI primitives from `@/components/ui` (`Card`, `DataTable`, `Dialog`,
`ConfirmDialog`, `Tabs` and `TabPanel`, `TextField`, `SelectField`, …);
`useApiData(path, query)` (`frontend/src/hooks/useApiData.ts`) for GET
requests with loading and error state; `useUrlTab` to keep the active tab in
the URL; `createApi()` / `errorMessage()` from `@/lib/api`. Module pages are
rendered by `frontend/src/app/(app)/modules/view/page.tsx`, and their
navigation entries come from `moduleNavItems()` in `frontend/src/lib/nav.ts`.
The My Phone portal's widgets are a fixed registry in
`frontend/src/portal/widgets.ts`.

## 3. Extension points

### 3.1 Available today (module API 1.3.0)

| Extension point | How | Notes |
|---|---|---|
| API router | `ctx.add_router(router)` once; manifest `[api] prefix` | Mounted at `/api/v1/ext/<prefix>`. Guard each route with `Depends(ctx.require("<own permission>"))`. A module may only check its own permissions. Use `get_db`, `Page`, `page_params`, `ProblemError`, `not_found`, `forbidden`, `conflict` from `veyra.sdk`. |
| Tables | `ctx.register_metadata(metadata)`; manifest `[database] table_prefix = "mod_<name>_"` | Every table name must start with the prefix. Use SQLAlchemy Core `Table` objects, as the bundled modules do. |
| Migrations | `migrations/env.py` (two lines) and `migrations/versions/*.py` | Unique revision ids (`<name>_0001`). Foreign keys to core tables (`organizations.id`) are allowed. Changing core tables is not. `downgrade()` must drop everything, because purge uses it. |
| Event handlers | `ctx.subscribe(pattern, fn)`; manifest `[events] subscribes` | The pattern must match a declared pattern. |
| Publishing events | `ctx.publish(name, payload)`; manifest `[events] publishes` | Names must start with the module namespace (`bell_log.`). Publish after `db.commit()`. |
| Periodic tasks | `ctx.add_periodic_task(name, seconds, fn)` *(1.1)* | Run by the worker only, at least every 5 s. Open `ctx.session()` inside. Exceptions are logged. |
| Background database work | `with ctx.session() as db:` | Commits on exit, rolls back on error. |
| Settings | manifest `[[config]]` (`string`, `integer`, `boolean`, `choice`, `secret`); `ctx.get_config(db, org_id)` | The Module Manager's Settings dialog is generated from the manifest; its "Settings for" choice edits a chosen organization's `scope = "organization"` fields. Only platform administrators (`modules.manage`) change settings. `secret` values are stored encrypted and returned decrypted only to the module. |
| Secrets in your own tables | `ctx.encrypt(text)` / `ctx.decrypt(token)` *(1.1)* | Bound to the module: other modules cannot decrypt them. |
| Time zone | `ctx.organization_timezone(db, org_id)` *(1.1)* | For times that administrators type in. |
| Core data | `ctx.organizations(db)`, `ctx.sites(db, org_id)`, `ctx.extensions(db, org_id, site_id=, number=)`, `ctx.extension(db, id)`, `ctx.devices(db, org_id, site_id=)`, `ctx.users(db, org_id)` *(1.3)* | Read-only frozen records from `veyra.sdk` (`ExtensionInfo`, …) with no secrets. Fields may be added within 1.x, never removed. They do not check permissions: filter with `principal.organization_ids_with(...)` before returning them. |
| Health | `ctx.add_health_check(fn)` returning `HealthResult("ok" \| "degraded" \| "failed" \| "unknown", message, details)` | Shown in `/api/v1/modules/<id>` and `/api/v1/system/health`. With `health_check = true` in the manifest and no check added, the module reports `degraded`. |
| Audit, logging, files | `ctx.audit(...)`, `ctx.log`, `ctx.data_dir`, `ctx.module_dir` | `data_dir` is `<data>/modules/<id>`, created by the core when the module loads. |
| Lifecycle hooks | `on_install`, `on_enable`, `on_disable`, `on_uninstall(ctx, purge)` on the entrypoint object | Optional. |
| Dependencies on other modules | manifest `[[dependencies]] id, version, optional` | Enable requires enabled dependencies. Disable is refused while dependents are enabled. |
| UI navigation | manifest `[[ui.nav]] label, view, icon, permission` | Shown in the navigation for users with the permission. `icon` is a name from `frontend/src/components/ui/Icon.tsx` (unknown names show `puzzle`). |
| UI page | manifest `[[ui.views]]` of `type = "resource_table"` | A paginated table from `GET <endpoint>?limit=&offset=` that returns `{items, total, limit, offset}`. Each row needs an `id`. Column formats are `text`, `datetime`, `boolean` and `status`. |
| Create form | `create_form = [...]` (needs `write_permission`) | Sends `POST <endpoint>` with JSON. Field types are `text`, `textarea`, `integer`, `boolean`, `choice` and `password` *(1.1)*. Empty fields are sent as `""`, integers as `null`. |
| Edit form | `edit_form = [...]` *(1.2, needs `write_permission`)* | Clicking a row opens the form filled from the row. Only changed fields are sent as `PATCH <endpoint>/<id>`, and an empty password is left out. |
| Delete | `delete = true` | Calls `DELETE <endpoint>/<id>` after a confirmation. |

### 3.2 Not possible today

Do not build on any of these. Ask for the core change instead.

| Wanted | Status |
|---|---|
| Generated dialplan or other engine configuration fragments | **Not available.** `build_snapshot()` and `generate()` have no module input, and `ModuleContext` has no method for it. A module cannot add contexts, feature codes or destination types, and cannot trigger a deploy. |
| My Phone portal widgets | **Not available**: open issue #134. `frontend/src/portal/widgets.ts` is a fixed list. |
| Custom JavaScript, custom pages, other view types (detail, chart, settings page) | **Not available.** Only `resource_table` exists, and the page shows "Unsupported view" for any other type. A module page cannot use tabs, filters, search or row actions other than edit and delete. |
| Python libraries of its own | **Not installed.** A module can use only what the core's virtual environment already installs (for example `httpx`, `sqlalchemy`, `pydantic`, `fastapi`). Declare them in `[runtime] requires = ["httpx>=0.27"]` (`name` or `name>=1.2,<2`; release numbers only): install is refused with a clear message when this Veyra lacks one, instead of failing on import. |
| Community or third-party (sandboxed) modules | The `service` runtime is planned (issue #110). Today only `in_process` modules with official trust load. |
| Events across processes | Not available. An event reaches handlers only in the process that published it. |
| Hot code reload | Not available. An update needs a service restart. |

## 4. Rules a module must follow

1. Import from the core only through `veyra.sdk`.
2. Filter every list with `principal.organization_ids_with(<read perm>)`.
   Before acting on one row, check `principal.has(<perm>, row.organization_id)`:
   answer 404 when the caller cannot read the row and 403 when the caller
   cannot write it.
3. Writes take the organization from the request or from
   `ctx.default_organization(db, principal)`, and check `principal.has`
   for it.
4. Audit every change with `ctx.audit`. Do not put secrets in `details`.
5. Use the manifest namespace everywhere: permissions `<ns>.…`, published
   events `<ns>.…`, tables `mod_<ns>_…`. The namespace is the last id
   segment with `-` replaced by `_` (`example.bell-log` → `bell_log`).
6. Return problem responses with `ProblemError` / `not_found` /
   `forbidden` / `conflict` and plain, helpful text.
7. Keep handlers and tasks short and idempotent. They share the worker loop
   with bells and paging.
8. Write the README for an administrator: what the module does, its setup,
   and its settings.

## 5. Worked example: the Bell Log module

A small but complete module: it records every scheduled bell (`bell.rang`),
shows the entries in a table, lets an administrator add a note to an entry
(edit form, module API 1.2), deletes entries on request, and purges old
entries with a periodic task. It follows `modules/veyra-example-notes` (the
template) and `modules/veyra-and-clocks` (which subscribes to `bell.rang`
and uses periodic tasks). It is not shipped with Veyra.

```
modules/example-bell-log/
  module.toml
  README.md
  backend/__init__.py      entrypoint object `module`
  backend/models.py        table definitions
  backend/api.py           the router
  migrations/env.py
  migrations/versions/0001_create_bell_log.py
backend/tests/test_bell_log.py
```

The test suite discovers modules only in the repository's `modules/`
directory (`backend/tests/conftest.py`, `module_paths`). Develop the module
there in your checkout. Anything committed under `modules/` (except
`veyra-example-*`) becomes part of a release built from that checkout, so
keep a private module in your own fork or branch.

### 5.1 `module.toml`

```toml
# Bell Log: a worked example from docs/MODULE_AUTHOR_GUIDE.md.
manifest_version = 1
health_check = true

[module]
id = "example.bell-log"
name = "Bell Log"
description = "Keeps a log of every scheduled bell with its outcome, and lets administrators add a note to an entry."
version = "0.1.0"
author = "Example Org"
license = "AGPL-3.0-or-later"
homepage = "https://example.org/veyra/bell-log"

[compatibility]
core_api = ">=1.2.0 <2.0.0"             # edit_form needs module API 1.2
engines = []

[runtime]
type = "in_process"
entrypoint = "backend:module"

[[permissions]]
key = "bell_log.read"
description = "View the bell log"
default_roles = ["org_admin", "site_admin", "technician", "read_only"]

[[permissions]]
key = "bell_log.write"
description = "Add notes to and delete bell log entries"
default_roles = ["org_admin"]

[[config]]
key = "keep_days"
label = "Days to keep bell log entries"
type = "integer"
default = 90
min = 1
max = 3650

[database]
migrations = "migrations"
table_prefix = "mod_bell_log_"

[api]
prefix = "bell-log"

[events]
subscribes = ["bell.rang"]

[[ui.nav]]
label = "Bell Log"
view = "rings"
icon = "clock"
permission = "bell_log.read"

[[ui.views]]
id = "rings"
title = "Bell log"
type = "resource_table"
description = "Every scheduled bell after it rings. Click an entry to add a note."
endpoint = "rings"
permission = "bell_log.read"
write_permission = "bell_log.write"
delete = true
empty_title = "No bells yet"
empty_body = "Each scheduled bell appears here after it rings."
columns = [
  { key = "schedule_name", label = "Bell schedule" },
  { key = "summary", label = "Event" },
  { key = "due_at", label = "Due", format = "datetime" },
  { key = "outcome", label = "Outcome", format = "status" },
  { key = "note", label = "Note" },
]
edit_form = [
  { key = "note", label = "Note", type = "textarea", max_length = 1000, help = "For example why the bell did not sound." },
]
```

`veyra modules validate modules/example-bell-log` prints
`OK: example.bell-log 0.1.0`.

### 5.2 `backend/models.py`

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, Uuid, func

metadata = MetaData()

rings = Table(
    "mod_bell_log_ring",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False, index=True),
    Column("schedule_name", String(100), nullable=False),
    Column("summary", String(500), nullable=False, server_default=""),
    Column("due_at", DateTime(timezone=True), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("note", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
```

### 5.3 `backend/__init__.py`

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bell Log: records every scheduled bell (the ``bell.rang`` event).

Only ``veyra.sdk`` is imported from the core.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, select

from veyra.sdk import Event, HealthResult, ModuleContext, utcnow

from .api import build_router
from .models import metadata, rings


class BellLogModule:
    def register(self, ctx: ModuleContext) -> None:
        ctx.register_metadata(metadata)
        ctx.add_router(build_router(ctx))
        ctx.add_health_check(lambda: _health(ctx))
        # bell.rang is published in the worker, so this handler runs there.
        ctx.subscribe("bell.rang", lambda event: record_ring(ctx, event))
        ctx.add_periodic_task("purge-old", 3600, lambda: purge_old(ctx))


def record_ring(ctx: ModuleContext, event: Event) -> None:
    p = event.payload
    try:
        org = uuid.UUID(str(p["organization_id"]))
        due = datetime.fromisoformat(str(p["due_at"]))
    except (KeyError, ValueError):
        ctx.log.warning("bell.rang without an organization or a time: %s", p)
        return
    with ctx.session() as db:
        db.execute(
            insert(rings).values(
                id=uuid.uuid4(),
                organization_id=org,
                schedule_name=str(p.get("schedule_name") or "")[:100],
                summary=str(p.get("summary") or "")[:500],
                due_at=due,
                outcome=str(p.get("outcome") or "unknown")[:32],
            )
        )


def purge_old(ctx: ModuleContext) -> None:
    with ctx.session() as db:
        days = int(ctx.get_config(db)["keep_days"])
        db.execute(delete(rings).where(rings.c.due_at < utcnow() - timedelta(days=days)))


def _health(ctx: ModuleContext) -> HealthResult:
    with ctx.session() as db:
        count = db.scalar(select(func.count()).select_from(rings)) or 0
    return HealthResult("ok", f"{count} bell(s) logged.", {"rings": count})


module = BellLogModule()
```

### 5.4 `backend/api.py`

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.orm import Session

from veyra.sdk import (
    ModuleContext,
    Page,
    PageParams,
    Principal,
    forbidden,
    get_db,
    not_found,
    page_params,
)

from .models import rings

READ, WRITE = "bell_log.read", "bell_log.write"


class RingPatch(BaseModel):
    note: str | None = Field(None, max_length=1000)


def _out(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    return {**d, "id": str(d["id"]), "organization_id": str(d["organization_id"])}


def build_router(ctx: ModuleContext) -> APIRouter:
    router = APIRouter()
    can_read = ctx.require(READ)
    can_write = ctx.require(WRITE)

    def visible(principal: Principal) -> Select[Any]:
        stmt = select(rings)
        orgs = principal.organization_ids_with(READ)  # None = every organization
        if orgs is not None:
            stmt = stmt.where(rings.c.organization_id.in_(orgs or {uuid.UUID(int=0)}))
        return stmt

    def owned(db: Session, principal: Principal, ring_id: uuid.UUID) -> Any:
        row = db.execute(select(rings).where(rings.c.id == ring_id)).first()
        if row is None or not principal.has(READ, row.organization_id):
            raise not_found("Bell log entry")
        if not principal.has(WRITE, row.organization_id):
            raise forbidden()
        return row

    @router.get("/rings", response_model=Page[dict[str, Any]])
    def list_rings(
        page: PageParams = Depends(page_params),
        principal: Principal = Depends(can_read),
        db: Session = Depends(get_db),
    ) -> Page[dict[str, Any]]:
        stmt = visible(principal)
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.execute(
            stmt.order_by(rings.c.due_at.desc()).limit(page.limit).offset(page.offset)
        )
        return Page(
            items=[_out(r) for r in rows], total=total, limit=page.limit, offset=page.offset
        )

    @router.patch("/rings/{ring_id}")
    def update_ring(
        ring_id: uuid.UUID,
        body: RingPatch,
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        row = owned(db, principal, ring_id)
        if body.note is not None and body.note != row.note:
            db.execute(update(rings).where(rings.c.id == ring_id).values(note=body.note))
            ctx.audit(
                db,
                principal,
                "ring.note",
                organization_id=row.organization_id,
                target_type="bell_ring",
                target_id=ring_id,
            )
            db.commit()
        return _out(db.execute(select(rings).where(rings.c.id == ring_id)).one())

    @router.delete("/rings/{ring_id}")
    def delete_ring(
        ring_id: uuid.UUID,
        principal: Principal = Depends(can_write),
        db: Session = Depends(get_db),
    ) -> dict[str, str]:
        row = owned(db, principal, ring_id)
        db.execute(delete(rings).where(rings.c.id == ring_id))
        ctx.audit(
            db,
            principal,
            "ring.delete",
            organization_id=row.organization_id,
            target_type="bell_ring",
            target_id=ring_id,
        )
        db.commit()
        return {"message": "Entry deleted."}

    return router
```

### 5.5 Migrations

`migrations/env.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
from veyra.modules.migration_env import run

run()
```

`migrations/versions/0001_create_bell_log.py`:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Create the bell log table.

Revision ID: bell_log_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "bell_log_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mod_bell_log_ring",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schedule_name", sa.String(100), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_mod_bell_log_ring_organization_id", "mod_bell_log_ring", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_table("mod_bell_log_ring")
```

### 5.6 Test: `backend/tests/test_bell_log.py`

The `admin` fixture (`backend/tests/conftest.py`) is a signed-in platform
administrator on a fresh PostgreSQL database, with unsigned modules allowed.
Events are published on the global `bus`, as `bell.rang` would be.
Periodic tasks are called directly from the loaded module's context, the
way `backend/tests/test_and_clocks.py` does.

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Bell Log example module (docs/MODULE_AUTHOR_GUIDE.md §5)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from veyra.core.events import Event, bus
from veyra.core.models.base import utcnow

MOD = "example.bell-log"
BASE = "/api/v1/ext/bell-log"


@pytest.fixture
def bell_admin(admin):
    assert admin.post(f"/api/v1/modules/{MOD}/install").status_code == 200
    assert admin.post(f"/api/v1/modules/{MOD}/enable").status_code == 200
    return admin


def _ring(org: str, summary: str, days_ago: int = 0) -> None:
    due = utcnow() - timedelta(days=days_ago)
    bus.publish(
        Event(
            "bell.rang",
            {
                "organization_id": org,
                "schedule_name": "Main bells",
                "summary": summary,
                "due_at": due.isoformat(),
                "outcome": "started",
            },
        )
    )


def test_bells_are_logged_noted_and_deleted(bell_admin):
    admin = bell_admin
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    _ring(org, "Period 2")
    bus.publish(Event("bell.rang", {"schedule_name": "no organization"}))  # ignored
    items = admin.get(f"{BASE}/rings").json()["items"]
    assert [(i["summary"], i["outcome"]) for i in items] == [("Period 2", "started")]

    r = admin.patch(f"{BASE}/rings/{items[0]['id']}", json={"note": "Fire drill"})
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "Fire drill"
    assert (
        admin.patch(f"{BASE}/rings/{items[0]['id']}", json={"note": "x" * 1001}).status_code == 422
    )

    assert admin.delete(f"{BASE}/rings/{items[0]['id']}").status_code == 200
    assert admin.get(f"{BASE}/rings").json()["total"] == 0


def test_old_entries_are_purged_by_the_worker_task(bell_admin):
    admin = bell_admin
    org = admin.get("/api/v1/organizations").json()["items"][0]["id"]
    _ring(org, "Old", days_ago=400)
    _ring(org, "New")
    ctx = admin.app.state.modules.loaded[MOD].ctx
    {t.name: t for t in ctx.periodic_tasks}["purge-old"].fn()
    items = admin.get(f"{BASE}/rings").json()["items"]
    assert [i["summary"] for i in items] == ["New"]


def test_ui_view_offers_the_edit_form(bell_admin):
    ext = next(
        e for e in bell_admin.get("/api/v1/modules/ui-extensions").json() if e["module_id"] == MOD
    )
    assert ext["api_base"] == BASE
    assert [f["key"] for f in ext["views"][0]["edit_form"]] == ["note"]
```

Add a test for every permission rule you rely on: a user of another
organization gets 404, and a `read_only` user gets 403 on PATCH and DELETE.
`backend/tests/test_api_modules.py` shows the lifecycle tests (install,
disable, uninstall, purge).

### 5.7 Frontend

None. The table, the edit dialog, the delete confirmation and the
navigation entry are generated from `[[ui.views]]` and `[[ui.nav]]` by
`frontend/src/app/(app)/modules/view/page.tsx`. The "Days to keep" field
appears on the module's Settings tab in the Module Manager.

### 5.8 Run it locally

Use the development environment of [DEVELOPMENT.md](DEVELOPMENT.md) §3
(`VEYRA_ENVIRONMENT=development VEYRA_ALLOW_UNSIGNED_MODULES=true
VEYRA_MODULE_PATHS=$PWD/../modules`). Then open the Module Manager, install
and enable "Bell Log", and run `veyra worker` next to the API so that bells
ring and the purge task runs.

### 5.9 Checklist

From `backend/`:

```
.venv/bin/veyra modules validate ../modules/example-bell-log
.venv/bin/ruff check veyra tests ../modules
.venv/bin/ruff format --check veyra tests ../modules
.venv/bin/mypy veyra
.venv/bin/pytest -q tests/test_bell_log.py      # needs PostgreSQL; drops and recreates veyra_test
.venv/bin/pytest -q                             # the whole suite before a release
```

`mypy veyra` checks the core only (`packages = ["veyra"]` in
`backend/pyproject.toml`). To type-check the module too, run
`../backend/.venv/bin/mypy --config-file ../backend/pyproject.toml backend`
from the module's directory; CI does this for every module in `modules/`.

From `frontend/` (needed only when you changed the core interface):

```
npx tsc --noEmit
npm run lint
npx vitest run
```

Before you publish, also check:

* `core_api` covers the API features you use (1.1 for periodic tasks,
  secrets and time zones; 1.2 for `edit_form`; 1.3 for core data).
* `module.version` is bumped for every published change. A new version with
  new migrations cannot be rolled back.
* `downgrade()` drops everything that `upgrade()` creates.
* The module's README explains the setup and the settings.

### 5.10 Package and sign

```
veyra modules keygen example-release --output-dir ~/keys      # once; keep the .key secret
veyra modules sign modules/example-bell-log \
    --key-file ~/keys/example-release.key --key-id example-release --package ./dist
# → dist/example.bell-log-0.1.0.vmod
```

* `sign` writes `SHA256SUMS` and `SIGNATURE` into the directory. Sign after
  the last change: any later edit breaks verification. `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache` and `*.pyc` are ignored, and
  symbolic links are refused.
* On the server, the administrator copies `example-release.pub` to
  `/etc/veyra/trust/official/` (the directory decides the trust level,
  §1.2), then uploads the `.vmod` (Modules → Upload, or
  `POST /api/v1/modules/upload`), installs and enables it.
* To publish through a catalog
  ([MODULE_CATALOG.md](MODULE_CATALOG.md) §2.4):

  ```
  veyra catalog add dist/example.bell-log-0.1.0.vmod --url <release asset URL> --index catalog/index.json
  veyra catalog sign catalog/index.json --key-file catalog.key --key-id <catalog key id>
  veyra catalog verify catalog/index.json --trust-dir <trust root containing catalog/>
  ```

  Servers accept the index only when its key is in `/etc/veyra/trust/catalog/`.

## 6. Prompt for an AI coding agent

Copy this block, fill in the two placeholders, and give it to the agent as
its first message.

````text
You are building a custom module for Veyra, an open-source phone system
(PBX) management platform. The repository is checked out at <PATH TO veyra>.

Module to build: <ONE PARAGRAPH: what it does, who uses it, which data it
keeps, which Veyra events or schedules it reacts to>.

Before writing code, read in this order:
1. docs/MODULE_AUTHOR_GUIDE.md: concepts, the extension points that exist
   today (§3.1) and those that do not (§3.2), the rules (§4), and the worked
   example (§5).
2. docs/MODULE_DEVELOPMENT.md: manifest and module API reference.
3. backend/veyra/modules/manifest.py and backend/veyra/modules/context.py:
   the executable specification. backend/veyra/version.py: MODULE_API_VERSION.
4. modules/veyra-example-notes/ and modules/veyra-and-clocks/: real modules.
   Copy their structure.
5. backend/tests/test_api_modules.py and backend/tests/test_and_clocks.py:
   how modules are tested.

Rules:
- Import from the core only through `veyra.sdk`.
- Use only the extension points in §3.1 of the guide. If the module needs
  something in §3.2 (dialplan fragments, portal widgets, custom JavaScript,
  core tables, extra Python libraries), stop and say so instead of working
  around it.
- Scope every query and write to the caller's organizations
  (principal.organization_ids_with / principal.has), and audit every change
  with ctx.audit.
- Put the module in modules/<dir>/ with module.toml, backend/, migrations/
  and README.md, and its tests in backend/tests/test_<name>.py.
- Check every event name and payload key you use by searching backend/veyra
  for `Event("<name>"`.
- Do not change core files unless asked to.

Done means all of these pass (from backend/):
  .venv/bin/veyra modules validate ../modules/<dir>
  .venv/bin/ruff check veyra tests ../modules
  .venv/bin/ruff format --check veyra tests ../modules
  .venv/bin/mypy veyra
  .venv/bin/pytest -q tests/test_<name>.py
and, if you touched frontend/: npx tsc --noEmit, npm run lint,
npx vitest run. Then report: the files you created, the permissions, tables
and events, what you could not build with today's module API, and the
signing command from §5.10 of the guide.
````

## 7. Keep it current

Update this guide in the same commit whenever `MODULE_API_VERSION` changes,
`ModuleContext` or `veyra.sdk` gains or loses a member, the manifest schema
changes (`backend/veyra/modules/manifest.py`), a new UI view type or form
field type is added, or an item in §3.2 becomes possible (for example
issue #134 or #110). Add a check of this page to the release checklist.
[MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md) must change at the same time.
