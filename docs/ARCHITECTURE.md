# Veyra Architecture

This document describes how Veyra is structured and why. Major decisions are
recorded as Architecture Decision Records in [`docs/adr/`](adr/). Items marked
**(planned, M*n*)** are designed but not implemented; the milestone number
says when they are expected.

## 1. Overview

```
Browser (admin UI: static Next.js export)
        │ HTTPS (NGINX: TLS, security headers, static files, /api proxy)
        ▼
veyra-api  (FastAPI, 127.0.0.1:8100) ──── PostgreSQL (authoritative data)
   │  core: auth, RBAC, tenancy, audit, modules, updates, config, health
   │  modules (official, in-process) / isolated module services (planned)
   │
   ├── Telephony services ── Engine adapter interface ── Asterisk adapter ── ARI (127.0.0.1:8088)
   │                                                     (FreeSWITCH adapter: not planned)
   │
veyra-worker (scheduled jobs: heartbeats, update checks)
veyra-deployer (planned, M3: validates/writes engine config, reloads engine)
```

Processes and trust boundaries:

| Process | Runs as | Can reach | Notes |
|---|---|---|---|
| NGINX | `www-data` | static files, `127.0.0.1:8100` | The only listener on the network for administration (HTTPS). |
| veyra-api | `veyra` | PostgreSQL via local socket (peer auth), ARI on loopback | systemd-hardened, read-only code, no capabilities. |
| veyra-worker | `veyra` | same as the API | Background jobs. |
| veyra-deployer (planned) | dedicated account | `/etc/asterisk/veyra/`, engine reload | The only component allowed to write telephony configuration. |
| Asterisk | `asterisk` | SIP/RTP on the network, ARI on loopback | AMI disabled. Keeps running when Veyra is down. |
| PostgreSQL | `postgres` | local socket (network only for HA replication, M16) | |

## 2. Code layout

```
backend/veyra/
  core/          config, db, models, security (passwords, sessions, RBAC), audit,
                 events, errors (RFC 9457), pagination, semver, signing, bootstrap
  api/v1/        versioned HTTP API (OpenAPI at /api/docs)
  modules/       module framework: manifest, packages, manager, context (module API), migrations
  telephony/     adapter interface + asterisk adapter
  configmgmt/    configuration revision state machine and diffs
  provisioning/  template spec, catalog, sandboxed renderer
  updates/       update policy, signed metadata, checker
  ha/            cluster status
  system/        host metrics
  cli/           `veyra` command and terminal branding
  migrations/    core Alembic migrations
  sdk.py         public surface for module authors
frontend/        Next.js (static export) admin UI and design system
modules/         official modules shipped with Veyra (example: veyra-example-notes)
provisioning/templates/official/   official phone templates
installer/       install/preflight/verify/upgrade/uninstall + templates
docs/            documentation and ADRs
```

## 3. Deployment modes

All modes use the same code and schema. The mode is data
(`installation.deployment_mode`, `multi_tenancy_enabled`,
`central_management_enabled`), never a different build.

| Mode | Status | Notes |
|---|---|---|
| A. Standalone | Foundation in M0, installation in M1 | One node; `cluster_nodes` holds one row with role `standalone`. |
| B. HA (active/passive) | Design only (see [HA_ARCHITECTURE.md](HA_ARCHITECTURE.md)), M16 | A standalone node is enrolled as primary; a second node joins as secondary. No rebuild. |
| C. Multi-tenant | Data model in M0; activation M14 | Every tenant-owned row carries `organization_id`. Telephony isolation is generated separately (see §6). |
| D. Centrally managed | Identity in M0; M15 | `installation.instance_id` is a permanent UUID. Instances keep working when central management is unreachable. |

Converting standalone to HA works because node roles live in
`cluster_nodes`, not in hostnames, and the instance identity does not change.

## 4. Data model

The full table list is in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md). Key points:

* **Tenancy hierarchy:** installation → organizations → sites → buildings, plus departments; users have a home organization.
* **RBAC:** `roles` + `role_permissions` + `role_assignments(scope_type, organization_id, site_id)`. The scope is enforced by a check constraint. Permissions are registered by core and modules; system roles are synchronized at startup and custom roles are never modified.
* **Audit:** `audit_log` is append-only, enforced by a database trigger: UPDATE is always refused, and DELETE is only allowed inside a transaction that sets `veyra.audit_retention = on`.
* **Telephony objects** (`extensions`, `devices`) are engine-neutral. `extensions.endpoint_name` is globally unique because SIP endpoints share one namespace in the engine.
* **Platform tables:** `installed_modules`, `module_configs`, `update_policies`, `available_updates`, `update_history`, `update_checks`, `cluster_nodes`, `cluster_events`, `config_revisions`, `provisioning_templates`, `system_settings`.
* Migrations are Alembic. CI runs `alembic check` so the models and migrations cannot drift. Modules have their own migration histories (§7).

## 5. API design

* Versioned under `/api/v1`. OpenAPI JSON at `/api/openapi.json`, interactive docs at `/api/docs`.
* Errors use RFC 9457 problem details (`application/problem+json`) with `code`, `errors[]` (field-level) and `request_id`. The request ID is also returned in `X-Request-ID` and recorded in audit events.
* List endpoints return `{items, total, limit, offset}` (limit ≤ 200) and accept `q` filters where useful.
* Every endpoint enforces permissions in the backend. The UI's permission list is advisory only.
* Every state-changing operation writes an audit event, including denied and failed attempts.

## 6. Security architecture

See also [SECURITY.md](../SECURITY.md).

* **Authentication:** local accounts with Argon2id hashes and a 12-character minimum password. Sessions are server-side and only SHA-256 hashes of tokens are stored. The session cookie is HttpOnly, Secure and SameSite=Strict, with a 12-hour absolute lifetime and 60-minute idle timeout. CSRF protection uses a double-submit token (`veyra_csrf` cookie echoed in `X-CSRF-Token`, compared to the hash stored in the session).
* **Brute force:** per-IP sliding window in the API, a per-IP limit in NGINX, and per-account lockout (10 failures → 15 minutes). Failure responses are the same for unknown users and wrong passwords, with equalized timing.
* **First run:** setup is possible only while no user exists and only with a one-time token (24 h) printed on the server console. Concurrent setup attempts are serialized with an advisory lock.
* **Recovery administrator:** the first administrator is flagged `is_recovery_admin` and always authenticates locally, even when SSO is added later.
* **RBAC scopes:** platform, organization and site. Platform-only permissions (module management, updates, HA, settings) cannot be granted at organization scope. Only platform administrators can grant platform roles, and the last platform administrator cannot be removed.
* **Tenant isolation (data):** list and get queries are filtered by `Principal.organization_ids_with(permission)`. An object outside the caller's scope returns 404, not 403, so its existence is not revealed.
* **Tenant isolation (telephony):** a tenant ID on a row does *not* isolate calls. M14 generates per-tenant dialplan contexts, endpoint prefixes, voicemail contexts and recording paths, and isolation tests must pass before multi-tenancy can be enabled.
* **Secrets:** no passwords in configuration files. PostgreSQL uses peer authentication over its local socket. The ARI credential is generated at install and stored mode 0640 root:veyra. SIP secrets will be encrypted at rest with an installation key (M4). The audit log redacts any key containing password/secret/token/key/credential.
* **Exposure:** the API, ARI and PostgreSQL are bound to loopback. AMI is disabled. NGINX listens only on private addresses unless the installer is given `--allow-public-admin`. `verify.sh` checks all of this.
* **Module code:** only signed official modules run inside the core process (§7).
* **Templates:** Jinja2 sandbox with no globals, a restricted loader, validated variables, XML auto-escaping and validated filenames.
* **No shell execution from API input.** Nothing in the API spawns processes. Privileged work (engine configuration, updates) is done by separate services with fixed, validated inputs.

## 7. Modular architecture

Details: [MODULE_DEVELOPMENT.md](MODULE_DEVELOPMENT.md).

* **Core** provides authentication, authorization, tenancy, the database, the module manager, the event bus, API infrastructure, configuration, audit, health and dependency checks.
* **Modules** are directories with a `module.toml` manifest: identity, semantic version, compatibility (`core_api` range against `MODULE_API_VERSION`), dependencies, permissions, configuration fields, migrations, API prefix, declared events, declarative UI views and health checks.
* **Module API v1** (`veyra.sdk`) is the only supported import surface for modules. `ModuleContext` checks that a module only uses what it declared: its own permissions, its declared event patterns, and tables carrying its table prefix.
* **Lifecycle:** available → installed → enabled ⇄ disabled → removed (data retained) → purge (tables dropped; requires typing the module ID). Uninstalling never deletes data silently.
* **Independent upgrades:** each module has its own Alembic history and version table (`alembic_version_<module>`), so one module can be upgraded without touching the core or other modules.
* **Trust and integrity:** packages carry `SHA256SUMS` and an Ed25519 `SIGNATURE`. The trust level (official, community or third_party) is determined by which keyring directory the signing key is in, never by the package itself. Integrity is re-verified each time a module loads, so tampered files are detected.
* **Isolation policy:** only *official* signed modules run in-process. Community and third-party modules must use the `service` runtime: a separate process using a restricted, token-scoped API (planned, M11). Until then they are refused. Unsigned modules load only in non-production environments with `allow_unsigned_modules`.
* **UI extension points are declarative.** Modules contribute navigation entries and `resource_table` views described in the manifest, which the core UI renders. Modules do not inject JavaScript into the administrative origin.
* **Runtime:** the API runs as a single process. Enabling or disabling a module takes effect immediately in that process. Disabled modules' routes return 404. When module code is replaced, the API must be restarted, and the manager reports `restart_required`. Multi-process coordination via PostgreSQL LISTEN/NOTIFY is planned with HA.

## 8. Event system

An in-process event bus (`veyra.core.events`) delivers domain events such as
`organization.created`, `module.enabled` and `example_notes.note_created` to
subscribers matched by glob pattern. Failing handlers are isolated and
logged. Publishers publish after their transaction commits. Cross-process
delivery (worker, deployer, the other HA node) is planned via PostgreSQL
`LISTEN/NOTIFY` with a durable outbox table (M11/M16).

## 9. Telephony adapter

```
Veyra services ─► TelephonyAdapter (capabilities, health, endpoint status,
                  active calls, generate_config, reload)
                     ├─ AsteriskAdapter (M0: health via ARI; M3+: config, status)
                     └─ NullAdapter (no engine configured)
```

Callers check `capabilities()` before using a feature, and anything the
adapter cannot provide is reported as unavailable rather than invented. The
dashboard therefore shows "not available yet" for active calls and
registrations until M5.

## 10. Configuration management

The database is the authoritative source for everything Veyra manages.

```
API request ──► change rows in DB ──► "draft" revision
                                          │  (deployer service, never the HTTP handler)
                                          ▼
          generate files via adapter ─► validate ─► diff vs deployed ─► write to
          /etc/asterisk/veyra/ (atomic) ─► targeted reload (e.g. `pjsip reload`)
          ─► verify (ARI) ─► "deployed"   │ on failure: restore previous files ─► "failed"
```

* `config_revisions` follows the state machine in `veyra/configmgmt/revisions.py`. Transitions are validated, and any superseded revision can be redeployed as a rollback.
* Diffs never show the content of files that contain credentials.
* Reloads are targeted (for example `module reload res_pjsip.so` or `dialplan reload`) to avoid disturbing calls in progress.
* Asterisk reads only generated files and does not depend on Veyra at call time, so telephone service continues if the web application stops.
* Status: the state machine and diff are implemented. Generation and deployment arrive in M3.

## 11. Update management

See [UPDATE_MANAGEMENT.md](UPDATE_MANAGEMENT.md). In summary: per-component
policies (Veyra, modules, templates, telephony engine, OS), four modes, and
channels. Update metadata is signed and protected against freeze and
rollback attacks. Checks never install anything. Unattended installation is
disabled until the executor is tested (M12). `upgrade.sh` already performs
backup → migrate → verify with automatic rollback when a migration fails.

## 12. High availability

See [HA_ARCHITECTURE.md](HA_ARCHITECTURE.md). Active/passive, manual
switchover first, and no automatic failover until fencing and quorum have
been tested.

## 13. Provisioning

See [PROVISIONING_TEMPLATES.md](PROVISIONING_TEMPLATES.md). Official,
community and local templates support inheritance and a sandboxed renderer.
Local overrides never modify official templates.

## 14. Backups and recovery (design)

* **Content:** the database (`pg_dump -Fc`), `/etc/veyra` (including secrets), generated telephony configuration, and later voicemail and recordings under `/var/lib/veyra`.
* **Portability:** dumps are standard PostgreSQL custom format. Configuration is a tarball, so restoring onto a fresh node is install.sh followed by restore.
* **Encryption:** planned with age or OpenSSL, using a key the administrator holds (M17). Plaintext backups stay root-only (0600) under `/var/backups/veyra`.
* **Retention and scheduling:** planned in a Backup module (M17). `upgrade.sh` already takes a backup before every upgrade.
* **Verification:** a restore test into a scratch database before a backup is reported good (M17).

## 15. Observability

* Health is reported at `/api/v1/system/health` (database, engine, modules, host metrics, cluster) and through `veyra status` on the command line.
* Logs go to journald (`journalctl -u veyra-api`) plus installer logs in `/var/log/veyra`.
* Asterisk ships `res_prometheus`; exposing metrics is a later decision (M10).
