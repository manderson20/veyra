# Database Schema

PostgreSQL is the authoritative store. The schema is defined by SQLAlchemy
models (`backend/veyra/core/models/`) and Alembic migrations
(`backend/veyra/migrations/versions/`). CI runs `alembic check` to make sure
the two agree. Constraint names follow a fixed naming convention.

## Core tables (migration `0001`)

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `installation` | Single row: identity of this installation | `instance_id` (permanent UUID for HA and central management), `deployment_mode`, `multi_tenancy_enabled`, `central_management_enabled`, `setup_completed_at` |
| `organizations` | Tenants | `slug` unique, `timezone`, `is_active`; `provisioning_user`, `provisioning_secret_ciphertext` (migration `0011`: the enrollment credential, purpose `organization.provisioning_secret:<id>`) |
| `sites` | Locations of an organization | `organization_id`, unique (`organization_id`, `slug`), civic address (future dispatchable location); `emergency_caller_id_number` (migration `0011`, default for the site's extensions) |
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
| `extensions` | Extensions (engine-neutral) | unique (`organization_id`, `number`); `endpoint_name` globally unique (`<org slug>-<number>`); numbers also unique installation-wide (enforced by the API with an advisory lock until M14); `sip_secret_ciphertext` (AES-256-GCM token, installation key) and `sip_secret_changed_at` (migration `0003`); `emergency_caller_id_number` (migration `0010`, presented on emergency routes) |
| `devices` | Phones registered by MAC address (migration `0011` adds the Milestone 9 columns; [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §2) | `mac_address` unique (12 hex digits), `profile_id` (`SET NULL`), `primary_extension_id` (`SET NULL`), `lines` (JSONB extra registrations), `keys` (JSONB line keys, NULL = the profile's), `values` (JSONB overrides), `firmware_image_id`, `provisioning_secret_ciphertext` (installation key, purpose `device.provisioning_secret:<id>`), `last_seen_*`, `last_result`, `firmware_reported`, `is_enabled` |
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
| `inbound_routes` | DID → destination (migration `0006`; typed destinations in `0008`) | `did` as the carrier sends it, `did_canonical` (ten digits for North American numbers); unique (`trunk_id`, `did_canonical`) with NULLs not distinct; `destination_type` (`extension`/`voicemail`/`ivr`) with `destination_extension_id` or `destination_ivr_id`, `destination_ring_group_id`, `destination_queue_id` (migration `0009`) (`SET NULL`), the same three for `after_hours_*`, `time_condition_id` and `trunk_id` (`RESTRICT`), `caller_id_prefix` |
| `outbound_routes` | Dial patterns → trunks (migration `0006`) | `name` and `slug` unique (`veyra-out-<slug>`); `position` (evaluation order), `is_emergency`, `patterns` (JSONB `{prefix, match, prepend}`), `caller_id_number` |
| `outbound_route_trunks` | Ordered trunks of a route | PK (`route_id`, `trunk_id`), unique (`route_id`, `position`); route `CASCADE`, trunk `RESTRICT` |
| `api_tokens` | Scoped bearer tokens (migration `0007`, M6b, ADR 0015) | `token_hash` unique (SHA-256), `kind` (`companion`), `label` (device), `scopes` (JSONB permission keys), `created_at`/`created_ip`, `expires_at` (idle expiry, extended on use), `last_used_at`/`last_used_ip`, `revoked_at`; user `CASCADE` |
| `user_preferences` | Per-user settings document (migration `0007`) | `user_id` PK, `data` (JSONB; `companion` section: speed dials, dial prefix, default extension, notification toggles), `updated_at` |
| `voicemail_boxes` | One voicemail box per extension, or a shared inbox without one (migration `0008`, M7; `0016`, M9c) | `extension_id` unique, nullable (`CASCADE`), `organization_id` (`RESTRICT`), `number` (unique; shared inboxes only, shared number space) and `name`, `pin_ciphertext` (installation key, purpose `voicemail.pin:<box id>`), `email`, `attach_audio`, `delete_after_email`, `ring_seconds`, `is_enabled` |
| `voicemail_box_members` | Extensions whose message lamp follows a shared inbox (migration `0016`, M9c) | PK (`box_id`, `extension_id`), both `CASCADE` |
| `prompts` | The audio library (migration `0008`; `kind`, `license`, `credit` in `0013`, M9c) | unique (`organization_id`, `slug`) — the file is `<data>/prompts/<org slug>/<slug>.wav`; `name`, `description`, `source` (`upload`/`recording`), `duration_seconds`, `size_bytes` |
| `ivr_menus` | Auto-attendant menus (migration `0008`) | unique (`organization_id`, `name`) and `slug` unique (`veyra-ivr-<slug>`); `prompt_id`, `invalid_prompt_id` (`SET NULL`), `timeout_seconds`, `max_retries`, `allow_direct_dial`, `timeout_type`/`timeout_extension_id`/`timeout_ivr_id`/`timeout_ring_group_id`/`timeout_queue_id` and `invalid_*` (typed fallbacks, `SET NULL`; the group and queue columns from migration `0009`), `is_enabled` |
| `ivr_entries` | One key of a menu (migration `0008`) | PK (`menu_id`, `digit`), menu `CASCADE`; `destination_type` with `destination_extension_id`, `destination_ivr_id`, `destination_ring_group_id` or `destination_queue_id` (`SET NULL`; the last two from migration `0009`) |
| `ring_groups` | A number that rings several extensions (migration `0009`, M8) | unique (`organization_id`, `name`), `slug` unique (context `veyra-rg-<slug>`), `number` unique (shared number space with extensions and queues); `strategy` (`ringall`/`sequential`), `ring_seconds`, `ring_busy_members`, `caller_id_prefix`, `failover_type` with `failover_extension_id`/`failover_ivr_id`/`failover_ring_group_id`/`failover_queue_id` (`SET NULL`; the queue side is added after both tables exist), `is_enabled` |
| `ring_group_members` | Ordered members (migration `0009`) | PK (`group_id`, `extension_id`), both `CASCADE`; unique (`group_id`, `position`) |
| `call_queues` | A number that queues callers for agents (migration `0009`) | unique (`organization_id`, `name`), `slug` unique (queue `veyra-<slug>`, context `veyra-queue-<slug>`), `number` unique; `strategy`, `member_timeout`, `retry_seconds`, `wrapup_seconds`, `max_wait_seconds`, `max_callers`, `join_when_empty`, `announce_position`, `announce_frequency`, `announcement_prompt_id`, `periodic_prompt_id` (`SET NULL`), `periodic_seconds`, `music`, `failover_*` as ring groups, `is_enabled` |
| `queue_members` | Agents (migration `0009`) | PK (`queue_id`, `extension_id`), both `CASCADE`; `penalty` |
| `pickup_groups` | Extensions that may answer each other's calls (migration `0009`) | unique (`organization_id`, `name`), `slug` unique (the Asterisk named group); `description` |
| `pickup_group_members` | Membership (migration `0009`) | PK (`group_id`, `extension_id`), both `CASCADE` |
| `paging_zones` | Multicast page groups (migration `0011`, M9; [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §5) | unique (`organization_id`, `name`), (`organization_id`, `slug`), (`organization_id`, `poly_group`); `multicast_address`/`multicast_port` (speakers), `poly_address`/`poly_port`/`poly_group` (phones), `kind`, `codec`, `site_id` (`SET NULL`), `is_enabled` |
| `device_profiles` | Template family or model plus values, keys and firmware (migration `0011`) | unique (`organization_id`, `name`); `template_key`, `values` (JSONB), `keys` (JSONB), `site_id`, `firmware_image_id` (`SET NULL`) |
| `device_profile_paging` | Zone memberships of a profile (migration `0011`) | PK (`profile_id`, `zone_id`), both `CASCADE`; `subscribed`, `transmit`, `role` (`none`/`default`/`priority`/`emergency`) |
| `firmware_images` | Uploaded vendor firmware (migration `0011`) | unique (`manufacturer`, `version`, `filename`); `models` (JSONB), `size`, `sha256`, `uploaded_by` (`SET NULL`); file at `<data>/firmware/<id>/<filename>` |
| `provisioning_requests` | Log of phone requests (migration `0011`) | `at` and `mac` indexed; `filename`, `method`, `ip_address`, `user_agent`, `organization_id`/`device_id` (`SET NULL`), `result`, `status`; pruned after 30 days by the worker |
| `call_samples` | Engine readings for the dashboard graphs (migration `0012`, M9b; [INTERFACE_REWORK.md](INTERFACE_REWORK.md) §2) | `at` indexed; `channels`, `calls_internal`, `calls_external`, `registrations`; one row per worker iteration (30 s), pruned after 14 days |
| `paging_zone_members` | Phones allowed to page a zone whose `allowed` is `members` (migration `0014`, M9c) | PK (`zone_id`, `extension_id`), both `CASCADE`; `paging_zones` gains `number` (unique, shared number space), `allowed`, `max_seconds` |
| `pages` | A page over zones (migration `0014`; [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §1) | unique (`organization_id`, `name`) and (`organization_id`, `slug`); `number` unique (shared number space), `audio_id` (`prompts`, `SET NULL`; NULL = live), `pre_tone`, `repeat`, `priority`, `allowed`, `max_seconds`, `is_enabled` |
| `page_zones`, `page_members` | Zones of a page; phones allowed to start it (migration `0014`) | composite PKs, `CASCADE` |
| `page_log` | Every page started (migration `0014`) | `at` indexed; `page_id` (`SET NULL`), `page_name`, `zones` (JSONB slugs), `trigger` (`dial`/`api`/`bell`/`ui`), `actor`, `outcome`, `detail`; pruned after 90 days |
| `calendars` | iCal subscriptions for bells (migration `0015`; [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §4) | unique (`organization_id`, `name`); `url_ciphertext` (installation key, purpose `calendar.url:<id>`), `url_display`, `poll_minutes`, `timezone`, `last_polled_at`/`last_status`/`last_error`, `event_count` |
| `calendar_events` | Cached occurrences of the next 48 hours (migration `0015`) | unique (`calendar_id`, `uid`, `starts_at`); `summary`, `ends_at`, `all_day`; replaced at every poll |
| `bell_schedules` | Calendar → page (migration `0015`) | unique (`organization_id`, `name`); `calendar_id` and `page_id` `CASCADE`; `match` (glob on the title), `trigger` (`start`/`end`/`both`), `tolerance_seconds`, `all_day_events`, `is_enabled` |
| `bell_rings` | Ring-once guard and history (migration `0015`) | unique (`schedule_id`, `event_key`); `due_at`, `rang_at`, `outcome`, `detail`; pruned after 90 days |
| *destination columns* | Shared inbox targets (migration `0016`, M9c) | `inbound_routes.destination_voicemail_box_id` / `after_hours_voicemail_box_id`, `ivr_menus.timeout_voicemail_box_id` / `invalid_voicemail_box_id`, `ivr_entries.destination_voicemail_box_id`, `ring_groups.failover_voicemail_box_id`, `call_queues.failover_voicemail_box_id`; all `SET NULL` |

Tenant-owned tables (`sites`, `buildings`, `departments`, `extensions`,
`devices`, `device_profiles`, `paging_zones`, `inbound_routes`, `time_conditions`) carry `organization_id` with `ON DELETE RESTRICT`, so deleting an
organization never silently removes telephony data.

## Module tables

Each module owns tables prefixed `mod_<name>_` and its own version table
`alembic_version_<module id>`. Example: `mod_example_notes_note`.

## Planned

* Row-level security policies as defense in depth for tenant isolation (M14).
* CDR and CEL tables populated by Asterisk `cdr_pgsql` / `cel_pgsql` (M10).
* An outbox table for cross-process events (M11/M16).
