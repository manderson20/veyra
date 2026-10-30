// SPDX-License-Identifier: AGPL-3.0-or-later
/** API response types (mirrors backend/veyra/api/v1). */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_recovery_admin: boolean;
  auth_source: string;
  home_organization_id: string | null;
  last_login_at: string | null;
  created_at: string;
  locked_until: string | null;
  password_changed_at: string | null;
  must_change_password: boolean;
  mfa_enabled: boolean;
}

export interface MfaStatus {
  enabled: boolean;
  required: boolean;
  grace_until: string | null;
  methods: number;
  recovery_codes_remaining: number;
}

export interface SessionInfo {
  user: User;
  permissions: string[];
  is_platform_admin: boolean;
  installation_name: string;
  must_change_password: boolean;
  csrf_token?: string | null;
  version: string;
  release: string | null;
  mfa: MfaStatus;
}

export interface MfaMethod {
  id: string;
  type: string;
  label: string;
  created_at: string | null;
  last_used_at: string | null;
}

/** Returned by sign-in (HTTP 202) while the second factor is pending. */
export interface MfaChallenge {
  mfa_pending: boolean;
  enrol: boolean;
  methods: MfaMethod[];
  email: string;
  display_name: string;
  expires_at: string;
  /** "Trust this browser for N days" (#137); 0: not offered. */
  trust_days?: number;
}

export interface TotpBegin {
  method_id: string;
  secret: string;
  uri: string;
  qr_svg: string;
  expires_at: string | null;
}

export interface TotpConfirm {
  method: MfaMethod;
  recovery_codes: string[];
  session: SessionInfo;
}

export interface MfaMethods {
  status: MfaStatus;
  methods: MfaMethod[];
  allowed_methods: string[];
}

export interface MfaPolicy {
  required_for: string[];
  grace_days: number;
  /** Days a browser may skip the second factor; 0: never (#137). */
  trusted_browser_days?: number;
  allowed_methods: string[];
}

export interface MfaPolicyOut {
  policy: MfaPolicy;
  roles: { key: string; name: string }[];
}

export interface UserSession {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip_address: string | null;
  user_agent: string | null;
  is_current: boolean;
}

/** How the Companion extension can be installed on this server (docs/COMPANION.md §5). */
export interface CompanionInfo {
  available: boolean;
  name: string | null;
  version: string | null;
  extension_id: string | null;
  zip_url: string | null;
  crx_url: string | null;
  update_url: string | null;
  install_sources_pattern: string | null;
}

/** What the Companion rollout guide needs (System → Companion rollout). */
export interface CompanionRollout {
  info: CompanionInfo;
  host: string;
  origin: string;
  certificate: { kind: "public" | "veyra"; names: string[]; issuer: string | null; not_after: string | null };
  ca_url: string;
  adoption: {
    users: number;
    active_7d: number;
    recent: { email: string; display_name: string; device: string; created_at: string; last_used_at: string | null }[];
  };
}

/** A scoped bearer token (Companion extension), ADR 0015. */
export interface ApiToken {
  id: string;
  kind: string;
  label: string;
  scopes: string[];
  created_at: string;
  created_ip: string | null;
  expires_at: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  is_current: boolean;
}

export interface PasswordResetLink {
  token: string;
  path: string;
  expires_at: string;
}

export interface ResetTokenInfo {
  display_name: string;
  email: string;
  expires_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  is_active: boolean;
  /** Default hold music set of the organization's phones; null = the built-in set. */
  moh_class_id?: string | null;
  /** The plain-HTTP trust bootstrap also carries the enrollment credential. */
  bootstrap_includes_credential?: boolean;
  /** Numbers extensions may present as outbound caller ID besides the organization's DIDs. */
  caller_id_allow_list?: string[];
  /** Intercom default for the organization's phones: allow or deny. */
  intercom_default?: "allow" | "deny" | string;
  /** Who may answer with **<extension> (#138). */
  directed_pickup?: "organization" | "group" | string;
  /** Callers who ring every phone through Do Not Disturb (#170). */
  dnd_allow?: string[];
  /** Both sides hear a beep when a supervisor starts monitoring (#167). */
  monitor_beep?: boolean;
  /** Users may play recordings of their own calls from My Phone (docs/USER_PORTAL.md §5). */
  users_play_own_recordings?: boolean;
  fax_header?: string | null;
  fax_station_id?: string | null;
  /** Prefix of the organization's engine names; empty: today's names. */
  engine_namespace?: string;
  created_at: string;
}

export interface Role {
  id: string;
  key: string;
  name: string;
  description: string;
  is_system: boolean;
}

export interface RoleAssignment {
  id: string;
  role_key: string;
  role_name: string;
  scope_type: "platform" | "organization" | "site";
  organization_id: string | null;
  organization_name: string | null;
  site_id: string | null;
}

export interface SetupStep {
  key: string;
  title: string;
  available: boolean;
  /** Set up after the wizard, here. */
  after?: string;
}

export interface SetupStatus {
  setup_required: boolean;
  token_issued: boolean;
  steps: SetupStep[];
  telephony_engine: string;
  telephony_state: string;
}

export interface EngineModule {
  name: string;
  status: string;
}

export interface EngineStatus {
  engine: string;
  state: string;
  version: string | null;
  message: string;
  capabilities: string[];
  started_at: string | null;
  last_reload_at: string | null;
  entity_id: string | null;
  modules: EngineModule[];
  endpoints_total: number | null;
  endpoints_registered: number | null;
  active_channels: number | null;
  config_dir: string | null;
  deployed_revision: number | null;
  pending_revision: number | null;
  /** The database differs from the deployed configuration (null: no generation). */
  changes_pending: boolean | null;
  pending_since: string | null;
  pending_by: string | null;
  installation_key_present: boolean;
  pending_mode: "now" | "when_idle" | null;
  pending_requested_at: string | null;
  pending_active_calls: number | null;
  active_calls: number | null;
}

export type DeployMode = "now" | "when_idle";

export interface ActiveCall {
  channel_id: string;
  caller: string | null;
  callee: string | null;
  state: string;
  duration_seconds: number;
  endpoint: string | null;
  extension_number: string | null;
  extension_name: string | null;
  recording: boolean;
  recording_stoppable: boolean;
}

export interface ActiveCalls {
  calls: ActiveCall[];
  available: boolean;
  message: string | null;
}

export interface OriginateResult {
  channel_id: string;
  extension_number: string;
  number: string;
  message: string;
}

/** One registered contact and where it registers from (docs/CALL_FEATURES.md §2.1). */
export interface RegistrationContact {
  uri: string;
  /** The address the phone put in its Contact header (its own, often private). */
  contact_host: string | null;
  contact_port: number | null;
  /** Where the registration actually arrived from (public behind NAT). */
  source_host: string | null;
  source_port: number | null;
  nat: boolean;
  transport: string | null;
  user_agent: string | null;
  expires_at: string | null;
  status: string | null;
  rtt_ms: number | null;
}

export interface Registration {
  registered: boolean;
  channels: number;
  contacts: RegistrationContact[];
}

export interface RegistrationRow extends RegistrationContact {
  endpoint: string;
  extension_id: string | null;
  extension_number: string | null;
  extension_name: string | null;
  organization_id: string | null;
  organization_name: string | null;
  /** Phones registered on this endpoint and how many it accepts (null for an unknown endpoint). */
  registered?: number;
  registration_limit?: number | null;
}

export interface TrunkRegistrationRow {
  trunk_id: string;
  name: string;
  slug: string;
  host: string;
  status: string | null;
  state: "registered" | "rejected" | "registering" | "unregistered" | "online" | "offline" | "unknown" | string;
  reachable: boolean | null;
}

export interface Registrations {
  registrations: RegistrationRow[];
  available: boolean;
  message: string | null;
  unregistered: number;
  /** Registration trunks and how their registration stands (platform administrators). */
  trunks?: TrunkRegistrationRow[];
}

export interface ApplyResult {
  revision: ConfigRevision;
  applied: boolean;
  unchanged: boolean;
}

export interface NumberingPlan {
  extension_length: number;
  first_extension: string;
  last_extension: string;
  reserved_prefixes: string[];
}

export interface NumberingOut {
  plan: NumberingPlan;
  problems: string[];
  description: string;
}

export interface Extension {
  id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  number: string;
  display_name: string;
  endpoint_name: string;
  user_id: string | null;
  user_display_name: string | null;
  user_email: string | null;
  caller_id_name: string | null;
  caller_id_number: string | null;
  /** Presented on emergency routes instead of the regular caller ID (the building's ELIN or DID). */
  emergency_caller_id_number: string | null;
  /** Presented on trunk calls: one of the organization's numbers or an allowed number (CALL_FEATURES.md §3.5). */
  outbound_caller_id_number?: string | null;
  outbound_caller_id_name?: string | null;
  /** Do Not Disturb (CALL_FEATURES.md §3.2); the full state is at /extensions/{id}/state. */
  dnd?: boolean;
  /** Intercom (CALL_FEATURES.md §3.6): may other phones make this one answer on speaker? */
  intercom?: "default" | "allow" | "deny" | string;
  /** A fax machine on an ATA port: T.38 offered to it (PROVISIONING_BREADTH.md §4.4). */
  fax_t38?: boolean;
  /** Class of service (CALL_FEATURES.md §3.8); null: everything allowed. */
  class_of_service_id?: string | null;
  class_of_service_name?: string | null;
  /** Phones that may register at once (EXTENSIONS.md §1); null: as many as are provisioned, at least one. */
  max_registrations?: number | null;
  /** Enabled devices provisioned with this extension. */
  provisioned_phones?: number;
  /** The effective limit: the larger of max_registrations and provisioned_phones, at least 1. */
  registration_limit?: number;
  /** The site the phone is at (its emergency route and caller ID); a building implies its site. */
  site_id?: string | null;
  site_name?: string | null;
  building_id?: string | null;
  building_name?: string | null;
  location?: string | null;
  /** Groups extensions for My Phone layout templates. */
  department_id?: string | null;
  department_name?: string | null;
  /** Hotline (issue #168): dialled when the handset is lifted, after hotline_delay seconds. */
  hotline_target?: string | null;
  hotline_delay?: number;
  /** The extension template it follows (issue #172) and the fields it locks. */
  template_id?: string | null;
  template_name?: string | null;
  locked_fields?: string[];
  is_enabled: boolean;
  sip_secret_set: boolean;
  sip_secret_changed_at: string | null;
  created_at: string;
  updated_at: string;
  registration: Registration | null;
  /** Groups the extension belongs to (docs/RING_GROUPS_QUEUES.md). */
  ring_groups: Membership[];
  queues: Membership[];
  pickup_groups: Membership[];
}

/** A ring group, queue or pickup group an extension belongs to. */
export interface Membership {
  id: string;
  name: string;
  number: string | null;
}

export interface SipCredentials {
  extension_id: string;
  number: string;
  username: string;
  secret: string;
  udp_port: number;
  tcp_port: number | null;
  tls_port: number | null;
  rotated_at: string | null;
}

export interface NextNumber {
  number: string | null;
  plan: string;
  message: string | null;
}

export interface SipSettings {
  bind_address: string;
  udp_port: number;
  tcp_enabled: boolean;
  tcp_port: number;
  tls_enabled: boolean;
  tls_port: number;
  tls_certificate: "veyra" | "public";
  external_signaling_address: string | null;
  external_media_address: string | null;
  local_nets: string[];
  rtp_start: number;
  rtp_end: number;
  codecs: string[];
  default_language: string;
}

export interface SipSettingsOut {
  settings: SipSettings;
  problems: string[];
  codecs_available: string[];
}

export interface RevisionFile {
  path: string;
  sensitive: boolean;
  content: string | null;
  lines: number;
}

export interface FileDiff {
  changed: boolean;
  diff: string | null;
  sensitive: boolean;
}

export type RevisionState = "draft" | "validated" | "deploying" | "deployed" | "failed" | "superseded" | "rolled_back";

export interface ConfigRevision {
  id: string;
  sequence: number;
  engine: string;
  state: RevisionState;
  summary: string;
  content_hash: string | null;
  created_by: string;
  created_at: string;
  deployed_at: string | null;
  parent_sequence: number | null;
  validation_errors: string[];
  files: RevisionFile[];
  diff: Record<string, FileDiff> | null;
  unchanged: boolean | null;
  can_deploy: boolean;
  can_rollback: boolean;
  deploy_mode: "now" | "when_idle" | null;
  deploy_requested_at: string | null;
}

export type HealthStatus = "ok" | "degraded" | "failed" | "unknown";

export interface HealthComponent {
  status: HealthStatus;
  message: string;
  details: Record<string, unknown>;
}

export interface HostMetrics {
  cpu_percent: number | null;
  load_average: number[] | null;
  cpu_count: number | null;
  memory_total_bytes: number | null;
  memory_available_bytes: number | null;
  memory_percent: number | null;
  disk_path: string;
  disk_total_bytes: number | null;
  disk_free_bytes: number | null;
  disk_percent: number | null;
  uptime_seconds: number | null;
}

export interface ClusterNode {
  id: string;
  node_name: string;
  hostname: string;
  address: string | null;
  role: string;
  state: string;
  last_heartbeat_at: string | null;
  software_version: string | null;
  // Milestone 16 (docs/HIGH_AVAILABILITY.md §11)
  fingerprint?: string | null;
  epoch?: number;
  db_role?: string;
  replication?: HaReplication;
  sync_at?: string | null;
  holds_address?: boolean;
  stale?: boolean;
}

export interface ClusterStatus {
  deployment_mode: string;
  ha_enabled: boolean;
  automatic_failover: boolean;
  automatic_failover_reason: string;
  database_role: string | null;
  replication: HaReplication | { state: string } | null;
  nodes: ClusterNode[];
  /** healthy | degraded | isolated | standalone (dashboard tile). */
  summary?: string;
  local_role?: string | null;
  local_state?: string | null;
}

// ----------------------------------------------------------------- high availability (Milestone 16)

export interface HaReplication {
  db_role?: string;
  state?: string | null;
  receiver?: string | null;
  slot?: string | null;
  lag_bytes?: number | null;
  lag_seconds?: number | null;
  current_lsn?: string | null;
  replay_lsn?: string | null;
  replay_at?: string | null;
  synchronous?: boolean;
  detail?: string;
}

export interface HaStep {
  name: string;
  status: "running" | "ok" | "failed" | "skipped";
  started_at: string;
  finished_at: string | null;
  detail: string;
  seconds: number | null;
}

export interface HaOperation {
  kind: string;
  target: string;
  actor: string;
  status: "running" | "completed" | "aborted" | "failed";
  started_at: string;
  finished_at: string | null;
  error: string;
  steps: HaStep[];
}

export interface HaService {
  name: string;
  address: string;
  prefix: number;
  interface: string;
  synchronous: boolean;
  holder: string | null;
}

export interface HaStatus extends ClusterStatus {
  version: string;
  epoch: number;
  local: {
    node_name: string;
    role: string;
    epoch: number;
    state: string;
    db_role: string;
    holds_address: boolean;
    agent: boolean;
    peer_reachable: boolean | null;
    frozen: boolean;
  };
  peer: ClusterNode | null;
  replication: HaReplication | null;
  sync: { last_success_at: string | null; last_attempt_at: string | null; last_error: string; backlog: number; recordings: boolean } | null;
  service: HaService;
  operation: HaOperation | null;
  fencing: { configured: boolean; method: string };
}

export interface HaEvent {
  id: number;
  occurred_at: string;
  event_type: string;
  node_name: string | null;
  actor_label: string;
  details: Record<string, unknown>;
}

export interface HaJoinToken {
  id: string;
  label: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  used_by: string | null;
  expired?: boolean;
}

export interface HaJoinTokenCreated extends HaJoinToken {
  token: string;
  primary_url: string;
  fingerprint: string | null;
  command: string;
}

export interface HaFencing {
  enabled: boolean;
  method: string;
  url: string;
  token_id: string;
  pve_node: string;
  vms: Record<string, { vmid: number; pve_node?: string }>;
  verify_tls: boolean;
  ca_pem: string;
  has_secret: boolean;
}

export interface HaSwitchoverCheck {
  target: string;
  ok: boolean;
  problems: string[];
}

export interface ModuleHealthRow {
  module_id: string;
  state: string;
  health: HealthStatus;
  message: string;
}

export interface SystemHealth {
  status: HealthStatus;
  version: string;
  components: {
    database: HealthComponent;
    telephony: HealthComponent;
    modules: HealthComponent;
    [k: string]: HealthComponent;
  };
  host: HostMetrics;
  cluster: ClusterStatus;
  active_calls: number | null;
  registrations: number | null;
  /** False when these counts cover the whole server and are not shown to you. */
  server_counts: boolean;
  trunks: { total: number; up: number; known: number } | null;
}

export interface SystemInfo {
  name: string | null;
  instance_id: string | null;
  deployment_mode: string | null;
  multi_tenancy_enabled: boolean;
  central_management_enabled: boolean;
  version: string;
  module_api_version: string;
}

export interface SearchResult {
  type: string;
  id: string;
  title: string;
  subtitle: string;
  href: string;
}

export interface ModuleInfo {
  module_id: string;
  name: string | null;
  description: string | null;
  author: string | null;
  license: string | null;
  installed_version: string | null;
  available_version: string | null;
  update_available: boolean;
  state: "available" | "installed" | "enabled" | "disabled" | "failed" | "removed";
  trust_level: "official" | "community" | "third_party" | "unsigned";
  signature_verified: boolean;
  verification_error: string | null;
  compatible: boolean;
  problems: string[];
  dependencies: { id: string; version: string; optional: boolean }[];
  permissions: { key: string; description: string; default_roles?: string[] }[];
  compatibility: { core_api: string; engines: string[] } | null;
  health: { status: HealthStatus; message: string } | null;
  last_error: string | null;
  restart_required: boolean;
  /** The version "Roll back" goes back to, when the store keeps one. */
  previous_version: string | null;
}

export interface ModuleList {
  module_api_version: string;
  items: ModuleInfo[];
}

export interface UiColumn {
  key: string;
  label: string;
  format: "text" | "datetime" | "boolean" | "status";
}

export interface UiFormField {
  key: string;
  label: string;
  type: "text" | "textarea" | "integer" | "boolean" | "choice" | "password";
  required: boolean;
  max_length: number | null;
  choices: string[] | null;
  help: string | null;
}

export interface UiFilter {
  key: string;
  label: string;
  choices: string[];
}

export interface UiView {
  id: string;
  title: string;
  type: "resource_table";
  description: string | null;
  endpoint: string;
  permission: string;
  write_permission: string | null;
  columns: UiColumn[];
  create_form: UiFormField[];
  /** Module API 1.2: clicking a row opens this form; changes go as PATCH <endpoint>/<id>. */
  edit_form?: UiFormField[];
  delete: boolean;
  /** Module API 1.3: a search box sends `q`; each filter sends its key. */
  search?: boolean;
  filters?: UiFilter[];
  empty_title: string;
  empty_body: string | null;
}

export interface UiNav {
  label: string;
  view: string;
  icon: string;
  permission: string;
}

export interface UiExtension {
  module_id: string;
  module_name: string;
  api_base: string | null;
  nav: UiNav[];
  views: UiView[];
}

export type UpdateMode = "manual" | "notify" | "download_approve" | "auto_install_window";

export interface UpdatePolicy {
  component: string;
  label: string;
  mode: UpdateMode;
  channel: "stable" | "beta" | "development";
  check_enabled: boolean;
  check_interval_hours: number;
  auto_download: boolean;
  auto_install_categories: string[];
  require_approval: boolean;
  notify_admins: boolean;
  maintenance_window: MaintenanceWindow | null;
  updated_at: string;
}

export interface MaintenanceWindow {
  days: string[];
  start: string;
  duration_minutes: number;
  timezone: string;
}

export interface UpdatePolicies {
  source_configured: boolean;
  available_modes: UpdateMode[];
  items: UpdatePolicy[];
}

export interface UpdateCheck {
  checked_at: string;
  source: string;
  outcome: "ok" | "not_configured" | "failed" | "rejected";
  message: string | null;
}

export interface AvailableUpdate {
  id: string;
  component: string;
  target: string;
  version: string;
  current_version: string | null;
  channel: string;
  category: string;
  release_notes: string | null;
  state: string;
  created_at: string;
  downloaded_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  install_when: "now" | "window" | null;
  install_started_at: string | null;
  install_finished_at: string | null;
  error: string | null;
}

export interface UpdateCheckItem {
  key: string;
  ok: boolean;
  message: string;
}

export interface UpdateDetail extends AvailableUpdate {
  service_impact: string;
  size: number | null;
  checks: UpdateCheckItem[];
  window: MaintenanceWindow | null;
  next_window: string | null;
}

/** GET /updates/source: the fixed feed (issue #84) and the notification recipients. */
export interface UpdateSource {
  effective_url: string;
  official: boolean;
  recipients: string[];
  last_check: UpdateCheck | null;
}

export interface UpgradeRun {
  version: string;
  from_version: string;
  state: "running" | "succeeded" | "failed";
  step: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  log_tail: string[];
  log_file: string | null;
}

/** An approved or starting installation before (and while) the installer runs. */
export interface UpgradePending {
  id: string;
  version: string;
  state: "approved" | "installing";
  install_when: "now" | "window" | null;
  approved_at: string | null;
  approved_by: string | null;
  install_started_at: string | null;
  error: string | null;
  phase: "queued" | "window" | "starting" | "running" | "finishing";
  worker_last_pass_at: string | null;
  worker_interval_seconds: number;
  next_window: string | null;
}

export interface UpgradeStatus {
  installed_version: string;
  run: UpgradeRun | null;
  pending: UpgradePending | null;
}

export interface SystemPackage {
  name: string;
  version: string;
  from: string | null;
  security: boolean;
  telephony: boolean;
}

export interface SystemPackages {
  checked_at: string | null;
  packages: SystemPackage[];
  error: string | null;
  counts: { total: number; security: number; telephony: number };
  /** The last (or running) refresh or upgrade from the page. */
  run: SystemPackagesRun | null;
}

export type SystemPackagesMode = "refresh" | "security" | "all" | "everything";

export interface SystemPackagesRun {
  mode: SystemPackagesMode | null;
  started_at: string;
  finished_at: string | null;
  running: boolean;
  ok: boolean;
  output: string;
  reboot_required: boolean;
  reboot_packages: string[];
}

export interface UpdateHistoryItem {
  id: string;
  component: string;
  target: string;
  from_version: string | null;
  to_version: string;
  started_at: string;
  finished_at: string | null;
  outcome: string;
  initiated_by: string;
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor_type: string;
  actor_label: string;
  organization_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: "success" | "failure" | "denied";
  ip_address: string | null;
  request_id: string | null;
  details: Record<string, unknown>;
}

export interface TemplateSummary {
  key: string;
  name: string;
  version: string;
  manufacturer: string;
  models: string[];
  abstract: boolean;
  parent: string | null;
  parent_version: string | null;
  firmware: string;
  status: "stable" | "experimental" | "deprecated";
  description: string;
  source: "official" | "community" | "local";
  features: string[];
  parent_updated?: boolean;
}

export interface TemplateVariable {
  name: string;
  type: "string" | "integer" | "boolean";
  description: string;
  sensitive: boolean;
  required: boolean;
  default: string | number | boolean | null;
  max_length: number;
  pattern: string | null;
}

/** The template editor's catalog of facts and snippets (GET /provisioning/template-catalog). */
export interface TemplateCatalog {
  groups: { key: string; title: string; description: string; loop: string | null; facts: { expr: string; description: string; sensitive: boolean }[] }[];
  snippets: { title: string; description: string; text: string }[];
  core_variables: string[];
}

export interface TemplateDetail extends TemplateSummary {
  chain: string[];
  files: { name: string; source: string; format: string }[];
  variables: TemplateVariable[];
  defaults: Record<string, string | number | boolean>;
  validation: string[];
}

export interface RenderedFile {
  filename: string;
  format: string;
  content: string;
}

/* ---------------------------------------------------------------- Milestone 6: trunks and routing */

export type TrunkAuthMode = "registration" | "ip";
export type TrunkTransport = "udp" | "tcp" | "tls";
export type CallerIdHeader = "pai" | "rpid" | "none";
export type DtmfMode = "rfc4733" | "inband" | "info" | "auto";

export interface TrunkStatus {
  /** online/offline from the qualify ping; rejected/registering/unregistered from the engine's registration state (issue #45). */
  state: "online" | "offline" | "unknown" | "rejected" | "registering" | "unregistered";
  reachable: boolean | null;
  /** The engine's own word for the outbound registration. */
  registration?: string | null;
}

export interface Trunk {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  is_enabled: boolean;
  auth_mode: TrunkAuthMode;
  host: string;
  port: number;
  transport: TrunkTransport;
  username: string | null;
  auth_username: string | null;
  has_password: boolean;
  from_user: string | null;
  from_domain: string | null;
  outbound_proxy: string | null;
  match_addresses: string[];
  codecs: string[] | null;
  max_channels: number | null;
  /** Of max_channels, kept for emergency calls (issue #171). */
  emergency_reserved_channels?: number;
  default_caller_id: string | null;
  caller_id_header: CallerIdHeader;
  dtmf_mode: DtmfMode;
  fax_t38: boolean;
  qualify_frequency: number;
  register_expiry: number;
  register_retry_interval?: number;
  register_forbidden_retry?: number;
  register_max_retries?: number | null;
  status: TrunkStatus | null;
  created_at: string;
  updated_at: string;
}

export interface TrunkPage {
  items: Trunk[];
  total: number;
}

/** Create/patch body for a trunk; `password` is write-only (null clears it on PATCH). */
export interface TrunkInput {
  name?: string;
  description?: string | null;
  is_enabled?: boolean;
  auth_mode?: TrunkAuthMode;
  host?: string;
  port?: number;
  transport?: TrunkTransport;
  username?: string | null;
  auth_username?: string | null;
  password?: string | null;
  from_user?: string | null;
  from_domain?: string | null;
  outbound_proxy?: string | null;
  match_addresses?: string[];
  codecs?: string[] | null;
  max_channels?: number | null;
  emergency_reserved_channels?: number;
  default_caller_id?: string | null;
  caller_id_header?: CallerIdHeader;
  dtmf_mode?: DtmfMode;
  fax_t38?: boolean;
  qualify_frequency?: number;
  register_expiry?: number;
  register_retry_interval?: number;
  register_forbidden_retry?: number;
  register_max_retries?: number | null;
}

export type DestinationType = "extension" | "voicemail" | "voicemail_box" | "ivr" | "ring_group" | "queue" | "announcement" | "conference" | "call_flow" | "fax" | "custom" | "directory" | "hangup";

/** A call destination as the API reports it (docs/VOICEMAIL_IVR.md §6, RING_GROUPS_QUEUES.md §5). */
export interface Destination {
  type: DestinationType | "missing";
  extension_id: string | null;
  ivr_id: string | null;
  ring_group_id?: string | null;
  queue_id?: string | null;
  voicemail_box_id?: string | null;
  announcement_id?: string | null;
  conference_id?: string | null;
  call_flow_id?: string | null;
  fax_inbox_id?: string | null;
  custom_context?: string | null;
  /** "2214 — Front Office", "Voicemail of 2214 (Front Office)", "Shared inbox: Attendance (2900)", "Menu: Main menu", "Ring group: Sales (2300)", "Queue: Support (2400)", "Hang up"; null when the target is gone. */
  label: string | null;
  missing: boolean;
}

export interface DestinationInput {
  type: DestinationType;
  extension_id?: string | null;
  ivr_id?: string | null;
  ring_group_id?: string | null;
  queue_id?: string | null;
  voicemail_box_id?: string | null;
  announcement_id?: string | null;
  conference_id?: string | null;
  call_flow_id?: string | null;
  fax_inbox_id?: string | null;
  custom_context?: string | null;
}

export type RouteDestinationType = Exclude<DestinationType, "hangup">;

export interface InboundRoute {
  id: string;
  organization_id: string;
  organization_name: string;
  did: string;
  did_canonical: string;
  aliases: string[];
  trunk_id: string | null;
  trunk_name: string | null;
  description: string | null;
  destination_type: RouteDestinationType;
  destination_extension_id: string | null;
  destination_ivr_id: string | null;
  destination_ring_group_id: string | null;
  destination_queue_id: string | null;
  destination_voicemail_box_id: string | null;
  destination_announcement_id?: string | null;
  destination_conference_id?: string | null;
  destination_call_flow_id?: string | null;
  destination_custom_context?: string | null;
  destination_fax_inbox_id?: string | null;
  destination_number: string | null;
  destination_name: string | null;
  destination: Destination;
  destination_missing: boolean;
  time_condition_id: string | null;
  time_condition_name: string | null;
  after_hours_type: RouteDestinationType;
  after_hours_extension_id: string | null;
  after_hours_ivr_id: string | null;
  after_hours_ring_group_id: string | null;
  after_hours_queue_id: string | null;
  after_hours_voicemail_box_id: string | null;
  after_hours_announcement_id?: string | null;
  after_hours_conference_id?: string | null;
  after_hours_call_flow_id?: string | null;
  after_hours_custom_context?: string | null;
  after_hours_fax_inbox_id?: string | null;
  after_hours_number: string | null;
  after_hours_name: string | null;
  after_hours: Destination | null;
  caller_id_prefix: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface InboundRouteInput {
  organization_id?: string;
  did?: string;
  trunk_id?: string | null;
  description?: string | null;
  destination_type?: RouteDestinationType;
  destination_extension_id?: string | null;
  destination_ivr_id?: string | null;
  destination_ring_group_id?: string | null;
  destination_queue_id?: string | null;
  destination_voicemail_box_id?: string | null;
  destination_announcement_id?: string | null;
  destination_conference_id?: string | null;
  destination_call_flow_id?: string | null;
  destination_fax_inbox_id?: string | null;
  destination_custom_context?: string | null;
  time_condition_id?: string | null;
  after_hours_type?: RouteDestinationType;
  after_hours_extension_id?: string | null;
  after_hours_ivr_id?: string | null;
  after_hours_ring_group_id?: string | null;
  after_hours_queue_id?: string | null;
  after_hours_voicemail_box_id?: string | null;
  after_hours_announcement_id?: string | null;
  after_hours_conference_id?: string | null;
  after_hours_call_flow_id?: string | null;
  after_hours_fax_inbox_id?: string | null;
  after_hours_custom_context?: string | null;
  caller_id_prefix?: string | null;
  is_enabled?: boolean;
}

export interface OutboundPattern {
  prefix: string;
  match: string;
  prepend: string;
}

export interface RouteTrunk {
  id: string;
  name: string;
  slug: string;
  is_enabled: boolean;
}

export interface OutboundRoute {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  position: number;
  is_emergency: boolean;
  site_id?: string | null;
  is_enabled: boolean;
  patterns: OutboundPattern[];
  /** Rendered Asterisk extensions, e.g. `_9NXXNXXXXXX`. */
  examples: string[];
  /** Failover order. */
  trunks: RouteTrunk[];
  caller_id_number: string | null;
  /** The route's caller ID also replaces an extension's outbound caller ID. */
  caller_id_force?: boolean;
  /** Only this organization's phones use the route; null: every organization. */
  organization_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface OutboundRoutes {
  items: OutboundRoute[];
  warnings: string[];
}

export interface OutboundRouteInput {
  name?: string;
  description?: string | null;
  is_emergency?: boolean;
  site_id?: string | null;
  is_enabled?: boolean;
  patterns?: OutboundPattern[];
  trunk_ids?: string[];
  caller_id_number?: string | null;
  caller_id_force?: boolean;
  organization_id?: string | null;
}

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export interface TimeRange {
  days: Weekday[];
  /** HH:MM, 24-hour. */
  start: string;
  end: string;
}

export interface TimeCondition {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  description: string | null;
  timezone: string;
  ranges: TimeRange[];
  /** MM-DD dates on which the condition is closed. */
  holidays: string[];
  /** What the schedule says now; `effective_open` includes an override (docs/CALL_FEATURES.md §4.6). */
  open_now: boolean;
  effective_open: boolean;
  override: "open" | "closed" | null;
  override_temporary: boolean;
  override_by: string | null;
  override_at: string | null;
  /** Digits after the override code (*27<index>); null: no code. */
  code_index: number | null;
  code: string | null;
  has_pin: boolean;
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface TimeConditionInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  /** IANA name; null or empty = the organization default. */
  timezone?: string | null;
  ranges?: TimeRange[];
  holidays?: string[];
  code_index?: number | null;
  /** Write-only; null removes the PIN. */
  pin?: string | null;
}

// ---------------------------------------------------------------- voicemail, prompts, IVR (Milestone 7)

export interface VoicemailBox {
  id: string;
  organization_id: string;
  organization_name: string;
  /** A shared inbox has no extension: `number` and `name` are its own and `members` follow it on their lamps (docs/PAGING_RECORDINGS.md §5). */
  shared: boolean;
  extension_id: string | null;
  extension_number: string;
  extension_name: string;
  extension_enabled: boolean;
  /** The extension's number and name, or the shared inbox's own. */
  number: string;
  name: string;
  members: GroupMember[];
  user_display_name: string | null;
  email: string | null;
  attach_audio: boolean;
  delete_after_email: boolean;
  keep_days?: number | null;
  ring_seconds: number;
  /** Pressing 0 while the greeting plays reaches this extension (CALL_FEATURES.md §3.7). */
  operator_extension?: string | null;
  /** The after-hours greeting plays while this time condition is closed (#169). */
  after_hours_time_condition_id?: string | null;
  /** Pressing 1 / 2 during the greeting (#131): "followme" (1 only) or a number of the organization. */
  locater_1?: string | null;
  locater_2?: string | null;
  is_enabled: boolean;
  /** Settings → Email delivery is enabled; without it messages stay in the box. */
  email_delivery_enabled: boolean;
  /** Inbound routes and IVR keys that send calls to this box. */
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

/** Returned once by POST /voicemail: the PIN is never shown again. */
export interface VoicemailBoxCreated extends VoicemailBox {
  pin: string;
}

export interface VoicemailBoxInput {
  extension_id?: string;
  /** Shared inbox (no extension): the organization, its number, name and member extensions. */
  organization_id?: string;
  number?: string;
  name?: string;
  members?: string[];
  /** Omitted on creation: a random PIN is generated. */
  pin?: string;
  /** Omitted on creation: the extension user's address. Null or empty: no email. */
  email?: string | null;
  attach_audio?: boolean;
  delete_after_email?: boolean;
  keep_days?: number | null;
  ring_seconds?: number;
  is_enabled?: boolean;
  operator_extension?: string | null;
  after_hours_time_condition_id?: string | null;
  /** Pressing 1 / 2 during the greeting (#131): "followme" (1 only) or a number of the organization. */
  locater_1?: string | null;
  locater_2?: string | null;
}

export interface MyVoicemail {
  id: string;
  /** A shared inbox one of the user's extensions is a member of. */
  shared: boolean;
  extension_id: string | null;
  extension_number: string;
  extension_name: string;
  number: string;
  name: string;
  email: string | null;
  ring_seconds: number;
  is_enabled: boolean;
  locater_1?: string | null;
  locater_2?: string | null;
}

/** A personal contact of the signed-in user (docs/USER_PORTAL.md §6). */
export interface ContactNumber { label: "work" | "mobile" | "home" | "other"; number: string }
export interface Contact {
  id: string;
  name: string;
  company: string | null;
  numbers: ContactNumber[];
  email: string | null;
  favourite: boolean;
  speed_dial: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}
export interface ContactInput {
  name: string;
  company: string | null;
  numbers: ContactNumber[];
  email: string | null;
  favourite: boolean;
  speed_dial: number | null;
  notes: string | null;
}

/** Portal canvas layout documents and templates (docs/USER_PORTAL.md §10). */
export interface PortalLayoutOut {
  layout: { version: 1; tabs: { id: string; name: string; widgets: { key: string; instance: string; x: number; y: number; w: number; h: number; settings?: Record<string, unknown> }[] }[] } | null;
  source: "user" | "template" | "default";
  template_id: string | null;
  template_name: string | null;
  locked_widgets: string[];
  /** The layout template's current announcement text. */
  announcement?: string | null;
}
export type PortalScope = "system" | "organization" | "building" | "department" | "role";
export interface PortalTemplate {
  id: string;
  organization_id: string | null;
  organization_name: string | null;
  name: string;
  description: string | null;
  scope: PortalScope;
  scope_ref: string | null;
  scope_label: string | null;
  layout: NonNullable<PortalLayoutOut["layout"]>;
  locked_widgets: string[];
  priority: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** One of the user's phones with its key slots (docs/USER_PORTAL.md §8). */
export interface MyDeviceSlot {
  index: number;
  kind: "locked" | "user";
  type: string | null;
  label: string | null;
  value: string | null;
}
export interface MyDevice {
  id: string;
  label: string | null;
  manufacturer: string;
  model: string;
  mac_display: string;
  extension_id: string;
  extension_number: string;
  profile_name: string | null;
  slots: MyDeviceSlot[];
  user_slots: number;
}
export interface UserKeyInput { type: "speed_dial" | "blf" | "presence"; label: string | null; value: string; contact_id?: string | null }

/** One voicemail message as the store helper reports it (docs/USER_PORTAL.md §2). */
export interface VoicemailMessage {
  number: number;
  folder: string;
  msg_id: string;
  caller_number: string;
  caller_name: string;
  received_at: string | null;
  duration_seconds: number;
  urgent: boolean;
  format: string | null;
  size_bytes: number;
}

/** One of the four greetings of a box (docs/USER_PORTAL.md §3). */
export interface VoicemailGreeting {
  kind: "unavail" | "busy" | "greet" | "temp" | "absence" | "afterhours";
  label: string;
  recorded: boolean;
  format: string | null;
  size_bytes: number;
}

/** POST …/messages/{n}/email (issue #148). */
export interface VoicemailEmailResult {
  sent_to: string[];
  deleted: boolean;
  delete_error: string | null;
}

export interface VoicemailMessages {
  folder: string;
  messages: VoicemailMessage[];
  counts: Record<string, number>;
  folders: { key: string; label: string }[];
}

export type AudioKind = "prompt" | "bell" | "announcement" | "greeting" | "music";

export interface Prompt {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string | null;
  source: "upload" | "recording" | "builtin";
  /** What the recording is for (docs/PAGING_RECORDINGS.md §3). */
  kind: AudioKind;
  license: string | null;
  credit: string | null;
  duration_seconds: number;
  size_bytes: number;
  file_present: boolean;
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

/** A recording made from a phone with *95, waiting to be named (adopted) or discarded. */
export interface Recording {
  file: string;
  organization_id: string;
  organization_name: string;
  extension_number: string;
  recorded_at: string;
  duration_seconds: number;
  size_bytes: number;
}

export interface IvrEntry {
  digit: string;
  destination: Destination;
}

export interface IvrEntryInput {
  digit: string;
  destination: DestinationInput;
}

export interface IvrMenu {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  description: string | null;
  prompt_id: string | null;
  prompt_name: string | null;
  invalid_prompt_id: string | null;
  invalid_prompt_name: string | null;
  timeout_seconds: number;
  max_retries: number;
  allow_direct_dial: boolean;
  timeout_destination: Destination;
  invalid_destination: Destination;
  entries: IvrEntry[];
  is_enabled: boolean;
  /** Why the menu will not work as configured. */
  problems: string[];
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface IvrMenuInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  prompt_id?: string | null;
  invalid_prompt_id?: string | null;
  timeout_seconds?: number;
  max_retries?: number;
  allow_direct_dial?: boolean;
  timeout_destination?: DestinationInput;
  invalid_destination?: DestinationInput;
  entries?: IvrEntryInput[];
  is_enabled?: boolean;
}

// ---------------------------------------------------------------- call flow (docs/CALL_FEATURES.md §4)

/** Plays a prompt, then continues to a destination (§4.1). */
export interface Announcement {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  description: string | null;
  prompt_id: string | null;
  prompt_name: string | null;
  allow_skip: boolean;
  repeat_key: string | null;
  destination: Destination;
  is_enabled: boolean;
  problems: string[];
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface AnnouncementInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  prompt_id?: string | null;
  allow_skip?: boolean;
  repeat_key?: string | null;
  destination?: DestinationInput;
  is_enabled?: boolean;
}

/** A meet-me room (§4.3); PINs are write-only. */
export interface ConferenceRoom {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  number: string;
  context: string;
  description: string | null;
  has_user_pin: boolean;
  has_admin_pin: boolean;
  max_participants: number;
  record: boolean;
  announce_join_leave: boolean;
  music_on_hold_alone: boolean;
  wait_for_admin: boolean;
  moh_class_id: string | null;
  moh_class_name: string | null;
  is_enabled: boolean;
  problems: string[];
  in_use_by: number;
  owners: string[];
  created_at: string;
  updated_at: string;
}

export interface ConferenceRoomInput {
  organization_id?: string;
  name?: string;
  number?: string;
  description?: string | null;
  user_pin?: string | null;
  admin_pin?: string | null;
  max_participants?: number;
  record?: boolean;
  announce_join_leave?: boolean;
  music_on_hold_alone?: boolean;
  wait_for_admin?: boolean;
  moh_class_id?: string | null;
  is_enabled?: boolean;
}

/** A day/night switch between two destinations (§4.5). */
export interface CallFlow {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  description: string | null;
  code_index: number;
  code: string | null;
  has_pin: boolean;
  normal: Destination;
  override_destination: Destination;
  override: boolean;
  override_by: string | null;
  override_at: string | null;
  is_enabled: boolean;
  problems: string[];
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface CallFlowInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  code_index?: number;
  pin?: string | null;
  normal?: DestinationInput;
  override_destination?: DestinationInput;
  is_enabled?: boolean;
}

/** A parking lot (§4.7): park extension, slot range, timeout return. */
export interface ParkingLot {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  description: string | null;
  park_exten: string;
  slot_first: number;
  slot_last: number;
  slots: string[];
  timeout_seconds: number;
  return_ring_seconds: number;
  courtesy_tone: boolean;
  timeout: Destination;
  is_enabled: boolean;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface ParkingLotInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  park_exten?: string;
  slot_first?: number;
  slot_last?: number;
  timeout_seconds?: number;
  return_ring_seconds?: number;
  courtesy_tone?: boolean;
  timeout?: DestinationInput;
  is_enabled?: boolean;
}

/** A blocked caller number (§4.8). */
export interface CallerBlock {
  id: string;
  organization_id: string;
  organization_name: string;
  number: string;
  description: string | null;
  source: "api" | "phone" | "csv";
  hits: number;
  last_hit_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallerBlockPolicy {
  organization_id: string;
  organization_name: string;
  block_anonymous: boolean;
  anonymous_hits: number;
  destination: Destination;
  blocked_numbers: number;
  total_hits: number;
  updated_at: string | null;
}

export interface CallerBlockImportResult {
  added: number;
  updated: number;
  skipped: string[];
}

export type SmtpSecurity = "starttls" | "tls" | "none";

export interface SmtpSettings {
  enabled: boolean;
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string | null;
  has_password: boolean;
  from_address: string | null;
  from_name: string | null;
  effective_from_address: string;
  effective_from_name: string;
  problems: string[];
  queue: { waiting: number; failed: number };
  updated_at: string | null;
}

export interface SmtpSettingsInput {
  enabled: boolean;
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string | null;
  /** Omitted: unchanged. Null or empty: removed. */
  password?: string | null;
  from_address: string | null;
  from_name: string | null;
}

export interface SmtpTestResult {
  ok: boolean;
  message: string;
  recipient: string;
}

// ---------------------------------------------------------------- ring groups, queues, pickup groups (docs/RING_GROUPS_QUEUES.md)

export interface GroupMember {
  extension_id: string;
  number: string;
  display_name: string;
  is_enabled: boolean;
  position: number | null;
  penalty: number | null;
  /** Queue agents (docs/CALL_FEATURES.md §4.9): a dynamic agent is in the queue only while logged in. */
  dynamic?: boolean;
  logged_in?: boolean;
  paused?: boolean;
  state_by?: string | null;
  state_at?: string | null;
  /** Ring group members (issue #166): this member's ring time; null: the group's. */
  ring_seconds?: number | null;
}

/** One-at-a-time orders (issue #166): circular starts after the last answer, roundrobin one later each call, longest_idle with the member who answered least recently. */
export type RingGroupStrategy = "ringall" | "sequential" | "circular" | "roundrobin" | "longest_idle";

export interface RingGroup {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  number: string;
  description: string | null;
  strategy: RingGroupStrategy;
  ring_seconds: number;
  ring_busy_members: boolean;
  /** Skip a member after this many unanswered calls in a row, for skip_minutes (#166); null: never. */
  skip_after_misses?: number | null;
  skip_minutes?: number;
  /** Outside numbers rung with the members (CALL_FEATURES.md §3.4); the leg presses 1 when confirm_external is on. */
  external_members?: string[];
  confirm_external?: boolean;
  caller_id_prefix: string | null;
  /** What callers hear while members ring. */
  music: QueueMusic;
  moh_class_id: string | null;
  moh_class_name: string | null;
  failover: Destination;
  members: GroupMember[];
  is_enabled: boolean;
  problems: string[];
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface RingGroupInput {
  organization_id?: string;
  name?: string;
  number?: string;
  description?: string | null;
  strategy?: RingGroupStrategy;
  ring_seconds?: number;
  ring_busy_members?: boolean;
  skip_after_misses?: number | null;
  skip_minutes?: number;
  external_members?: string[];
  confirm_external?: boolean;
  caller_id_prefix?: string | null;
  music?: QueueMusic;
  moh_class_id?: string | null;
  failover?: DestinationInput;
  members?: string[];
  is_enabled?: boolean;
  /** Extension id -> seconds (issue #166). */
  member_ring_seconds?: Record<string, number>;
}

export type QueueStrategy = "ringall" | "rrmemory" | "leastrecent" | "fewestcalls" | "random" | "linear";
export type QueueMusic = "default" | "ring";

export interface CallQueue {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  queue_name: string;
  context: string;
  number: string;
  description: string | null;
  strategy: QueueStrategy;
  member_timeout: number;
  retry_seconds: number;
  wrapup_seconds: number;
  max_wait_seconds: number;
  max_callers: number;
  join_when_empty: boolean;
  announce_position: boolean;
  announce_frequency: number;
  announcement_prompt_id: string | null;
  announcement_prompt_name: string | null;
  periodic_prompt_id: string | null;
  periodic_prompt_name: string | null;
  periodic_seconds: number;
  music: QueueMusic;
  moh_class_id: string | null;
  moh_class_name: string | null;
  failover: Destination;
  /** Break-out menu: keys callers may press while waiting (§4.10). */
  breakout_ivr_id: string | null;
  breakout_ivr_name: string | null;
  members: GroupMember[];
  is_enabled: boolean;
  problems: string[];
  in_use_by: number;
  created_at: string;
  updated_at: string;
}

export interface QueueAgentInput {
  extension_id: string;
  penalty: number;
  /** In the queue only while logged in (*45 or the queue page). */
  dynamic?: boolean;
}

export interface QueueInput {
  organization_id?: string;
  name?: string;
  number?: string;
  description?: string | null;
  strategy?: QueueStrategy;
  member_timeout?: number;
  retry_seconds?: number;
  wrapup_seconds?: number;
  max_wait_seconds?: number;
  max_callers?: number;
  join_when_empty?: boolean;
  announce_position?: boolean;
  announce_frequency?: number;
  announcement_prompt_id?: string | null;
  periodic_prompt_id?: string | null;
  periodic_seconds?: number;
  music?: QueueMusic;
  moh_class_id?: string | null;
  failover?: DestinationInput;
  breakout_ivr_id?: string | null;
  members?: QueueAgentInput[];
  is_enabled?: boolean;
}

export interface PickupGroup {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string | null;
  members: GroupMember[];
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface PickupGroupInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  members?: string[];
}

// ---------------------------------------------------------------- devices (docs/DEVICE_PROVISIONING.md)

export interface Site {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  timezone: string | null;
  street: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  /** Default emergency caller ID for the site's extensions. */
  emergency_caller_id_number: string | null;
  extensions: number;
  devices: number;
  buildings?: number;
  created_at: string;
  updated_at: string;
}

/** A building of a site, with its own civic address when it differs (#126). */
export interface Building {
  id: string;
  organization_id: string;
  site_id: string;
  site_name: string;
  name: string;
  street: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  has_own_address: boolean;
  extensions: number;
  created_at: string;
  updated_at: string;
}

export interface Department {
  id: string;
  organization_id: string;
  name: string;
  site_id: string | null;
  site_name: string | null;
  extensions: number;
  created_at: string;
  updated_at: string;
}

export interface SiteInput {
  organization_id?: string;
  name?: string;
  timezone?: string | null;
  street?: string | null;
  city?: string | null;
  region?: string | null;
  postal_code?: string | null;
  country?: string | null;
  emergency_caller_id_number?: string | null;
}

export type PagingKind = "normal" | "priority" | "emergency";
export type PagingCodec = "G.711Mu" | "G.722";

export interface PagingZone {
  id: string;
  organization_id: string;
  organization_name: string;
  site_id: string | null;
  site_name: string | null;
  name: string;
  slug: string;
  description: string | null;
  /** Plain multicast group the speakers listen to. */
  multicast_address: string;
  multicast_port: number;
  /** Poly group paging address, port and group number (1-25). */
  poly_address: string;
  poly_port: number;
  poly_group: number;
  kind: PagingKind;
  codec: PagingCodec;
  is_enabled: boolean;
  /** Dialable number from the shared number space, who may page, longest page (docs/PAGING_RECORDINGS.md §2). */
  number: string | null;
  allowed: PagingAllowed;
  members: GroupMember[];
  max_seconds: number;
  profiles: { id: string; name: string }[];
  problems: string[];
  created_at: string;
  updated_at: string;
}

export type PagingAllowed = "everyone" | "members" | "administrators";

export interface PagingZoneInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  site_id?: string | null;
  multicast_address?: string;
  multicast_port?: number;
  poly_address?: string;
  poly_port?: number;
  poly_group?: number;
  kind?: PagingKind;
  codec?: PagingCodec;
  is_enabled?: boolean;
  number?: string | null;
  allowed?: PagingAllowed;
  members?: string[];
  max_seconds?: number;
}

export type PagePriority = "normal" | "priority" | "emergency";

export interface PagingPage {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string | null;
  number: string | null;
  zones: { id: string; name: string; slug: string; poly_group: number }[];
  audio: { id: string; name: string; duration_seconds: number } | null;
  pre_tone: boolean;
  repeat: number;
  priority: PagePriority;
  allowed: PagingAllowed;
  members: GroupMember[];
  max_seconds: number;
  is_enabled: boolean;
  last_sent_at: string | null;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface PagingPageInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  number?: string | null;
  zones?: string[];
  audio_id?: string | null;
  pre_tone?: boolean;
  repeat?: number;
  priority?: PagePriority;
  allowed?: PagingAllowed;
  members?: string[];
  max_seconds?: number;
  is_enabled?: boolean;
}

export interface PageSendResult {
  started: boolean;
  message: string;
  channel_id: string | null;
}

export interface PageLogEntry {
  id: string;
  at: string;
  page_id: string | null;
  page_name: string;
  zones: string[];
  trigger: "dial" | "api" | "bell" | "ui";
  actor: string | null;
  outcome: "started" | "failed";
  detail: Record<string, unknown>;
}

/** "user": an open slot the phone's user fills from My Phone (docs/USER_PORTAL.md §8). */
export type LineKeyType = "line" | "blf" | "speed_dial" | "page" | "user" | "park" | "voicemail" | "transfer" | "intercom" | "dnd" | "toggle" | "presence";

export interface LineKey {
  type: LineKeyType;
  label: string | null;
  value: string;
}

export type PagingRole = "none" | "default" | "priority" | "emergency";

export interface PagingMembership {
  zone_id: string;
  subscribed: boolean;
  transmit: boolean;
  role: PagingRole;
  zone_name: string;
  poly_group: number;
  kind: PagingKind;
}

export interface PagingMembershipInput {
  zone_id: string;
  subscribed?: boolean;
  transmit?: boolean;
  role?: PagingRole;
}

export interface FirmwareRef {
  id: string;
  manufacturer?: string;
  version: string;
  filename: string;
  source?: "device" | "profile";
}

export interface DeviceProfile {
  id: string;
  organization_id: string;
  organization_name: string;
  site_id: string | null;
  site_name: string | null;
  name: string;
  description: string | null;
  template_key: string;
  template_name: string | null;
  template_abstract: boolean | null;
  manufacturer: string | null;
  /** Model → concrete template key the family resolves to. */
  models: Record<string, string>;
  values: Record<string, string | number | boolean>;
  keys: LineKey[];
  paging: PagingMembership[];
  firmware: FirmwareRef | null;
  devices: number;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface DeviceProfileInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  site_id?: string | null;
  template_key?: string;
  values?: Record<string, string | number | boolean>;
  keys?: LineKey[];
  paging?: PagingMembershipInput[];
  firmware_image_id?: string | null;
}

export interface ExtensionRef {
  id: string;
  number: string;
  display_name: string;
  is_enabled: boolean;
}

export type DeviceStatus = "never" | "provisioned" | "stale" | "error";

export interface Device {
  id: string;
  organization_id: string;
  organization_name: string;
  site_id: string | null;
  building_id?: string | null;
  location?: string | null;
  site_name: string | null;
  mac_address: string;
  mac_display: string;
  manufacturer: string;
  model: string;
  label: string | null;
  profile_id: string | null;
  profile_name: string | null;
  template_key: string | null;
  extension: ExtensionRef | null;
  lines: ExtensionRef[];
  keys: LineKey[] | null;
  values: Record<string, string | number | boolean>;
  firmware: FirmwareRef | null;
  firmware_reported: string | null;
  firmware_state: "unknown" | "up_to_date" | "pending" | "none";
  is_enabled: boolean;
  status: DeviceStatus;
  last_seen_at: string | null;
  last_seen_ip: string | null;
  last_user_agent: string | null;
  last_result: string | null;
  /** First provisioning over HTTPS (phone trust); null until then. */
  https_seen_at: string | null;
  /** The plain-HTTP bootstrap is served to this phone. */
  allow_bootstrap: boolean;
  credential_user: string;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface DeviceInput {
  organization_id?: string;
  mac_address?: string;
  manufacturer?: string;
  model?: string;
  label?: string | null;
  site_id?: string | null;
  profile_id?: string | null;
  primary_extension_id?: string | null;
  lines?: string[];
  keys?: LineKey[] | null;
  values?: Record<string, string | number | boolean>;
  firmware_image_id?: string | null;
  is_enabled?: boolean;
  building_id?: string | null;
  location?: string | null;
}

export interface UnregisteredDevice {
  mac_address: string;
  mac_display: string;
  organization_id: string | null;
  organization_name: string | null;
  ip_address: string | null;
  user_agent: string | null;
  manufacturer: string | null;
  model: string | null;
  last_seen_at: string;
  requests: number;
}

export interface DevicePreview {
  template_key: string | null;
  files: RenderedFile[];
  error: string | null;
  error_code: string | null;
  /** Variables a template or key referenced but nobody defined. */
  warnings?: string[];
}

/** Provisioning variables (docs/PROVISIONING_BREADTH.md §2). */
export type VariableScope = "installation" | "organization" | "site" | "profile";

export interface ProvisioningVariable {
  id: string | null;
  source: "core" | "defined";
  scope: VariableScope | null;
  scope_id: string | null;
  scope_name: string | null;
  organization_id: string | null;
  name: string;
  value: string | null;
  sensitive: boolean;
  description: string | null;
  type?: string | null;
  default?: string | number | boolean | null;
  affected_devices?: number | null;
  updated_at?: string | null;
}

export interface ResolvedVariable {
  name: string;
  value: string;
  scope: VariableScope;
  scope_id: string | null;
  sensitive: boolean;
  description: string | null;
}

export interface ReprovisionResult {
  sent: boolean;
  endpoint: string | null;
  message: string;
}

export interface FirmwareImage {
  id: string;
  manufacturer: string;
  models: string[];
  version: string;
  filename: string;
  size: number;
  sha256: string;
  notes: string | null;
  uploaded_by: string | null;
  url: string;
  profiles: number;
  devices: number;
  created_at: string;
}

export interface ProvisioningCredential {
  organization_id: string;
  username: string | null;
  url: string;
  http_enabled: boolean;
  /** "bootstrap": plain HTTP serves only the Veyra CA and the HTTPS address. */
  http_mode?: "bootstrap" | "full";
  rotated_at: string | null;
}

export interface ProvisioningCredentialRotated extends ProvisioningCredential {
  password: string;
}

export interface CatalogModels {
  manufacturers: { name: string; models: string[] }[];
}

// ---------------------------------------------------------------- dashboard graphs (docs/INTERFACE_REWORK.md §2)

export type MetricsRange = "1h" | "6h" | "24h" | "7d";

export interface CallMetricPoint {
  at: string;
  channels: number;
  calls_internal: number;
  calls_external: number;
  registrations: number;
  /** Phones the engine knows, registered or not; null in samples before 0.26.5. */
  endpoints: number | null;
}

export interface CallMetrics {
  range: MetricsRange;
  step_seconds: number;
  since: string;
  points: CallMetricPoint[];
  current: Omit<CallMetricPoint, "at"> | null;
  available: boolean;
}

// ---------------------------------------------------------------- calendars and bells (docs/PAGING_RECORDINGS.md §4)

export interface CalendarSub {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  kind: "ical";
  url_display: string;
  poll_minutes: number;
  timezone: string | null;
  is_enabled: boolean;
  last_polled_at: string | null;
  last_status: "ok" | "failed" | null;
  last_error: string | null;
  event_count: number;
  schedules: number;
  created_at: string;
  updated_at: string;
}

export interface CalendarSubInput {
  organization_id?: string;
  name?: string;
  url?: string;
  poll_minutes?: number;
  timezone?: string | null;
  is_enabled?: boolean;
}

export interface CalendarEventOut {
  uid: string;
  summary: string;
  starts_at: string;
  ends_at: string | null;
  all_day: boolean;
}

export type BellTrigger = "start" | "end" | "both";

export interface BellSchedule {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  calendar_id: string;
  calendar_name: string;
  page_id: string;
  page_name: string;
  match: string;
  trigger: BellTrigger;
  tolerance_seconds: number;
  all_day_events: boolean;
  is_enabled: boolean;
  next_rings: { summary: string; due_at: string; trigger: string }[];
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface BellScheduleInput {
  organization_id?: string;
  name?: string;
  calendar_id?: string;
  page_id?: string;
  match?: string;
  trigger?: BellTrigger;
  tolerance_seconds?: number;
  all_day_events?: boolean;
  is_enabled?: boolean;
}

export interface BellRing {
  id: string;
  summary: string;
  due_at: string;
  rang_at: string;
  outcome: "started" | "failed" | "skipped";
  detail: Record<string, unknown>;
}

// ---------------------------------------------------------------- hold music (docs/PAGING_RECORDINGS.md §3.2)

export interface HoldMusicTrack {
  prompt_id: string;
  name: string;
  kind: AudioKind;
  license: string | null;
  duration_seconds: number;
  file_present: boolean;
}

export interface HoldMusicSet {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  /** The engine's music class, `veyra-<slug>`. */
  class_name: string;
  description: string | null;
  random: boolean;
  /** An internet stream instead of the recordings (#138). */
  stream_url?: string | null;
  tracks: HoldMusicTrack[];
  /** Organizations (as default), queues and ring groups playing the set. */
  in_use_by: number;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export interface HoldMusicInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  tracks?: string[];
  random?: boolean;
  stream_url?: string | null;
}

// ---------------------------------------------------------------- firewall (docs/FIREWALL_TRUST.md §7)

export type FirewallService = "sip" | "rtp" | "web" | "ssh";
export type FirewallPolicy = "anywhere" | "allow_list_only";

export interface FirewallPendingConfirm {
  previous_policy: Record<FirewallService, FirewallPolicy>;
  deadline: string;
  by: string;
}

export interface FirewallSettings {
  enabled: boolean;
  policy: Record<FirewallService, FirewallPolicy>;
  ban_score: number;
  window_minutes: number;
  ban_minutes: number;
  max_ban_days: number;
  weights: Record<string, number>;
  ssh_ports: number[];
  bootstrap_networks: string[];
  pending_confirm: FirewallPendingConfirm | null;
}

export interface FirewallStatus {
  enabled: boolean;
  service_running: boolean;
  applied: boolean;
  error: string | null;
  sources: Record<string, string | null>;
  active_bans: number;
  events_24h: number;
  bans_24h: number;
  top_addresses: { address: string; events: number }[];
  pending_confirm: FirewallPendingConfirm | null;
  your_address: string | null;
  your_address_allowed: boolean;
}

export interface FirewallRule {
  id: string;
  action: "allow" | "block";
  cidr: string;
  services: FirewallService[];
  comment: string | null;
  expires_at: string | null;
  origin: "manual" | "server" | "sip_local_net" | "trunk";
  created_by: string | null;
  created_at: string;
}

export interface FirewallBan {
  id: string;
  address: string;
  reason: string;
  source: string;
  event_count: number;
  offence: number;
  banned_at: string;
  expires_at: string;
  lifted_at: string | null;
  lifted_by: string | null;
}

export interface FirewallEvent {
  id: string;
  at: string;
  address: string;
  source: "asterisk" | "auth" | "provisioning" | "nginx";
  kind: string;
  detail: string | null;
  count: number;
  would_ban: boolean;
}

export interface FirewallFeed {
  id: string;
  name: string;
  kind: "crowdsec" | "list";
  url: string;
  has_key: boolean;
  is_enabled: boolean;
  last_fetched_at: string | null;
  last_status: string | null;
  last_error: string | null;
  entry_count: number;
}

// ---------------------------------------------------------------- call history (docs/REPORTING.md §3)

export type CallDirection = "internal" | "inbound" | "outbound";
export type CallOutcome = "answered" | "missed" | "busy" | "failed" | "voicemail" | "abandoned" | "blocked" | "denied";

export interface CallExtensionRef {
  id: string;
  number: string;
  display_name: string;
}

export interface CallHistoryItem {
  id: string;
  organization_id: string | null;
  organization_name: string | null;
  direction: CallDirection;
  outcome: CallOutcome;
  from_number: string | null;
  from_name: string | null;
  to_number: string | null;
  did: string | null;
  from_extension: CallExtensionRef | null;
  to_extension: CallExtensionRef | null;
  answered_by: CallExtensionRef | null;
  trunk_name: string | null;
  started_at: string;
  answered_at: string | null;
  ended_at: string | null;
  ring_seconds: number;
  talk_seconds: number;
  leg_count: number;
  recorded: boolean;
  /** On the user's own history: the other party's name from their contacts. */
  contact_name?: string | null;
  in_progress: boolean;
}

export interface CallLegItem {
  start: string;
  answer: string | null;
  end: string | null;
  channel: string;
  dstchannel: string;
  src: string;
  dst: string;
  lastapp: string;
  disposition: string;
  billsec: number;
}

export interface CallHistoryDetail extends CallHistoryItem {
  legs: CallLegItem[];
  /** The call's recording (listening needs recordings.read). */
  recording_id: string | null;
}

// ---------------------------------------------------------------- call recording (docs/REPORTING.md §4)

export interface RecordingPolicy {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  is_enabled: boolean;
  inbound: boolean;
  outbound: boolean;
  internal: boolean;
  scope: "all" | "selected";
  extension_ids: string[];
  ring_group_ids: string[];
  queue_ids: string[];
  inbound_route_ids: string[];
  announcement_prompt_id: string | null;
  retention_days: number;
  problems: string[];
  created_at: string;
  updated_at: string;
}

export type RecordingPolicyInput = Omit<RecordingPolicy, "id" | "organization_name" | "problems" | "created_at" | "updated_at">;

export interface CallRecordingItem {
  id: string;
  organization_id: string | null;
  call_id: string | null;
  policy_name: string | null;
  started_at: string | null;
  direction: CallDirection | null;
  from_number: string | null;
  from_name: string | null;
  to_number: string | null;
  /** A conference room's recording (#133) instead of a call's. */
  conference_room_id?: string | null;
  conference_name?: string | null;
  duration_seconds: number;
  size_bytes: number;
  created_at: string;
  delete_after: string | null;
  held: boolean;
  held_by: string | null;
  deleted_at: string | null;
}

// ---------------------------------------------------------------- monitoring (docs/REPORTING.md §6)

export interface AlertItem {
  id: string;
  rule: string;
  title: string;
  subject: string;
  state: "pending" | "raised" | "cleared";
  message: string;
  first_seen_at: string;
  raised_at: string | null;
  cleared_at: string | null;
  notify_error: string | null;
}

// ---------------------------------------------------------------- report builder (docs/REPORT_BUILDER.md)

export type ReportGroup =
  | "day" | "week" | "month" | "hour" | "weekday" | "direction" | "outcome" | "answered_by"
  | "called_extension" | "calling_extension" | "did" | "trunk" | "queue" | "ring_group" | "caller";
export type ReportMeasure =
  | "calls" | "answered" | "missed" | "voicemail" | "answer_rate" | "avg_ring" | "total_ring"
  | "avg_talk" | "total_talk" | "within_sl";
export type ReportPeriodKind =
  | "today" | "yesterday" | "last_7_days" | "last_30_days" | "this_week" | "last_week"
  | "this_month" | "last_month" | "this_year" | "custom";

export interface ReportFilters {
  directions: CallDirection[];
  outcomes: CallOutcome[];
  extension_ids: string[];
  dids: string[];
  trunk_ids: string[];
  queues: string[];
  ring_groups: string[];
  caller_contains: string | null;
  min_talk_seconds: number | null;
  business_hours: "any" | "inside" | "outside";
  time_condition_id: string | null;
}

export interface ReportDefinition {
  organization_id: string | null;
  group_by: ReportGroup[];
  measures: ReportMeasure[];
  filters: ReportFilters;
  period: { kind: ReportPeriodKind; from_date: string | null; to_date: string | null };
  show_as: "table" | "bars" | "line";
  sort_by: string | null;
  sort_desc: boolean;
  limit: number;
  sl_seconds: number;
}

export interface ReportColumn {
  key: string;
  label: string;
  kind: "group" | "measure";
  unit?: "count" | "percent" | "seconds";
}

export interface ReportResult {
  columns: ReportColumn[];
  rows: ({ group: { key: string | null; label: string }[] } & Record<string, unknown>)[];
  totals: Record<string, number>;
  truncated: boolean;
  period: { from: string; to: string; label: string; timezone: string };
}

export interface ReportOptions {
  extensions: { id: string; label: string }[];
  dids: string[];
  trunks: { id: string; label: string }[];
  queues: { id: string; label: string }[];
  ring_groups: { id: string; label: string }[];
  time_conditions: { id: string; label: string }[];
  groups: Record<ReportGroup, string>;
  measures: Record<ReportMeasure, { label: string; unit: string }>;
}

export interface ReportSchedule {
  frequency: "daily" | "weekly" | "monthly";
  hour: number;
  weekday: number;
  day: number;
  recipients: string[];
}

export interface SavedReport {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  definition: ReportDefinition;
  owner_user_id: string | null;
  shared: boolean;
  schedule: ReportSchedule | null;
  next_run_at: string | null;
  last_sent_at: string | null;
  last_error: string | null;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------- module catalog (docs/MODULE_CATALOG.md)

export interface CatalogVersionItem {
  version: string;
  core_api: string;
  url: string;
  sha256: string;
  size: number;
  released: string | null;
  notes: string | null;
  source: string;
  compatible: boolean;
  problem: string | null;
}

export interface CatalogModuleItem {
  id: string;
  name: string;
  summary: string | null;
  publisher: string | null;
  homepage: string | null;
  source: string;
  installed_version: string | null;
  state: string;
  latest_compatible: string | null;
  update_available: boolean;
  versions: CatalogVersionItem[];
}

export interface CatalogSourceItem {
  id: string;
  name: string;
  url: string;
  is_enabled: boolean;
  signed_by: string | null;
  modules: number;
  last_fetched_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface ModuleConfigField {
  key: string;
  label: string;
  type: "string" | "integer" | "boolean" | "choice" | "secret";
  help?: string | null;
  default?: unknown;
  required?: boolean;
  min?: number | null;
  max?: number | null;
  max_length?: number | null;
  choices?: string[] | null;
  scope?: "installation" | "organization";
}

// --- Integrations (docs/INTEGRATIONS.md) ------------------------------------

export interface SsoProviderPublic {
  id: string;
  kind: "google" | "microsoft" | "oidc";
  name: string;
}

export type JitRole = "standard_user" | "read_only" | "technician" | "site_admin" | "org_admin";

export interface IdentityProviderOut {
  id: string;
  kind: "google" | "microsoft" | "oidc";
  name: string;
  issuer: string;
  client_id: string;
  has_secret: boolean;
  allowed_domains: string[];
  organization_id: string;
  create_accounts: boolean;
  default_role_key: JitRole;
  enabled: boolean;
  redirect_uri: string;
  linked_users: number;
  metadata_fetched_at: string | null;
  created_at: string;
}

export interface IdentityProviderInput {
  kind: "google" | "microsoft" | "oidc";
  name: string;
  issuer?: string | null;
  client_id: string;
  client_secret?: string | null;
  allowed_domains: string[];
  organization_id: string;
  create_accounts: boolean;
  default_role_key: JitRole;
  enabled: boolean;
}

export interface ProviderTestOut {
  ok: boolean;
  message: string;
  authorization_endpoint: string | null;
  keys: number;
}

export interface TestSignInOut {
  request_id: string;
  url: string;
}

export interface TestSignInResult {
  status: "waiting" | "done" | "expired";
  result: Record<string, unknown> | null;
}

export interface UserIdentityOut {
  id: string;
  provider_id: string;
  provider_name: string;
  email: string;
  created_at: string;
  last_used_at: string | null;
}

export interface IntegrationScope {
  key: string;
  description: string;
}

export interface IntegrationOut {
  id: string;
  organization_id: string;
  name: string;
  scopes: string[];
  allowed_networks: string[];
  expires_at: string | null;
  expired: boolean;
  token_prefix: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  created_at: string;
  created_by: string;
}

export interface IntegrationTokenOut extends IntegrationOut {
  token: string;
}

export interface WebhookEventDef {
  name: string;
  group: string;
  description: string;
  live: boolean;
  module: string | null;
}

export interface WebhookOut {
  id: string;
  organization_id: string;
  name: string;
  url: string;
  allow_http: boolean;
  events: string[];
  enabled: boolean;
  disabled_reason: string | null;
  failing_since: string | null;
  last_delivery_at: string | null;
  last_status: "delivered" | "failed" | null;
  pending: number;
  created_at: string;
  created_by: string;
}

export interface WebhookSecretOut extends WebhookOut {
  secret: string;
}

export interface WebhookDeliveryOut {
  id: string;
  event: string;
  status: "pending" | "delivered" | "failed";
  attempts: number;
  max_attempts: number;
  created_at: string;
  next_attempt_at: string;
  delivered_at: string | null;
  response_code: number | null;
  duration_ms: number | null;
  error: string | null;
  response_excerpt: string | null;
  payload: Record<string, unknown>;
}

// --- Multi-tenancy (docs/MULTI_TENANCY.md) ------------------------------------

export interface MultiTenancyCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface MultiTenancyStatus {
  enabled: boolean;
  active_organizations: number;
  organizations: { id: string; name: string; slug: string; namespace: string; is_active: boolean }[];
  shared: string[];
  checks?: MultiTenancyCheck[];
}

// --- Central management (docs/CENTRAL_MANAGEMENT.md) ---------------------------

export interface CentralConsole {
  enabled: boolean;
  fingerprint: string | null;
  address: string;
  offline_minutes: number;
  instances: number;
}

export interface CentralToken {
  id: string;
  label: string | null;
  policy_id: string | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
}

export interface CentralTokenCreated extends CentralToken {
  token: string;
  address: string;
  fingerprint: string;
}

export type CentralStatus = "ok" | "degraded" | "failed" | "online" | "offline" | "revoked";

export interface CentralInstanceRow {
  instance_id: string;
  label: string | null;
  name: string;
  version: string | null;
  status: CentralStatus;
  policy_id: string | null;
  policy_name: string | null;
  policy_state: string | null;
  enrolled_at: string;
  last_seen_at: string | null;
  last_address: string | null;
  registered: number | null;
  active_calls: number | null;
  extensions: number | null;
  alerts: number;
  update_available: string | null;
}

export interface CentralCommandRow {
  id: string;
  kind: string;
  arguments: Record<string, unknown>;
  created_by: string;
  created_at: string;
  expires_at: string;
  delivered_at: string | null;
  completed_at: string | null;
  outcome: string | null;
  message: string | null;
}

export interface CentralInstanceDetail extends CentralInstanceRow {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the instance report is free-form
  report: Record<string, any> | null;
  fingerprint: string;
  revoked_at: string | null;
  samples: { at: string; registered: number | null; active_calls: number | null; alerts: number | null; status: string }[];
  commands: CentralCommandRow[];
}

export interface CentralPolicyDocument {
  updates?: {
    policy: { mode: string; maintenance_window?: { days: string[]; start: string; duration_minutes: number } | null; [k: string]: unknown };
    source_url?: string | null;
    recipients?: string[] | null;
  };
  firewall_allow?: { cidr: string; comment?: string | null }[];
  alert_recipients?: string[];
  notice?: string;
}

export interface CentralPolicy {
  id: string;
  name: string;
  description: string | null;
  document: CentralPolicyDocument;
  version: number;
  is_default: boolean;
  instances: number;
  updated_at: string;
}

export interface CentralMembership {
  enrolled: boolean;
  console_url?: string;
  console_name?: string | null;
  console_fingerprint?: string | null;
  fingerprint?: string | null;
  enrolled_at?: string;
  last_contact?: string | null;
  last_attempt?: string | null;
  last_error?: string | null;
  revoked?: boolean;
  accepted?: Record<string, boolean>;
  policy?: { name: string | null; version: number; results: Record<string, string>; document: CentralPolicyDocument; applied_at: string | null } | null;
  log?: { at: string; what: string; detail: unknown }[];
}

export interface CentralNotice {
  text: string | null;
  console_name: string | null;
  managed: Record<string, boolean>;
}

// ----------------------------------------------------------------- backups (Milestone 17)

export interface BackupSettings {
  enabled: boolean;
  time: string;
  keep: { daily_days: number; weekly_weeks: number; upgrades: number };
  recordings: boolean;
  recipients: string[];
  destinations: BackupDestination[];
  ssh_public: string;
}

/** Where backups are copied (docs/PRODUCTION_HARDENING.md §2.7); never a secret. */
export interface BackupDestination {
  id: string;
  kind: "directory" | "sftp" | "s3" | "gdrive";
  name: string;
  enabled: boolean;
  keep: { daily_days: number; weekly_weeks: number; upgrades: number } | null;
  target: string;
  path?: string;
  host?: string;
  port?: number;
  username?: string;
  host_key?: string | null;
  host_key_fingerprint?: string | null;
  endpoint?: string;
  bucket?: string;
  region?: string;
  prefix?: string;
  access_key_id?: string;
  addressing?: "path" | "virtual";
  drive_id?: string;
  folder?: string;
  client_email?: string | null;
  has_secret?: boolean;
  last: { state: "ok" | "failed"; at: string; error?: string | null; count?: number; copied?: string[] } | null;
}

export interface BackupDestinationTest {
  state: "ok" | "failed" | "host_key";
  message: string;
  host_key?: string;
  fingerprint?: string | null;
}

export interface BackupRow {
  id: string;
  name: string;
  kind: "scheduled" | "manual" | "upgrade" | string;
  started_at: string;
  finished_at: string | null;
  state: "running" | "verified" | "failed" | "deleted" | string;
  path: string;
  encrypted: boolean;
  recipients: string[];
  bytes: number;
  parts: { name: string; bytes: number; sha256: string }[];
  copies: Record<string, { state: string; at: string; error?: string | null; name?: string }>;
  verify: { ok?: boolean | null; restore?: boolean; schema?: boolean; parts?: Record<string, boolean> };
  version: string | null;
  schema: string | null;
  error: string | null;
  created_by: string;
}

export interface BackupSummary {
  enabled: boolean;
  last_good_at: string | null;
  last_state: string | null;
  last_error: string | null;
  stale: boolean;
  encrypted: boolean;
  count: number;
}

export interface BackupStatus {
  state: "idle" | "running" | "finished" | "failed" | string;
  kind?: string;
  step?: string;
  started_at?: string;
  finished_at?: string | null;
  error?: string | null;
  backup?: string | null;
}

export interface MyExtension {
  id: string;
  number: string;
  display_name: string;
  organization_id: string;
  organization_name: string;
  is_enabled: boolean;
  registration: Registration | null;
}

// ----------------------------------------------------------------- extension state and feature codes (Milestone 18)

export interface ExtensionState {
  dnd: boolean;
  cf_always: string | null;
  cf_busy: string | null;
  cf_no_answer: string | null;
  /** While no phone of the extension is registered (issue #165). */
  cf_unavailable?: string | null;
  /** Issue #163: a second caller hears busy while a call is up. */
  call_waiting_off?: boolean;
  /** Issue #163: outside callers who withhold their number are refused. */
  anonymous_reject?: boolean;
  /** Callers who still ring while Do Not Disturb is on (issue #170). */
  dnd_allow?: string[];
  fmfm_enabled: boolean;
  ring_seconds: number;
  /** Presence shown to colleagues (docs/USER_PORTAL.md §7). */
  presence?: PresenceState;
  presence_message?: string | null;
  updated_at: string | null;
  updated_by: "phone" | "user" | "admin" | "sync" | string | null;
}

export type PresenceState = "available" | "away" | "busy" | "meeting" | "lunch" | "out";
export interface Presence {
  state: PresenceState;
  label: string;
  message: string | null;
  states: { key: PresenceState; label: string }[];
  applied: Record<string, unknown>;
}
export interface PresenceRule { dnd?: boolean | null; cf_always?: string | null }

/** A directory entry (docs/COMPANION.md §4) with presence and live status (USER_PORTAL.md §7). */
export interface DirectoryEntry {
  type: "extension" | "ring_group" | "queue" | string;
  id: string;
  number: string;
  name: string;
  organization: string;
  user_display_name: string | null;
  user_email: string | null;
  registered: boolean | null;
  presence?: PresenceState | null;
  presence_message?: string | null;
  on_call?: boolean | null;
}

export interface ClassOfService {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string | null;
  allowed_outbound_routes: { id: string; name: string }[];
  /** null: every feature code. */
  allowed_feature_code_keys: string[] | null;
  allow_external_forwards: boolean;
  allow_external_follow_me: boolean;
  allow_intercom: boolean;
  /** Supervisor codes (issue #167). */
  allow_monitor?: boolean;
  monitor_protected?: boolean;
  allow_fax: boolean;
  max_outbound_calls: number | null;
  extensions: number;
  created_at: string;
  updated_at: string;
}

export interface ClassOfServiceInput {
  organization_id?: string;
  name?: string;
  description?: string | null;
  allowed_outbound_route_ids?: string[];
  allowed_feature_code_keys?: string[] | null;
  all_feature_codes?: boolean;
  allow_external_forwards?: boolean;
  allow_external_follow_me?: boolean;
  allow_intercom?: boolean;
  allow_monitor?: boolean;
  monitor_protected?: boolean;
  allow_fax?: boolean;
  max_outbound_calls?: number | null;
  no_call_limit?: boolean;
}

export interface FollowMeMember {
  type: "extension" | "external";
  target: string;
  ring_seconds: number;
}

export interface FollowMe {
  enabled: boolean;
  strategy: "ringall" | "sequential" | string;
  initial_ring_seconds: number;
  confirm_calls: boolean;
  caller_id_mode: "caller" | "extension" | string;
  members: FollowMeMember[];
  no_answer_destination: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface FeatureCode {
  key: string;
  label: string;
  description: string;
  code: string;
  default_code: string;
  enabled: boolean;
  takes_number: boolean;
  milestone: number;
}

export interface FeatureCodes {
  codes: FeatureCode[];
  /** Codes that are always present and cannot be changed, with what they do. */
  fixed: Record<string, string>;
}

/** A whole set of codes to load as a draft (issue #164), such as an old carrier's code card. */
export interface FeatureCodePreset {
  key: string;
  name: string;
  description: string;
  /** Feature key -> code, every feature. */
  codes: Record<string, string>;
  /** Differences the set cannot remove (fixed codes, features Veyra lacks). */
  notes: string[];
}

// ----------------------------------------------------------------- diagnostics: logs and engine queries (Milestone 18)

export interface LogFiles {
  files: { key: string; label: string; file: string; bytes: number; present: boolean }[];
  max_lines: number;
}

export interface LogTail {
  key: string;
  file: string;
  lines: string[];
  present: boolean;
}

export interface EngineQueries {
  queries: { key: string; command: string; takes_argument: boolean; label: string }[];
}

export interface EngineQueryResult {
  key: string;
  command: string;
  ok: boolean;
  output: string;
}

// ----------------------------------------------------------------- packet captures (Milestone 18)

export type CaptureState = "starting" | "running" | "finished" | "stopped" | "failed" | "deleted" | string;

export interface CaptureFilter {
  hosts: string[];
  nets: string[];
  ports: number[];
  portranges: [number, number][];
  rtp: boolean;
}

export interface CaptureRow {
  id: string;
  label: string;
  state: CaptureState;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number;
  size_limit_mb: number;
  filter: CaptureFilter;
  expression: string;
  rtp: boolean;
  bytes: number;
  packets: number | null;
  error: string | null;
  created_by: string;
  downloadable: boolean;
}

export interface CaptureList {
  captures: CaptureRow[];
  running: number;
  max_running: number;
  limits: { seconds: [number, number]; mb: [number, number] };
}

export interface CaptureTargets {
  sip_ports: number[];
  rtp_range: [number, number];
  extensions: { id: string; number: string; display_name: string; organization_name: string | null; hosts: string[] }[];
  trunks: { id: string; name: string; host: string; port: number }[];
}

export type CaptureTarget = "all_sip" | "extension" | "trunk" | "address";

export interface SipMessage {
  at: string;
  src: string;
  sport: number;
  dst: string;
  dport: number;
  transport: string;
  kind: "request" | "response";
  method: string | null;
  status: number | null;
  reason: string | null;
  call_id: string | null;
  cseq: string | null;
  from: string | null;
  to: string | null;
  user_agent: string | null;
  request_uri: string | null;
}

export interface SipDialog {
  call_id: string;
  first_at: string;
  last_at: string;
  messages: number;
  method: string | null;
  last_status: number | null;
  last_reason: string | null;
  from: string | null;
  to: string | null;
  parties: string[];
}

export interface SipSummary {
  packets_read: number;
  messages: SipMessage[];
  dialogs: SipDialog[];
  truncated: boolean;
}

// ----------------------------------------------------------------- retention (Milestone 17)

export interface RetentionRule {
  key: string;
  label: string;
  description: string;
  days: number;
  default_days: number;
  minimum_days: number;
}

export interface RetentionState {
  rules: RetentionRule[];
  last_run: { at: string; removed: Record<string, number> } | null;
}

export interface RetentionInventoryRow {
  key: string;
  label: string;
  rows: number;
  bytes: number;
  oldest: string | null;
  days: number | null;
  note?: string;
}

// ----------------------------------------------------------------- emergency calling (Milestone 17)

export interface EmergencyCheck {
  key: string;
  ok: boolean;
  label: string;
  detail: string;
  /** Advice only: does not decide whether the site is ready (issue #171). */
  advisory?: boolean;
}

export interface EmergencySiteRow {
  id: string;
  name: string;
  organization_id: string;
  ready: boolean;
  missing: string[];
  extensions: number;
  calls: number;
  elin: string | null;
}

export interface EmergencySettings {
  emergency_caller_id_number: string | null;
  address: string | null;
  attested: boolean;
  attested_by: string | null;
  attested_at: string | null;
  responder_extension_id: string | null;
  responder_number: string | null;
  callback_minutes: number;
  recipients: { emails?: string[]; page_id?: string | null; extensions?: string[]; webhook?: boolean };
  last_test_at: string | null;
  last_test_result: string | null;
  last_notification_test_at: string | null;
}

export interface EmergencyCallRow {
  id: string;
  occurred_at: string;
  site_id: string | null;
  extension_number: string;
  number: string;
  route: string | null;
  caller_id: string | null;
  location: string | null;
  kind: string;
  notifications: Record<string, unknown>;
  callback_until: string | null;
}

export interface EmergencySiteDetail {
  id: string;
  name: string;
  organization_id: string;
  readiness: { ready: boolean; checks: EmergencyCheck[]; extensions: number };
  settings: EmergencySettings;
  calls: EmergencyCallRow[];
  disclaimer: string;
}

/** Fax (docs/USER_PORTAL.md §9). */
export interface FaxInbox {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  context: string;
  recipients: string[];
  station_id: string | null;
  header: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type FaxState = "queued" | "dialling" | "sending" | "sent" | "failed" | "received" | "cancelled";

export interface FaxJob {
  id: string;
  organization_id: string;
  direction: "out" | "in";
  number: string;
  caller_id: string | null;
  remote_id: string | null;
  pages: number;
  state: FaxState | string;
  error: string | null;
  attempts: number;
  user_id: string | null;
  user_name: string | null;
  extension_number: string | null;
  inbox_id: string | null;
  inbox_name: string | null;
  original_name: string | null;
  has_cover: boolean;
  has_file: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  next_attempt_at: string | null;
}

/** Extended absence of a voicemail box (issue #169). */
export interface VoicemailAbsence {
  enabled: boolean;
  starts_on: string | null;
  ends_on: string | null;
  refuse_messages: boolean;
  /** On today (enabled and within the dates). */
  active: boolean;
  /** The worker has put the absence greeting in place. */
  applied: boolean;
}

/** Settings a group of extensions follows (issue #172). */
export interface ExtensionTemplateSettings {
  class_of_service_id?: string | null;
  intercom?: "default" | "allow" | "deny";
  max_registrations?: number | null;
  department_id?: string | null;
  ring_seconds?: number;
  call_waiting_off?: boolean;
  anonymous_reject?: boolean;
  cf_busy?: string | null;
  cf_no_answer?: string | null;
  cf_unavailable?: string | null;
  outbound_caller_id_number?: string | null;
  outbound_caller_id_name?: string | null;
  vm_attach_audio?: boolean;
  vm_delete_after_email?: boolean;
  vm_keep_days?: number | null;
  vm_operator_extension?: string | null;
}

export interface ExtensionTemplate {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  settings: ExtensionTemplateSettings;
  /** Fields the extensions cannot change while they follow the template. */
  locked: (keyof ExtensionTemplateSettings)[];
  extensions: number;
  created_at: string;
  updated_at: string;
}

export interface ExtensionTemplateApply {
  dry_run: boolean;
  extensions: { extension_id: string; number: string; changes: Record<string, { from: unknown; to: unknown }> }[];
  needs_deployment: boolean;
}
