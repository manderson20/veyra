# Database Schema

PostgreSQL is the authoritative store. The schema is defined by SQLAlchemy
models (`backend/veyra/core/models/`) and Alembic migrations
(`backend/veyra/migrations/versions/`). CI runs `alembic check` to make sure
the two agree. Constraint names follow a fixed naming convention.

## Core tables (migration `0001`)

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `installation` | Single row: identity of this installation | `instance_id` (permanent UUID for HA and central management), `deployment_mode`, `multi_tenancy_enabled`, `central_management_enabled`, `setup_completed_at` |
| `organizations` | Tenants | `slug` unique, `timezone`, `is_active` |
| `sites` | Locations of an organization | `organization_id`, unique (`organization_id`, `slug`), civic address (future dispatchable location) |
| `buildings` | Buildings at a site | `site_id`, unique (`site_id`, `name`) |
| `departments` | Departments | unique (`organization_id`, `name`) |
| `users` | Accounts | `email` unique (stored lower-case), `password_hash` (Argon2id, NULL for SSO-only), `auth_source`, `is_recovery_admin`, `home_organization_id`, lockout fields |
| `permissions` | Permission catalog (core + modules) | `key` PK, `module_id` |
| `roles` | System and custom roles | unique (`organization_id`, `key`); `is_system` |
| `role_permissions` | Role → permission | composite PK |
| `role_assignments` | User ↔ role in a scope | `scope_type` ∈ platform/organization/site, with a check constraint for consistent scope columns |
| `sessions` | Server-side sessions | `token_hash` unique, `csrf_token_hash`, `expires_at`, `last_seen_at`, `revoked_at` |
| `audit_log` | Append-only audit trail | indexed by time and organization; **UPDATE/DELETE blocked by trigger** `audit_log_append_only` (DELETE allowed only with `SET LOCAL veyra.audit_retention='on'`) |
| `system_settings` | Key/value settings | e.g. `setup.token` (hash plus expiry), `updates.metadata_sequence` |
| `extensions` | Extensions (engine-neutral) | unique (`organization_id`, `number`); `endpoint_name` globally unique; `sip_secret_ciphertext` |
| `devices` | Phones | `mac_address` unique (12 hex digits), `template_key`, `primary_extension_id` |
| `installed_modules` | Module registry | `module_id` PK, `version`, `state`, `trust_level`, `signature_verified`, `manifest` (JSONB) |
| `module_configs` | Module configuration | unique (`module_id`, `organization_id`) |
| `update_policies` | Update policy per component | `component` PK, `mode`, `channel`, window, categories |
| `available_updates` | Updates found by checks | unique (`component`, `target`, `version`), `state` |
| `update_history` | Applied updates | versions, outcome, `backup_ref`, `node_id` |
| `update_checks` | Check log | outcome: ok / not_configured / failed / rejected |
| `cluster_nodes` | Nodes and their **dynamic roles** | `node_name` unique, `role`, `state`, `last_heartbeat_at` |
| `cluster_events` | Switchover and role change history | |
| `config_revisions` | Generated engine configuration revisions | `sequence` (identity), `state`, `content_hash`, `parent_id` |
| `provisioning_templates` | Local and community templates | unique (`template_key`, `version`), `source`, `manifest`, `files` |

Tenant-owned tables (`sites`, `buildings`, `departments`, `extensions`,
`devices`) carry `organization_id` with `ON DELETE RESTRICT`, so deleting an
organization never silently removes telephony data.

## Module tables

Each module owns tables prefixed `mod_<name>_` and its own version table
`alembic_version_<module id>`. Example: `mod_example_notes_note`.

## Planned

* Row-level security policies as defense in depth for tenant isolation (M14).
* CDR and CEL tables populated by Asterisk `cdr_pgsql` / `cel_pgsql` (M10).
* An outbox table for cross-process events (M11/M16).
