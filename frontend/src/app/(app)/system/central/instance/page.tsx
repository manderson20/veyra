// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { CommandDialog } from "@/components/central/CentralDialogs";
import { Chart } from "@/components/common/Chart";
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
  SelectField,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { COMMAND_LABELS, STATUS_TONE } from "@/lib/central";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CentralCommandRow, CentralInstanceDetail, CentralPolicy } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

const OUTCOME_TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = { ok: "ok", refused: "warn", failed: "danger", expired: "neutral" };

function commandState(c: CentralCommandRow) {
  if (c.outcome) return <Badge tone={OUTCOME_TONE[c.outcome] ?? "neutral"}>{c.outcome}</Badge>;
  if (c.delivered_at) return <Badge tone="info">Delivered</Badge>;
  if (new Date(c.expires_at) < new Date()) return <Badge tone="neutral">Expired</Badge>;
  return <Badge tone="neutral">Waiting</Badge>;
}

function Settings({ inst, reload }: { inst: CentralInstanceDetail; reload: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("central.write") && inst.status !== "revoked";
  const policies = useApiData<CentralPolicy[]>("/central/policies");
  const [label, setLabel] = useState(inst.label ?? "");
  const [policyId, setPolicyId] = useState(inst.policy_id ?? "");
  const [busy, setBusy] = useState(false);
  useOnChange(inst, (i) => { setLabel(i.label ?? ""); setPolicyId(i.policy_id ?? ""); });
  const dirty = label !== (inst.label ?? "") || policyId !== (inst.policy_id ?? "");

  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/central/instances/${inst.instance_id}`, { label: label.trim() || null, policy_id: policyId || null });
      toast.success("Instance saved", policyId !== (inst.policy_id ?? "") ? "The policy goes out at its next check-in." : undefined);
      reload();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Settings here" footer={editable ? <Button variant="primary" disabled={!dirty} loading={busy} onClick={() => void save()}>Save</Button> : undefined}>
      <div className="form-grid">
        <TextField label="Label" value={label} disabled={!editable} placeholder={inst.name} onChange={(e) => setLabel(e.target.value)} />
        <SelectField label="Policy" value={policyId} disabled={!editable} placeholder="No policy" options={(policies.data ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setPolicyId(e.target.value)} />
      </div>
    </Card>
  );
}

function InstanceView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const toast = useToast();
  const { can } = useSession();
  const editable = can("central.write");
  const data = useApiData<CentralInstanceDetail>(id ? `/central/instances/${id}` : null);
  const [commanding, setCommanding] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!id) return <Card><EmptyState icon="server" title="No instance chosen" /></Card>;
  if (data.error) return <Card><ErrorState error={data.error} onRetry={data.reload} /></Card>;
  const inst = data.data;
  if (!inst) return <Card><LoadingState /></Card>;

  const r = inst.report ?? {};
  const revoked = inst.status === "revoked";
  const act = async (fn: () => Promise<unknown>, done: () => void) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      done();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const revoke = () => act(() => api.post(`/central/instances/${inst.instance_id}/revoke`), () => { setRevoking(false); toast.success("Instance revoked", "Its next check-in is refused."); data.reload(); });
  const remove = () => act(() => api.del(`/central/instances/${inst.instance_id}`), () => { toast.success("Instance removed"); router.push("/system/central/"); });

  const commandColumns: Column<CentralCommandRow>[] = [
    { key: "kind", header: "Command", render: (c) => <span><span className="table__primary" style={{ display: "block" }}>{COMMAND_LABELS[c.kind] ?? c.kind}</span>{Object.keys(c.arguments).length ? <span className="table__secondary mono">{Object.entries(c.arguments).map(([k, v]) => `${k}=${String(v)}`).join(" ")}</span> : null}</span> },
    { key: "by", header: "Queued", render: (c) => <span>{formatRelative(c.created_at)}<span className="table__secondary" style={{ display: "block" }}>by {c.created_by}</span></span> },
    { key: "state", header: "State", render: commandState },
    { key: "msg", header: "Result", render: (c) => c.message ? <span className="subtle">{c.message}</span> : null },
  ];

  const alerts = (r.alerts ?? []) as { rule: string; subject: string; message: string; since: string }[];
  const available = (r.updates?.available ?? []) as { version: string; category: string; state: string; error: string | null }[];
  const modules = (r.modules ?? []) as { id: string; version: string; state: string }[];

  return (
    <div className="stack">
      <PageHeader title={inst.label ?? inst.name} back={{ href: "/system/central/", label: "Central console" }}
        description={<>Enrolled {formatDateTime(inst.enrolled_at)} · last check-in {inst.last_seen_at ? formatRelative(inst.last_seen_at) : "never"}{inst.last_address ? ` from ${inst.last_address}` : ""}</>}
        actions={editable ? (revoked
          ? <Button variant="danger" icon="trash" onClick={() => setRemoving(true)}>Remove</Button>
          : <><Button icon="external" onClick={() => setCommanding(true)}>Send command</Button><Button variant="danger" onClick={() => setRevoking(true)}>Revoke</Button></>) : undefined} />
      {revoked ? <Callout tone="neutral" title="Revoked">Revoked {formatDateTime(inst.revoked_at)}. Its check-ins are refused; remove it here, and leave the console on the instance itself.</Callout> : null}
      <div className="grid grid--3">
        <Card title="Status"><p className="metric__value"><Badge tone={STATUS_TONE[inst.status] ?? "neutral"}>{inst.status}</Badge></p>
          <p className="subtle">Engine {r.health?.engine?.state ?? "unknown"}{r.health?.engine?.version ? ` (${r.health.engine.version})` : ""}</p></Card>
        <Card title="Telephony"><p className="metric__value">{inst.registered ?? "—"} / {inst.extensions ?? "—"}</p>
          <p className="subtle">registered phones / extensions · {inst.active_calls ?? 0} call{inst.active_calls === 1 ? "" : "s"} now</p></Card>
        <Card title="Version"><p className="metric__value mono">{inst.version ?? "—"}</p>
          <p className="subtle">{inst.update_available ? `${inst.update_available} available` : "No update known"}{r.updates?.last_check ? ` · checked ${formatRelative(r.updates.last_check)}` : ""}</p></Card>
      </div>
      <Card title="Last 30 days">
        {inst.samples.length < 2 ? <p className="subtle">Not enough check-ins yet.</p> : (
          <Chart points={inst.samples} rangeSeconds={30 * 86400} ariaLabel="Registered phones, calls and alerts over time"
            series={[{ key: "registered", label: "Registered phones", color: "var(--primary)", area: true }, { key: "active_calls", label: "Calls", color: "var(--text-muted)" }, { key: "alerts", label: "Alerts", color: "var(--danger)" }]} />
        )}
      </Card>
      <Settings inst={inst} reload={data.reload} />
      <div className="grid grid--2">
        <Card title="Open alerts">
          {alerts.length === 0 ? <p className="subtle">None.</p> : (
            <ul className="stack stack--sm" style={{ margin: 0, paddingLeft: 18 }}>
              {alerts.map((a, i) => <li key={i}><strong>{a.subject}</strong> — {a.message} <span className="subtle">({formatRelative(a.since)})</span></li>)}
            </ul>
          )}
        </Card>
        <Card title="Instance">
          <dl className="dl">
            <dt>Name</dt><dd>{inst.name}</dd>
            <dt>Deployment</dt><dd>{r.identity?.deployment_mode ?? "—"}{r.identity?.multi_tenancy ? ", multi-tenant" : ""}</dd>
            <dt>Organizations</dt><dd>{r.telephony?.organizations ?? "—"} · trunks {r.telephony?.trunks ?? "—"}</dd>
            <dt>Firewall</dt><dd>{r.security ? `${r.security.firewall ? "On" : "Off"} · ${r.security.active_bans} ban(s) · ${r.security.failed_sign_ins_1h} failed sign-in(s) in the last hour` : "—"}</dd>
            <dt>Policy</dt><dd>{inst.policy_name ?? "None"}{inst.policy_state ? ` · ${inst.policy_state}` : ""}</dd>
            <dt>Fingerprint</dt><dd className="mono">{inst.fingerprint}</dd>
          </dl>
        </Card>
      </div>
      {available.length || modules.length ? (
        <div className="grid grid--2">
          <Card title="Updates on the instance">
            {available.length === 0 ? <p className="subtle">None waiting.</p> : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>{available.map((u) => <li key={u.version}><span className="mono">{u.version}</span> {u.category} · {u.state}{u.error ? <span className="subtle"> — {u.error}</span> : null}</li>)}</ul>
            )}
          </Card>
          <Card title="Modules">
            {modules.length === 0 ? <p className="subtle">None installed.</p> : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>{modules.map((m) => <li key={m.id}>{m.id} <span className="mono">{m.version}</span> · {m.state}</li>)}</ul>
            )}
          </Card>
        </div>
      ) : null}
      <Card title="Commands" flush>
        <DataTable columns={commandColumns} rows={inst.commands} rowKey={(c) => c.id} caption="Commands" empty={<EmptyState compact icon="history" title="No commands sent" />} />
      </Card>
      <CommandDialog open={commanding} instanceIds={[inst.instance_id]} title={`Command for ${inst.label ?? inst.name}`} onClose={() => setCommanding(false)} onQueued={data.reload} />
      <ConfirmDialog open={revoking} title={`Revoke ${inst.label ?? inst.name}?`} confirmLabel="Revoke" tone="danger" busy={busy} error={error} onConfirm={() => void revoke()} onCancel={() => { setRevoking(false); setError(null); }}>
        <p>The console refuses its check-ins from now on. The instance then removes the firewall entries and notice it took from here; other settings stay as they are. To enroll it again, create a new token.</p>
      </ConfirmDialog>
      <ConfirmDialog open={removing} title={`Remove ${inst.label ?? inst.name}?`} confirmLabel="Remove" tone="danger" busy={busy} error={error} onConfirm={() => void remove()} onCancel={() => { setRemoving(false); setError(null); }}>
        <p>Its history and commands are deleted here.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><InstanceView /></Suspense>;
}
