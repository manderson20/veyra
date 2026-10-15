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
  milestone?: number;
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

export interface Registration {
  registered: boolean;
  channels: number;
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
}

export interface ClusterStatus {
  deployment_mode: string;
  ha_enabled: boolean;
  automatic_failover: boolean;
  automatic_failover_reason: string;
  database_role: string | null;
  replication: { state: string } | null;
  nodes: ClusterNode[];
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
  delete: boolean;
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
  maintenance_window: Record<string, unknown> | null;
  updated_at: string;
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
  state: "online" | "offline" | "unknown";
  reachable: boolean | null;
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
  default_caller_id: string | null;
  caller_id_header: CallerIdHeader;
  dtmf_mode: DtmfMode;
  qualify_frequency: number;
  register_expiry: number;
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
  default_caller_id?: string | null;
  caller_id_header?: CallerIdHeader;
  dtmf_mode?: DtmfMode;
  qualify_frequency?: number;
  register_expiry?: number;
}

export type DestinationType = "extension" | "voicemail" | "voicemail_box" | "ivr" | "ring_group" | "queue" | "hangup";

/** A call destination as the API reports it (docs/VOICEMAIL_IVR.md §6, RING_GROUPS_QUEUES.md §5). */
export interface Destination {
  type: DestinationType | "missing";
  extension_id: string | null;
  ivr_id: string | null;
  ring_group_id?: string | null;
  queue_id?: string | null;
  voicemail_box_id?: string | null;
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
}

export type RouteDestinationType = "extension" | "voicemail" | "voicemail_box" | "ivr" | "ring_group" | "queue";

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
  time_condition_id?: string | null;
  after_hours_type?: RouteDestinationType;
  after_hours_extension_id?: string | null;
  after_hours_ivr_id?: string | null;
  after_hours_ring_group_id?: string | null;
  after_hours_queue_id?: string | null;
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
  is_enabled: boolean;
  patterns: OutboundPattern[];
  /** Rendered Asterisk extensions, e.g. `_9NXXNXXXXXX`. */
  examples: string[];
  /** Failover order. */
  trunks: RouteTrunk[];
  caller_id_number: string | null;
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
  is_enabled?: boolean;
  patterns?: OutboundPattern[];
  trunk_ids?: string[];
  caller_id_number?: string | null;
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
  open_now: boolean;
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
  ring_seconds: number;
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
  ring_seconds?: number;
  is_enabled?: boolean;
}

export interface MyVoicemail {
  id: string;
  extension_id: string;
  extension_number: string;
  extension_name: string;
  email: string | null;
  ring_seconds: number;
  is_enabled: boolean;
}

export type AudioKind = "prompt" | "bell" | "announcement" | "greeting" | "music";

export interface Prompt {
  id: string;
  organization_id: string;
  organization_name: string;
  name: string;
  slug: string;
  description: string | null;
  source: "upload" | "recording";
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
}

export type RingGroupStrategy = "ringall" | "sequential";

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
  caller_id_prefix?: string | null;
  music?: QueueMusic;
  moh_class_id?: string | null;
  failover?: DestinationInput;
  members?: string[];
  is_enabled?: boolean;
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

export type LineKeyType = "line" | "blf" | "speed_dial" | "page";

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
export type CallOutcome = "answered" | "missed" | "busy" | "failed" | "voicemail" | "abandoned";

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
}
