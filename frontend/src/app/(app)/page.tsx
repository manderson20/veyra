"use client";

import Link from "next/link";
import { useEffect } from "react";
import { MetricCard, Meter } from "@/components/common/Metric";
import { OUTCOME, TELEPHONY_STATE } from "@/components/common/labels";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  toStatus,
} from "@/components/ui";
import { formatBytes, formatDuration, formatPercent, formatRelative } from "@/lib/format";
import type { AuditEvent, AvailableUpdate, Page, SystemHealth } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const REFRESH_MS = 30_000;

function NotAvailable({ text }: { text: string }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <Badge tone="outline">Not available yet</Badge>
      <span className="subtle">{text}</span>
    </span>
  );
}

export default function Dashboard() {
  const { session, can } = useSession();
  const health = useApiData<SystemHealth>(can("system.health.read") ? "/system/health" : null);
  const updates = useApiData<AvailableUpdate[]>(can("updates.read") ? "/updates/available" : null);
  const audit = useApiData<Page<AuditEvent>>(can("audit.read") ? "/audit" : null, { limit: 6 });
  const reloadHealth = health.reload;

  useEffect(() => {
    const t = window.setInterval(reloadHealth, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reloadHealth]);

  const h = health.data;
  return (
    <div className="stack">
      <PageHeader
        title={`Welcome, ${session?.user.display_name.split(" ")[0] ?? ""}`}
        description={session?.installation_name}
        actions={can("system.health.read") ? <Button icon="refresh" onClick={health.reload} loading={health.loading && !!h}>Refresh</Button> : null}
      />

      {!can("system.health.read") ? (
        <Card><EmptyState icon="lock" title="No dashboard access">Your role does not include system health. Ask an administrator if you need it.</EmptyState></Card>
      ) : health.error && !h ? (
        <Card><ErrorState title="Could not load system health" error={health.error} onRetry={health.reload} /></Card>
      ) : !h ? (
        <Card><LoadingState /></Card>
      ) : (
        <>
          <section aria-label="Service status" className="grid grid--4">
            <MetricCard icon="activity" label="Veyra" value={<StatusBadge status={toStatus(h.status)} label={h.status === "ok" ? "All systems normal" : undefined} />} hint={`Version ${h.version}`} />
            <MetricCard icon="database" label="Database" value={<StatusBadge status={toStatus(h.components.database.status)} />}
              hint={h.components.database.details.latency_ms !== undefined ? `PostgreSQL ${String(h.components.database.details.version ?? "")} · ${String(h.components.database.details.latency_ms)} ms` : h.components.database.message} />
            <MetricCard icon="phone" label="Telephony engine"
              value={<StatusBadge status={toStatus(h.components.telephony.status)} label={TELEPHONY_STATE[String(h.components.telephony.details.state)] ?? undefined} />}
              hint={h.components.telephony.message} />
            <MetricCard icon="modules" label="Modules" value={<StatusBadge status={toStatus(h.components.modules.status)} />} hint={h.components.modules.message} />
          </section>

          <section aria-label="Server resources" className="grid grid--4">
            <MetricCard icon="cpu" label="CPU" value={formatPercent(h.host.cpu_percent)}
              hint={h.host.load_average ? `Load ${h.host.load_average.join(" / ")} · ${h.host.cpu_count ?? "?"} cores` : "Unavailable"}>
              <Meter percent={h.host.cpu_percent} label="CPU utilization" />
            </MetricCard>
            <MetricCard icon="memory" label="Memory" value={formatPercent(h.host.memory_percent)}
              hint={h.host.memory_total_bytes ? `${formatBytes((h.host.memory_total_bytes ?? 0) - (h.host.memory_available_bytes ?? 0))} of ${formatBytes(h.host.memory_total_bytes)}` : "Unavailable"}>
              <Meter percent={h.host.memory_percent} label="Memory utilization" />
            </MetricCard>
            <MetricCard icon="disk" label={`Disk (${h.host.disk_path})`} value={formatPercent(h.host.disk_percent)}
              hint={h.host.disk_total_bytes ? `${formatBytes(h.host.disk_free_bytes)} free of ${formatBytes(h.host.disk_total_bytes)}` : "Unavailable"}>
              <Meter percent={h.host.disk_percent} label="Disk utilization" />
            </MetricCard>
            <MetricCard icon="clock" label="Uptime" value={formatDuration(h.host.uptime_seconds)} hint="Since the server last started" />
          </section>

          <div className="grid grid--2">
            <Card title="Calls and registrations" subtitle="Live telephony activity">
              <dl className="dl">
                <dt>Active calls</dt>
                <dd>{h.active_calls === null ? <NotAvailable text="Arrives with SIP calling (Milestone 5)." /> : h.active_calls}</dd>
                <dt>Registered extensions</dt>
                <dd>{h.registrations === null ? <NotAvailable text="Arrives with SIP registration (Milestone 5)." /> : h.registrations}</dd>
                <dt>SIP trunks</dt>
                <dd><NotAvailable text="Arrives with SIP trunks (Milestone 6)." /></dd>
              </dl>
            </Card>
            <Card title="Cluster and updates" actions={<Link href="/system/ha/" className="subtle">Details</Link>}>
              <dl className="dl">
                <dt>Deployment</dt>
                <dd>{h.cluster.ha_enabled ? "High availability" : "Standalone"}</dd>
                <dt>Database role</dt>
                <dd>{h.cluster.database_role ?? "Unknown"}</dd>
                <dt>Automatic failover</dt>
                <dd>{h.cluster.automatic_failover ? "Enabled" : "Disabled"}</dd>
                <dt>Available updates</dt>
                <dd>
                  {!can("updates.read") ? "—" : updates.error ? "Could not load" : updates.data === undefined ? "…" : (
                    <Link href="/updates/">{updates.data.length === 0 ? "Up to date (as of last check)" : `${updates.data.length} available`}</Link>
                  )}
                </dd>
              </dl>
            </Card>
          </div>
        </>
      )}

      {can("audit.read") ? (
        <Card title="Recent activity" flush actions={<Link href="/audit/" className="subtle">View audit log</Link>}>
          {audit.error ? (
            <ErrorState compact error={audit.error} onRetry={audit.reload} />
          ) : !audit.data ? (
            <LoadingState />
          ) : audit.data.items.length === 0 ? (
            <EmptyState compact icon="audit" title="No activity yet" />
          ) : (
            <ul className="list-plain">
              {audit.data.items.map((e) => (
                <li key={e.id} className="list-row">
                  <span style={{ minWidth: 0 }}>
                    <span className="mono">{e.action}</span>
                    <span className="subtle" style={{ display: "block" }}>{e.actor_label}{e.target_type ? ` · ${e.target_type}` : ""}</span>
                  </span>
                  <span className="row" style={{ flexWrap: "nowrap" }}>
                    <Badge tone={OUTCOME[e.outcome] ?? "neutral"}>{e.outcome}</Badge>
                    <span className="subtle nowrap">{formatRelative(e.occurred_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
    </div>
  );
}
