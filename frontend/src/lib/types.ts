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
}

export interface SessionInfo {
  user: User;
  permissions: string[];
  is_platform_admin: boolean;
  installation_name: string;
  must_change_password: boolean;
  csrf_token?: string | null;
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
  type: "text" | "textarea" | "integer" | "boolean" | "choice";
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
