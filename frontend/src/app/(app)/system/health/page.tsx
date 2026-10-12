"use client";

import { useEffect } from "react";
import { MetricCard, Meter } from "@/components/common/Metric";
import { MODULE_STATE, TELEPHONY_STATE } from "@/components/common/labels";
import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  toStatus,
  type Column,
} from "@/components/ui";
import { formatBytes, formatDuration, formatPercent } from "@/lib/format";
import type { HealthComponent, ModuleHealthRow, SystemHealth } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const LABELS: Record<string, { label: string; icon: string }> = {
  database: { label: "Database (PostgreSQL)", icon: "database" },
  telephony: { label: "Telephony engine", icon: "phone" },
  modules: { label: "Modules", icon: "modules" },
};

function detailValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export default function HealthPage() {
  const health = useApiData<SystemHealth>("/system/health");
  const reload = health.reload;
  useEffect(() => {
    const t = window.setInterval(reload, 15_000);
    return () => window.clearInterval(t);
  }, [reload]);
  const h = health.data;

  const moduleColumns: Column<ModuleHealthRow>[] = [
    { key: "id", header: "Module", render: (m) => <span className="mono">{m.module_id}</span> },
    { key: "state", header: "State", render: (m) => <Badge tone={MODULE_STATE[m.state]?.tone ?? "neutral"}>{MODULE_STATE[m.state]?.label ?? m.state}</Badge> },
    { key: "health", header: "Health", render: (m) => <StatusBadge status={toStatus(m.health)} /> },
    { key: "msg", header: "Message", render: (m) => <span className="subtle">{m.message || "—"}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="System health"
        description="Live status of Veyra's components and this server. Refreshes every 15 seconds."
        actions={<Button icon="refresh" onClick={health.reload} loading={health.loading && !!h}>Refresh</Button>}
      />
      {health.error && !h ? <Card><ErrorState title="Could not load health" error={health.error} onRetry={health.reload} /></Card> : !h ? <Card><LoadingState /></Card> : (
        <>
          <Card>
            <div className="row row--between">
              <div className="row"><span className="card__title">Overall</span><StatusBadge status={toStatus(h.status)} /></div>
              <span className="subtle">Veyra {h.version}</span>
            </div>
          </Card>
          <div className="grid grid--3">
            {(Object.entries(h.components) as [string, HealthComponent][]).map(([key, c]) => (
              <Card key={key} title={LABELS[key]?.label ?? key} actions={<StatusBadge status={toStatus(c.status)}
                label={key === "telephony" ? TELEPHONY_STATE[String(c.details.state)] : undefined} />}>
                <p>{c.message || "—"}</p>
                {key !== "modules" ? (
                  <dl className="dl" style={{ marginTop: 12 }}>
                    {Object.entries(c.details).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (
                      <div key={k} style={{ display: "contents" }}><dt>{k.replace(/_/g, " ")}</dt><dd className="mono">{detailValue(v)}</dd></div>
                    ))}
                  </dl>
                ) : null}
              </Card>
            ))}
          </div>
          <div className="grid grid--4">
            <MetricCard icon="cpu" label="CPU" value={formatPercent(h.host.cpu_percent)} hint={h.host.load_average ? `Load average ${h.host.load_average.join(" / ")}` : "Unavailable"}>
              <Meter percent={h.host.cpu_percent} label="CPU utilization" />
            </MetricCard>
            <MetricCard icon="memory" label="Memory" value={formatPercent(h.host.memory_percent)} hint={`${formatBytes(h.host.memory_available_bytes)} available of ${formatBytes(h.host.memory_total_bytes)}`}>
              <Meter percent={h.host.memory_percent} label="Memory utilization" />
            </MetricCard>
            <MetricCard icon="disk" label={`Disk ${h.host.disk_path}`} value={formatPercent(h.host.disk_percent)} hint={`${formatBytes(h.host.disk_free_bytes)} free of ${formatBytes(h.host.disk_total_bytes)}`}>
              <Meter percent={h.host.disk_percent} label="Disk utilization" />
            </MetricCard>
            <MetricCard icon="clock" label="Uptime" value={formatDuration(h.host.uptime_seconds)} hint={`${h.host.cpu_count ?? "?"} CPU cores`} />
          </div>
          <Card title="Modules" flush>
            <DataTable columns={moduleColumns} rows={(h.components.modules.details.modules as ModuleHealthRow[] | undefined) ?? []}
              rowKey={(m) => m.module_id} caption="Module health" empty={<EmptyState compact icon="modules" title="No modules installed" />} />
          </Card>
        </>
      )}
    </div>
  );
}
