// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { EnableDialog, FailoverDialog, FencingDialog, JoinTokenDialog, ReplicationModeField, SwitchoverDialog, SyncField } from "@/components/ha/HaDialogs";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { EVENT_LABELS, OPERATION_LABELS, lagLabel, nodeStatus, operationProgress, overallStatus, replicationLabel, seconds, stepLabel } from "@/lib/ha";
import type { ClusterNode, HaEvent, HaJoinToken, HaJoinTokenCreated, HaOperation, HaStatus, HaSyncState } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

function NodeCard({ n, status, manage, onSwitchover, onRejoin, onRemove }: {
  n: ClusterNode; status: HaStatus; manage: boolean;
  onSwitchover: () => void; onRejoin: () => void; onRemove: () => void;
}) {
  const local = n.node_name === status.local.node_name;
  const rep = local ? status.replication : n.replication;
  const canSwitch = manage && status.local.role === "primary" && n.role === "secondary" && !status.operation?.status.includes("running");
  return (
    <Card title={<span className="row" style={{ gap: 8 }}>{n.node_name}{local ? <Badge tone="outline">this node</Badge> : null}</span>}
      subtitle={n.address ?? n.hostname}
      actions={manage ? (
        <span className="row" style={{ gap: 6 }}>
          {canSwitch ? <Button size="sm" onClick={onSwitchover}>Switch over to {n.node_name}</Button> : null}
          {n.role === "secondary" && ["rejoining", "diverged", "unknown"].includes(n.state) ? <Button size="sm" onClick={onRejoin}>Rejoin</Button> : null}
          {n.role === "secondary" && status.local.role === "primary" ? <Button size="sm" variant="danger" onClick={onRemove}>Remove</Button> : null}
        </span>
      ) : null}>
      <dl className="dl">
        <dt>Role</dt><dd><Badge tone={n.role === "primary" ? "info" : "neutral"}>{n.role}</Badge> <span className="subtle">epoch {n.epoch ?? 0}</span></dd>
        <dt>State</dt><dd><StatusBadge status={nodeStatus(n)} label={n.stale ? "no heartbeat" : n.state} /></dd>
        <dt>Version</dt><dd><span className="mono">{n.software_version ?? "—"}</span>{n.software_version && n.software_version !== status.version ? <Badge tone="warn">differs</Badge> : null}</dd>
        <dt>Database</dt><dd>{n.db_role ?? "unknown"} · {replicationLabel(rep)}</dd>
        <dt>Replication lag</dt><dd>{lagLabel(rep)}</dd>
        {!local && status.local.peer_reachable !== null ? <><dt>Reachable from this node</dt><dd>{status.local.peer_reachable ? "Yes" : <Badge tone="danger">No</Badge>}</dd></> : null}
        <dt>Last heartbeat</dt><dd>{formatRelative(n.last_heartbeat_at)}</dd>
        <dt>File sync</dt><dd>{n.role === "secondary" ? formatRelative(local ? status.sync?.last_success_at : n.sync_at) : "serves the files"}</dd>
        <dt>Service address</dt><dd>{n.holds_address ? <Badge tone="ok">held</Badge> : <span className="subtle">not held</span>}</dd>
      </dl>
    </Card>
  );
}

function SyncCard({ state, manage, starting, onSync }: {
  state: HaSyncState | null; manage: boolean; starting: boolean; onSync: () => void;
}) {
  return (
    <Card title="File sync" actions={manage ? <Button size="sm" icon="refresh" onClick={onSync} loading={starting || !!state?.running} disabled={state?.reachable === false}>Sync now</Button> : null}>
      {!state ? <LoadingState /> : !state.reachable ? (
        <Callout tone="warn" title="The standby does not answer">Its file sync cannot be read or started from here.</Callout>
      ) : (
        <div className="stack stack--sm">
          <dl className="dl">
            <dt>State</dt><dd>{state.running ? <StatusBadge status="degraded" label="Syncing" /> : <StatusBadge status={state.last_error ? "failed" : "ok"} label={state.last_error ? "Last sync failed" : "Idle"} />}</dd>
            <dt>Last success</dt><dd>{formatRelative(state.last_success_at)}</dd>
            <dt>Files still to copy</dt><dd>{state.backlog}</dd>
          </dl>
          {state.last_error ? <Callout tone="warn" title="Last sync failed">{state.last_error}</Callout> : null}
        </div>
      )}
    </Card>
  );
}

function OperationCard({ op }: { op: HaOperation }) {
  const progress = operationProgress(op);
  const tone = op.status === "completed" ? "ok" : op.status === "running" ? "info" : "danger";
  return (
    <Card title={`${OPERATION_LABELS[op.kind] ?? op.kind}${op.target ? ` → ${op.target}` : ""}`}
      subtitle={`${op.status === "running" ? `Step ${progress.done + 1} of ${progress.total}` : op.status} · started ${formatDateTime(op.started_at)} by ${op.actor || "the agent"}`}
      actions={<Badge tone={tone}>{op.status}</Badge>}>
      <ol className="stack stack--xs" style={{ margin: 0, paddingLeft: "1.4em" }}>
        {op.steps.map((s, i) => (
          <li key={`${s.name}-${i}`} className="row" style={{ gap: 8, justifyContent: "space-between" }}>
            <span><StatusBadge status={s.status === "ok" ? "ok" : s.status === "running" ? "degraded" : s.status === "failed" ? "failed" : "unknown"} label={stepLabel(s.name)} />{s.detail ? <span className="subtle"> · {s.detail}</span> : null}</span>
            <span className="subtle mono">{seconds(s.seconds)}</span>
          </li>
        ))}
      </ol>
      {op.error ? <Callout tone="danger" title={op.status === "aborted" ? "Aborted; the primary was put back" : "Failed"}>{op.error}</Callout> : null}
    </Card>
  );
}

export default function HaPage() {
  const { can } = useSession();
  const toast = useToast();
  const manage = can("ha.manage");
  const status = useApiData<HaStatus>("/ha/status");
  const events = useApiData<HaEvent[]>("/ha/events", { limit: 50 });
  const tokens = useApiData<HaJoinToken[]>(manage ? "/ha/join-tokens" : null);
  const [enable, setEnable] = useState(false);
  const [shown, setShown] = useState<HaJoinTokenCreated | null>(null);
  const [switchTo, setSwitchTo] = useState<string | null>(null);
  const [failover, setFailover] = useState(false);
  const [fencing, setFencing] = useState(false);
  const [resume, setResume] = useState(false);
  const [remove, setRemove] = useState<ClusterNode | null>(null);
  const [standalone, setStandalone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [syncStarting, setSyncStarting] = useState(false);
  const s = status.data;
  const running = !!s?.operation && s.operation.status === "running";
  const syncState = useApiData<HaSyncState>(s?.peer ? "/ha/sync-state" : null);
  const syncRunning = !!syncState.data?.running;
  const removed = s?.local.role === "standalone" && s.local.state === "removed";
  const canStandalone = !!s && (removed || (s.ha_enabled && (s.local.role === "secondary" || (s.local.role === "primary" && !s.peer))));

  // Follow a running operation and the heartbeats.
  useEffect(() => {
    const id = setInterval(() => { status.reload(); if (running) events.reload(); }, running ? 2000 : 15000);
    return () => clearInterval(id);
  }, [running, status, events]);

  // Follow a sync started here until the standby says it finished.
  useEffect(() => {
    const id = setInterval(syncState.reload, syncRunning || syncStarting ? 2000 : 30000);
    return () => clearInterval(id);
  }, [syncRunning, syncStarting, syncState]);

  const syncNow = async () => {
    setSyncStarting(true);
    try {
      const out = await api.post<{ started: boolean }>("/ha/sync-now");
      toast.success(out.started ? "File sync started" : "A file sync is already running");
      setTimeout(() => setSyncStarting(false), 3000);
    } catch (err) {
      toast.error("File sync failed to start", errorMessage(err));
      setSyncStarting(false);
    }
    syncState.reload();
  };

  const reloadAll = () => { status.reload(); events.reload(); tokens.reload(); };

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      toast.success(label);
      reloadAll();
    } catch (err) {
      toast.error(`${label} failed`, errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const addNode = () => act("Join token created", async () => {
    const t = await api.post<HaJoinTokenCreated>("/ha/join-tokens", { label: null });
    setShown(t);
  });

  const eventColumns: Column<HaEvent>[] = [
    { key: "when", header: "When", render: (e) => <span className="subtle">{formatDateTime(e.occurred_at)}</span> },
    { key: "type", header: "Event", render: (e) => <span className="table__primary">{EVENT_LABELS[e.event_type] ?? e.event_type}</span> },
    { key: "node", header: "Node", render: (e) => e.node_name ?? "—" },
    { key: "actor", header: "By", render: (e) => e.actor_label },
    { key: "details", header: "Details", render: (e) => <span className="subtle mono" style={{ fontSize: "var(--text-xs)" }}>{summarise(e.details)}</span> },
  ];
  const tokenColumns: Column<HaJoinToken>[] = [
    { key: "label", header: "Token", render: (t) => t.label ?? <span className="subtle">(no label)</span> },
    { key: "created", header: "Created", render: (t) => `${formatDateTime(t.created_at)} by ${t.created_by}` },
    { key: "state", header: "State", render: (t) => t.used_at ? <Badge tone="ok">used by {t.used_by}</Badge> : t.expired ? <Badge tone="neutral">expired</Badge> : <Badge tone="info">valid until {formatDateTime(t.expires_at)}</Badge> },
    { key: "actions", header: "", render: (t) => manage && !t.used_at ? <Button size="sm" onClick={() => act("Token deleted", () => api.del(`/ha/join-tokens/${t.id}`))}>Delete</Button> : null },
  ];

  return (
    <div className="stack">
      <PageHeader title="High availability" description="Two servers, one service: the standby keeps a replica of the database and the files and takes over by a manual switchover or failover."
        actions={s?.ha_enabled && manage ? (
          <span className="row" style={{ gap: 6 }}>
            {s.local.role === "primary" ? <Button icon="plus" onClick={addNode} loading={busy} disabled={!!s.peer}>Add node</Button> : null}
            {s.local.role === "secondary" ? <Button variant="danger" onClick={() => setFailover(true)} disabled={running}>Fail over to this node</Button> : null}
            {s.local.state === "isolated" ? <Button variant="danger" onClick={() => setResume(true)} disabled={running}>Resume as primary</Button> : null}
          </span>
        ) : null} />

      {status.error ? <Card><ErrorState error={status.error} onRetry={status.reload} /></Card> : !s ? <Card><LoadingState /></Card> : !s.ha_enabled ? (
        <>
          {removed ? (
            <Callout tone="warn" title="This server was removed from its pair">
              <div className="stack stack--sm">
                <p>Its phone system stays off, so it cannot register to your carrier alongside the server that is still running. Start it only if this server should now handle calls by itself.</p>
                {manage ? <span><Button variant="danger" onClick={() => setStandalone(true)}>Run on its own</Button></span> : null}
              </div>
            </Callout>
          ) : null}
          <div className="grid grid--3">
            <Card title="Deployment mode"><p className="metric__value">Standalone</p><p className="subtle">This server operates independently.</p></Card>
            <Card title="Database role"><p className="metric__value" style={{ textTransform: "capitalize" }}>{s.database_role ?? "Unknown"}</p><p className="subtle">Accepts writes</p></Card>
            <Card title="HA agent"><p className="metric__value">{s.local.agent ? "Running" : "Not running"}</p><p className="subtle">{s.local.agent ? "Ready to enable high availability" : "veyra-ha-agent must run before HA can be enabled"}</p></Card>
          </div>
          <Card title="Enable high availability" actions={manage ? <Button variant="primary" onClick={() => setEnable(true)} disabled={!s.local.agent}>Enable high availability</Button> : null}>
            <div className="stack stack--sm">
              <p>A second server joins this one as a standby: PostgreSQL streams every change to it, its files are kept in step every 30 seconds, and it runs the web interface read-only. A planned switchover moves the service to the standby in about a minute; when the primary is lost, the operator fails over from the standby&apos;s own interface.</p>
              <p className="subtle">Automatic failover stays off: without a third witness, a node cannot tell a dead peer from a broken link. The pair instead holds a single rule: at most one node ever runs Asterisk, holds the service address and writes the database.</p>
              <p className="subtle">You will need: a service name (phones and browsers use it), a free address on the nodes&apos; network segment, and a second server with the same Ubuntu release.</p>
            </div>
          </Card>
        </>
      ) : (
        <>
          {s.local.state === "isolated" ? (
            <Callout tone="danger" title="This primary is isolated">
              It cannot reach {s.peer?.node_name ?? "its peer"} and is not serving calls, because the peer may have taken over. If the peer is really down, choose <strong>Resume as primary</strong>. If the peer is up, fix the link; this node rejoins by itself.
            </Callout>
          ) : s.local.frozen ? (
            <Callout tone="warn" title="Frozen for a switchover">Writes are refused until the switchover completes or is aborted.</Callout>
          ) : null}
          {s.local.role === "secondary" ? (
            <Callout tone="info" title="Standby node">Manage the system at <a href={`https://${s.service.name || s.peer?.node_name || ""}/`}>{s.service.name || s.peer?.node_name}</a>. This interface shows the pair and offers failover.</Callout>
          ) : null}

          <section aria-label="Cluster" className="grid grid--3">
            <Card title="Cluster"><p className="metric__value"><StatusBadge status={overallStatus(s)} label={s.summary ?? "unknown"} /></p><p className="subtle">epoch {s.epoch} · {s.nodes.length} node{s.nodes.length === 1 ? "" : "s"}</p></Card>
            <Card title="Service" actions={manage && !s.peer ? null : undefined}>
              <p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{s.service.name || "—"}</p>
              <p className="subtle">{s.service.address}/{s.service.prefix} on {s.service.interface} · held by {s.service.holder ?? "nobody"}</p>
            </Card>
            <Card title="Fencing" actions={manage ? <Button size="sm" onClick={() => setFencing(true)}>Configure</Button> : null}>
              <p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{s.fencing.configured ? "Proxmox" : "Manual confirmation"}</p>
              <p className="subtle">{s.fencing.configured ? "The old primary's VM is stopped before a failover." : "The operator confirms the primary is off before a failover."}</p>
            </Card>
          </section>

          {s.operation ? <OperationCard op={s.operation} /> : null}

          {manage && canStandalone ? (
            <Card title="Leave the pair" actions={<Button variant="danger" onClick={() => setStandalone(true)} disabled={running}>Run on its own</Button>}>
              <p className="subtle">{s.local.role === "secondary" ? "For a standby whose primary is gone for good, or that was removed while it was away. It is refused while the primary still answers." : "This server has no standby. It stops using the service address and goes back to being a single server."}</p>
            </Card>
          ) : null}

          <section aria-label="Nodes" className="grid grid--2">
            {s.nodes.filter((n) => n.role === "primary" || n.role === "secondary").map((n) => (
              <NodeCard key={n.id} n={n} status={s} manage={manage}
                onSwitchover={() => setSwitchTo(n.node_name)}
                onRejoin={() => act(`Rejoining ${n.node_name}`, () => api.post(`/ha/nodes/${n.id}/rejoin`))}
                onRemove={() => setRemove(n)} />
            ))}
            {!s.peer ? (
              <Card title="Second node">
                <EmptyState compact icon="server" title="No standby yet">
                  {manage ? "Use “Add node” for a join token and run the installer on the second server with it." : "A platform administrator adds the second node."}
                </EmptyState>
              </Card>
            ) : null}
          </section>

          {s.peer ? <SyncCard state={syncState.data ?? null} manage={manage} starting={syncStarting} onSync={syncNow} /> : null}

          {manage && s.local.role === "primary" ? (
            <Card title="Options">
              <div className="stack stack--sm">
                <ReplicationModeField status={s} onChanged={status.reload} />
                <SyncField status={s} onChanged={status.reload} />
              </div>
            </Card>
          ) : null}

          {manage && tokens.data && tokens.data.length ? (
            <Card title="Join tokens" flush>
              <DataTable columns={tokenColumns} rows={tokens.data} rowKey={(t) => t.id} caption="Join tokens" />
            </Card>
          ) : null}

          <Card title="Events" flush actions={<Button size="sm" icon="refresh" onClick={events.reload} loading={events.loading && !!events.data}>Refresh</Button>}>
            {events.error ? <ErrorState compact error={events.error} onRetry={events.reload} /> : (
              <DataTable columns={eventColumns} rows={events.data ?? []} rowKey={(e) => String(e.id)} caption="Cluster events"
                empty={<EmptyState compact icon="clock" title="No events yet">Switchovers, failovers and role changes are recorded here.</EmptyState>} />
            )}
          </Card>
        </>
      )}

      {s ? <EnableDialog open={enable} status={s} onClose={() => setEnable(false)} onDone={reloadAll} /> : null}
      <JoinTokenDialog token={shown} onClose={() => setShown(null)} />
      <SwitchoverDialog open={!!switchTo} target={switchTo} onClose={() => setSwitchTo(null)} onDone={reloadAll} />
      {s ? <FailoverDialog open={failover} status={s} onClose={() => setFailover(false)} onDone={reloadAll} /> : null}
      <FencingDialog open={fencing} nodes={(s?.nodes ?? []).map((n) => n.node_name)} onClose={() => setFencing(false)} onSaved={status.reload} />
      <ConfirmDialog open={resume} title="Resume as primary" confirmLabel="Resume" tone="danger" typeToConfirm="RESUME" busy={busy}
        onCancel={() => setResume(false)} onConfirm={() => act("Resuming primary duties", () => api.post("/ha/resume")).then(() => setResume(false))}>
        <p>Only when {s?.peer?.node_name ?? "the peer"} is really down. If it took over while this node could not reach it, resuming here creates two primaries.</p>
      </ConfirmDialog>
      <ConfirmDialog open={!!remove} title={`Remove ${remove?.node_name ?? ""}`} confirmLabel="Remove" tone="danger" typeToConfirm={remove?.node_name ?? ""} busy={busy}
        onCancel={() => setRemove(null)} onConfirm={() => remove ? act(`${remove.node_name} removed`, () => api.del(`/ha/nodes/${remove.id}`)).then(() => setRemove(null)) : undefined}>
        <p>The node leaves the cluster and its replication slot is dropped. Its phone system stays off until someone chooses <strong>Run on its own</strong> on its High availability page. With one node left, this installation is standalone again; the service address stays here.</p>
      </ConfirmDialog>
      <ConfirmDialog open={standalone} title="Run this server on its own" confirmLabel="Run on its own" tone="danger" typeToConfirm={s?.local.node_name ?? ""} busy={busy}
        onCancel={() => setStandalone(false)} onConfirm={() => act("This server now runs on its own", () => api.post("/ha/standalone")).then(() => setStandalone(false))}>
        <p>{s?.local.node_name} leaves the pair, its database starts accepting changes, and its phone system starts. It lets go of the service address, so phones that use it need another path to this server.</p>
        {s?.local.role === "secondary" ? <p><strong>Only if {s.peer?.node_name ?? "the primary"} is off or gone for good.</strong> If only the network between them is down, you get two servers taking calls and two diverging databases, and one server&apos;s changes will be lost.</p> : null}
        <p>You may have to sign in again. To make a pair again, add a new standby with a join token.</p>
      </ConfirmDialog>
    </div>
  );
}

function summarise(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([k]) => k !== "steps")
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" ")
    .slice(0, 160);
}
