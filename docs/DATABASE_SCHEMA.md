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
| `users` | Accounts | `email` unique (stored lower-case), `password_hash` (Argon2id, NULL for SSO-only), `auth_source`, `is_recovery_admin`, `home_organization_id`, lockout fields, `password_changed_at` and `must_change_password` (migration `0002`), `mfa_required_at` and `mfa_grace_until` (migration `0004`) |
| `permissions` | Permission catalog (core + modules) | `key` PK, `module_id` |
| `roles` | System and custom roles | unique (`organization_id`, `key`); `is_system` |
| `role_permissions` | Role → permission | composite PK |
| `role_assignments` | User ↔ role in a scope | `scope_type` ∈ platform/organization/site, with a check constraint for consistent scope columns |
| `sessions` | Server-side sessions | `token_hash` unique, `csrf_token_hash`, `expires_at`, `last_seen_at`, `revoked_at`, `ip_address`, `user_agent`; `mfa_verified_at` (NULL = pre-authentication session) and `mfa_failures` (migration `0004`); rows past retention are deleted by the worker |
| `mfa_methods` | Second factors (migration `0004`) | `type` (`totp`), `label`, `secret_ciphertext` (installation key), `credential` (WebAuthn, later), `last_used_step` (replay protection), `confirmed_at` |
| `mfa_recovery_codes` | Single-use recovery codes (migration `0004`) | `code_hash` (Argon2id), `used_at` |
| `password_reset_tokens` | One-time password reset links (migration `0002`) | `token_hash` unique, `expires_at`, `used_at`, `issued_by` (administrator email or `cli`), `issued_from_ip`; at most one unused token per user |
| `audit_log` | Append-only audit trail | indexed by time and organization; **UPDATE/DELETE blocked by trigger** `audit_log_append_only` (DELETE allowed only with `SET LOCAL veyra.audit_retention='on'`) |
| `system_settings` | Key/value settings | e.g. `setup.token` (hash plus expiry), `updates.metadata_sequence`, `telephony.sip` (SIP and media settings, M3), `telephony.numbering` (numbering plan, M4), `telephony.pending_change` (set by any engine-relevant save until the next deployment), `security.mfa` (two-factor policy, M4b) |
| `extensions` | Extensions (engine-neutral) | unique (`organization_id`, `number`); `endpoint_name` globally unique (`<org slug>-<number>`); numbers also unique installation-wide (enforced by the API with an advisory lock until M14); `sip_secret_ciphertext` (AES-256-GCM token, installation key) and `sip_secret_changed_at` (migration `0003`) |
| `devices` | Phones | `mac_address` unique (12 hex digits), `template_key`, `primary_extension_id` |
| `installed_modules` | Module registry | `module_id` PK, `version`, `state`, `trust_level`, `signature_verified`, `manifest` (JSONB) |
| `module_configs` | Module configuration | unique (`module_id`, `organization_id`) |
| `update_policies` | Update policy per component | `component` PK, `mode`, `channel`, window, categories |
| `available_updates` | Updates found by checks | unique (`component`, `target`, `version`), `state` |
| `update_history` | Applied updates | versions, outcome, `backup_ref`, `node_id` |
| `update_checks` | Check log | outcome: ok / not_configured / failed / rejected |
| `cluster_nodes` | Nodes and their **dynamic roles** | `node_name` unique, `role`, `state`, `last_heartbeat_at` |
| `cluster_events` | Switchover and role change history | |
| `config_revisions` | Generated engine configuration revisions | `sequence` (identity), `state`, `content_hash`, `parent_id`; `artifacts` holds non-sensitive files in clear and sensitive files as `ciphertext` (installation key, M4); `deploy_mode` (`now`/`when_idle`) and `deploy_requested_at` (migration `0005`, M5) |
| `provisioning_templates` | Local and community templates | unique (`template_key`, `version`), `source`, `manifest`, `files` |
| `sip_trunks` | Carrier connections (migration `0006`, M6) | `name` and `slug` unique (`trunk-<slug>` in the engine); `auth_mode` (`registration`/`ip`), host, port, transport, `password_ciphertext` (installation key), `match_addresses` (JSONB), codecs, `max_channels`, caller-ID and DTMF options, qualify and registration intervals |
| `time_conditions` | Opening hours per organization (migration `0006`) | unique (`organization_id`, `name`); `timezone`, `ranges` (JSONB weekly ranges), `holidays` (JSONB `MM-DD`) |
| `inbound_routes` | DID → destination (migration `0006`) | `did` as the carrier sends it, `did_canonical` (ten digits for North American numbers); unique (`trunk_id`, `did_canonical`) with NULLs not distinct; `destination_extension_id` and `after_hours_extension_id` (`SET NULL`), `time_condition_id` and `trunk_id` (`RESTRICT`), `caller_id_prefix` |
| `outbound_routes` | Dial patterns → trunks (migration `0006`) | `name` and `slug` unique (`veyra-out-<slug>`); `position` (evaluation order), `is_emergency`, `patterns` (JSONB `{prefix, match, prepend}`), `caller_id_number` |
| `outbound_route_trunks` | Ordered trunks of a route | PK (`route_id`, `trunk_id`), unique (`route_id`, `position`); route `CASCADE`, trunk `RESTRICT` |

Tenant-owned tables (`sites`, `buildings`, `departments`, `extensions`,
`devices`, `inbound_routes`, `time_conditions`) carry `organization_id` with `ON DELETE RESTRICT`, so deleting an
organization never silently removes telephony data.

## Module tables

Each module owns tables prefixed `mod_<name>_` and its own version table
`alembic_version_<module id>`. Example: `mod_example_notes_note`.

## Planned

* Row-level security policies as defense in depth for tenant isolation (M14).
* CDR and CEL tables populated by Asterisk `cdr_pgsql` / `cel_pgsql` (M10).
* An outbox table for cross-process events (M11/M16).
