// SPDX-License-Identifier: AGPL-3.0-or-later
// Helpers for the High availability page and banner (docs/HIGH_AVAILABILITY.md §10).
import type { Status } from "@/components/ui";
import type { ClusterNode, HaOperation, HaReplication, HaStatus } from "./types";

export const NODE_STATE_STATUS: Record<string, Status> = {
  online: "ok",
  frozen: "degraded",
  joining: "degraded",
  rejoining: "degraded",
  diverged: "failed",
  isolated: "failed",
  removed: "unavailable",
  unknown: "unknown",
  degraded: "degraded",
  offline: "failed",
};

export const OPERATION_LABELS: Record<string, string> = {
  switchover: "Switchover",
  failover: "Failover",
  rejoin: "Rejoin",
  demote: "Demotion",
  resume: "Resume",
  enable: "Enable high availability",
  join: "Join",
};

export const STEP_LABELS: Record<string, string> = {
  freeze: "Freeze the primary",
  "engine-stop": "Stop the engine",
  "catch-up": "Standby catches up",
  "release-address": "Release the service address",
  "postgres-stop": "Stop PostgreSQL",
  promote: "Promote the database",
  epoch: "New epoch",
  migrate: "Apply migrations",
  deploy: "Deploy the configuration",
  "hold-address": "Take the service address",
  "rejoin-peer": "Rejoin the other node",
  unfreeze: "Unfreeze",
  fence: "Fence the old primary",
  resync: "Resynchronise the database",
  "postgres-start": "Start PostgreSQL",
  role: "Record the role",
  sync: "File sync",
  demote: "Give up primary duties",
  "node-key": "Node key",
  "replication-password": "Replication credential",
  certificates: "Certificates",
  postgres: "Configure PostgreSQL",
  database: "Record the primary",
  join: "Ask the primary",
  basebackup: "Copy the database",
  "postgres-conf": "Configure PostgreSQL",
};

export const EVENT_LABELS: Record<string, string> = {
  ha_enabled: "High availability enabled",
  node_joined: "Node joined",
  node_removed: "Node removed",
  switchover_started: "Switchover started",
  switchover_epoch: "Switchover: new epoch",
  switchover_completed: "Switchover completed",
  switchover_aborted: "Switchover aborted",
  switchover_failed: "Switchover failed",
  failover_started: "Failover started",
  failover_epoch: "Failover: new epoch",
  failover_completed: "Failover completed",
  fenced: "Node fenced",
  demoted: "Node demoted",
  rejoined: "Node rejoined",
  isolated: "Primary isolated",
  resumed: "Primary resumed",
  ha_operation_failed: "Operation failed",
};

export function nodeStatus(n: Pick<ClusterNode, "state" | "stale">): Status {
  if (n.stale) return "unknown";
  return NODE_STATE_STATUS[n.state] ?? "unknown";
}

/** "12.3 MB" style lag label; "—" when unknown. */
export function lagLabel(r: HaReplication | null | undefined): string {
  if (!r || r.lag_bytes === null || r.lag_bytes === undefined) return "—";
  const mb = r.lag_bytes / (1024 * 1024);
  const bytes = mb >= 1 ? `${mb.toFixed(1)} MB` : r.lag_bytes < 1024 ? `${r.lag_bytes} B` : `${(r.lag_bytes / 1024).toFixed(0)} KB`;
  return r.lag_seconds !== null && r.lag_seconds !== undefined ? `${bytes} · ${r.lag_seconds.toFixed(1)} s` : bytes;
}

/** What replication is doing, in words, from either node's point of view. */
export function replicationLabel(r: HaReplication | null | undefined): string {
  if (!r) return "Unknown";
  if (r.db_role === "down") return "Database down";
  if (r.db_role === "standby") return r.receiver === "streaming" ? "Streaming from the primary" : "Not receiving";
  if (r.state === "streaming") return r.synchronous ? "Streaming (synchronous)" : "Streaming";
  if (r.state) return r.state;
  return "No standby connected";
}

/** The dashboard tile and the banner tone. */
export function overallStatus(s: Pick<HaStatus, "summary" | "ha_enabled">): Status {
  if (!s.ha_enabled) return "unavailable";
  if (s.summary === "healthy") return "ok";
  if (s.summary === "degraded") return "degraded";
  if (s.summary === "isolated") return "failed";
  return "unknown";
}

export function operationProgress(op: HaOperation | null | undefined): { done: number; total: number; current: string | null } {
  if (!op) return { done: 0, total: 0, current: null };
  const done = op.steps.filter((s) => s.status === "ok" || s.status === "skipped").length;
  const current = op.steps.find((s) => s.status === "running")?.name ?? null;
  return { done, total: op.steps.length, current };
}

export function isStandby(s: Pick<HaStatus, "local"> | undefined): boolean {
  return !!s && s.local.role === "secondary";
}

export function stepLabel(name: string): string {
  return STEP_LABELS[name] ?? name;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value >= 10 ? `${value.toFixed(0)} s` : `${value.toFixed(1)} s`;
}
