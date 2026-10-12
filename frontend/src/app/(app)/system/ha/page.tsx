"use client";

import {
  Badge,
  Callout,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  type Column,
  type Status,
} from "@/components/ui";
import { formatRelative } from "@/lib/format";
import type { ClusterNode, ClusterStatus } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const NODE_STATE: Record<string, Status> = { online: "ok", degraded: "degraded", offline: "failed", maintenance: "degraded", unknown: "unknown" };

export default function HaPage() {
  const status = useApiData<ClusterStatus>("/ha/status");
  const s = status.data;
  const columns: Column<ClusterNode>[] = [
    { key: "name", header: "Node", render: (n) => <span><span className="table__primary" style={{ display: "block" }}>{n.node_name}</span><span className="table__secondary">{n.address ?? n.hostname}</span></span> },
    { key: "role", header: "Role", render: (n) => <Badge tone={n.role === "primary" ? "info" : "neutral"}>{n.role}</Badge> },
    { key: "state", header: "State", render: (n) => <StatusBadge status={NODE_STATE[n.state] ?? "unknown"} label={n.state} /> },
    { key: "hb", header: "Last heartbeat", render: (n) => <span className="subtle">{formatRelative(n.last_heartbeat_at)}</span> },
    { key: "ver", header: "Version", render: (n) => <span className="mono">{n.software_version ?? "—"}</span> },
  ];
  return (
    <div className="stack">
      <PageHeader title="High availability" description="Cluster mode, node roles and failover protection. High availability is optional." />
      {status.error ? <Card><ErrorState error={status.error} onRetry={status.reload} /></Card> : !s ? <Card><LoadingState /></Card> : (
        <>
          <div className="grid grid--3">
            <Card title="Deployment mode"><p className="metric__value">{s.ha_enabled ? "High availability" : "Standalone"}</p>
              <p className="subtle">{s.ha_enabled ? "Active/passive pair" : "This server operates independently."}</p></Card>
            <Card title="Database role"><p className="metric__value" style={{ textTransform: "capitalize" }}>{s.database_role ?? "Unknown"}</p>
              <p className="subtle">{s.database_role === "primary" ? "Accepts writes" : s.database_role === "standby" ? "Read-only replica" : ""}</p></Card>
            <Card title="Automatic failover"><p className="metric__value">{s.automatic_failover ? "Enabled" : "Disabled"}</p>
              <p className="subtle">Switchover is manual and controlled.</p></Card>
          </div>
          <Callout tone="info" title="Why automatic failover is disabled">{s.automatic_failover_reason}</Callout>
          {!s.ha_enabled ? (
            <Callout tone="neutral">
              Enrolling a second node, PostgreSQL replication and controlled switchover arrive in Milestone 16. A standalone
              installation can be converted to a high availability pair later without rebuilding its configuration.
            </Callout>
          ) : null}
          <Card title="Nodes" flush>
            <DataTable columns={columns} rows={s.nodes} rowKey={(n) => n.id} caption="Cluster nodes"
              empty={<EmptyState compact icon="server" title="No nodes registered">Nodes register after first-run setup.</EmptyState>} />
          </Card>
        </>
      )}
    </div>
  );
}
