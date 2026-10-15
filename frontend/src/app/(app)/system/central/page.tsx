// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { CommandDialog, PolicyDialog, TokenDialog, TokenShownDialog } from "@/components/central/CentralDialogs";
import { CopyButton } from "@/components/common/CopyButton";
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
  Switch,
  TabPanel,
  Tabs,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { policySummary, STATUS_TONE } from "@/lib/central";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CentralConsole, CentralInstanceRow, CentralPolicy, CentralToken, CentralTokenCreated } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function ConsoleCard({ c, reload }: { c: CentralConsole; reload: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("central.write");
  const [busy, setBusy] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const [minutes, setMinutes] = useState(String(c.offline_minutes));
  useOnChange(c.offline_minutes, (m) => setMinutes(String(m)));

  const put = async (enabled: boolean, offline?: number) => {
    setBusy(true);
    try {
      await api.put("/central/console", { enabled, offline_minutes: offline ?? null });
      toast.success(enabled ? "Central console is on" : "Central console is off");
      setConfirmOff(false);
      reload();
    } catch (err) {
      toast.error("Could not change the console", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="This console">
      <div className="stack stack--sm">
        <Switch label="Act as a central console" checked={c.enabled} disabled={!editable || busy}
          description="Other Veyra installations can enroll here with a token, report their health and receive policies and commands. Turning it off keeps the enrolled instances but refuses their check-ins."
          onChange={(e) => (e.target.checked ? void put(true) : setConfirmOff(true))} />
        {c.enabled ? (
          <dl className="dl">
            <dt>Address</dt><dd><span className="row" style={{ gap: 8 }}><code className="mono">{c.address}</code><CopyButton text={c.address} /></span></dd>
            <dt>Fingerprint</dt><dd><span className="row" style={{ gap: 8 }}><code className="mono" style={{ wordBreak: "break-all" }}>{c.fingerprint}</code>{c.fingerprint ? <CopyButton text={c.fingerprint} /> : null}</span></dd>
            <dt>Offline after</dt><dd>
              <form className="row" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); void put(true, Number(minutes)); }}>
                <TextField label="Minutes without a check-in" type="number" min={2} max={1440} value={minutes} disabled={!editable} onChange={(e) => setMinutes(e.target.value)} />
                {editable && Number(minutes) !== c.offline_minutes ? <Button size="sm" type="submit" loading={busy}>Save</Button> : null}
              </form>
            </dd>
          </dl>
        ) : null}
      </div>
      <ConfirmDialog open={confirmOff} title="Turn the central console off?" confirmLabel="Turn off" tone="danger" busy={busy} onConfirm={() => void put(false)} onCancel={() => setConfirmOff(false)}>
        <p>{c.instances} enrolled instance{c.instances === 1 ? "" : "s"} can no longer check in until it is turned on again. Their enrollment is kept.</p>
      </ConfirmDialog>
    </Card>
  );
}

function InstancesTab() {
  const { can } = useSession();
  const router = useRouter();
  const editable = can("central.write");
  const list = useApiData<CentralInstanceRow[]>("/central/instances");
  const [selected, setSelected] = useState<string[]>([]);
  const [commanding, setCommanding] = useState(false);
  const rows = list.data ?? [];
  const live = rows.filter((r) => r.status !== "revoked");
  const pick = (id: string, on: boolean) => setSelected((s) => (on ? [...s, id] : s.filter((x) => x !== id)));

  const columns: Column<CentralInstanceRow>[] = [
    ...(editable ? [{ key: "pick", header: <input type="checkbox" aria-label="Select all instances" checked={live.length > 0 && selected.length === live.length} onChange={(e) => setSelected(e.target.checked ? live.map((r) => r.instance_id) : [])} />,
      render: (r: CentralInstanceRow) => r.status === "revoked" ? null : <input type="checkbox" aria-label={`Select ${r.label ?? r.name}`} checked={selected.includes(r.instance_id)} onClick={(e) => e.stopPropagation()} onChange={(e) => pick(r.instance_id, e.target.checked)} /> }] : []),
    { key: "name", header: "Instance", render: (r) => <span><span className="table__primary" style={{ display: "block" }}>{r.label ?? r.name}</span><span className="table__secondary">{r.label ? r.name : r.last_address ?? ""}</span></span> },
    { key: "status", header: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status}</Badge> },
    { key: "seen", header: "Last check-in", render: (r) => r.last_seen_at ? formatRelative(r.last_seen_at) : <span className="subtle">Never</span> },
    { key: "version", header: "Version", render: (r) => <span><span className="mono">{r.version ?? "—"}</span>{r.update_available ? <span className="table__secondary" style={{ display: "block" }}>{r.update_available} available</span> : null}</span> },
    { key: "phones", header: "Phones", render: (r) => r.registered == null ? "—" : `${r.registered}${r.extensions != null ? ` / ${r.extensions}` : ""}` },
    { key: "calls", header: "Calls", render: (r) => r.active_calls ?? "—" },
    { key: "alerts", header: "Alerts", render: (r) => r.alerts ? <Badge tone="warn" icon="alert">{r.alerts}</Badge> : <span className="subtle">0</span> },
    { key: "policy", header: "Policy", render: (r) => r.policy_name ? <span>{r.policy_name}{r.policy_state && r.policy_state !== "applied" ? <span className="table__secondary" style={{ display: "block" }}>{r.policy_state}</span> : null}</span> : <span className="subtle">None</span> },
  ];

  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted" style={{ margin: 0 }}>Installations enrolled here. They check in every few minutes over HTTPS with signed messages; the console never connects to them.</p>
        {editable ? <Button icon="external" disabled={selected.length === 0} onClick={() => setCommanding(true)}>Command {selected.length || ""} selected</Button> : null}
      </div>
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(r) => r.instance_id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Enrolled instances"
          onRowClick={(r) => router.push(`/system/central/instance/?id=${r.instance_id}`)} rowLabel={(r) => `Open ${r.label ?? r.name}`}
          empty={<EmptyState icon="server" title="No instances enrolled">Create an enrollment token, then enter it on the other installation under System → Central management.</EmptyState>} />
      </Card>
      <CommandDialog open={commanding} instanceIds={selected} title={`Command for ${selected.length} instance${selected.length === 1 ? "" : "s"}`}
        onClose={() => setCommanding(false)} onQueued={() => { setSelected([]); list.reload(); }} />
    </div>
  );
}

function PoliciesTab() {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("central.write");
  const list = useApiData<CentralPolicy[]>("/central/policies");
  const [editing, setEditing] = useState<CentralPolicy | undefined>();
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<CentralPolicy | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/central/policies/${deleting.id}`);
      toast.success(`"${deleting.name}" deleted`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<CentralPolicy>[] = [
    { key: "name", header: "Policy", render: (p) => <span><span className="table__primary" style={{ display: "block" }}>{p.name}{p.is_default ? <> <Badge tone="info">Default</Badge></> : null}</span>{p.description ? <span className="table__secondary">{p.description}</span> : null}</span> },
    { key: "sets", header: "Sets", render: (p) => { const s = policySummary(p.document); return s.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{s.map((x) => <Badge key={x} tone="neutral">{x}</Badge>)}</span> : <span className="subtle">Nothing</span>; } },
    { key: "instances", header: "Instances", render: (p) => p.instances },
    { key: "version", header: "Version", render: (p) => <span>{p.version}<span className="table__secondary" style={{ display: "block" }}>{formatRelative(p.updated_at)}</span></span> },
    ...(editable ? [{ key: "actions", header: "", render: (p: CentralPolicy) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" variant="ghost" icon="trash" aria-label={`Delete ${p.name}`} onClick={(e) => { e.stopPropagation(); setDeleting(p); }} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted" style={{ margin: 0 }}>What enrolled instances should use. Each instance chooses which sections it accepts.</p>
        {editable ? <Button variant="primary" icon="plus" onClick={() => setCreating(true)}>New policy</Button> : null}
      </div>
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Policies"
          onRowClick={editable ? (p) => setEditing(p) : undefined} rowLabel={(p) => `Edit ${p.name}`}
          empty={<EmptyState icon="shield" title="No policies">{editable ? "Without a policy, instances only report their health." : null}</EmptyState>} />
      </Card>
      <PolicyDialog open={creating} onClose={() => setCreating(false)} onSaved={list.reload} />
      <PolicyDialog open={!!editing} policy={editing} onClose={() => setEditing(undefined)} onSaved={list.reload} />
      <ConfirmDialog open={!!deleting} title={`Delete "${deleting?.name ?? ""}"?`} confirmLabel="Delete" tone="danger" busy={busy} error={error} onConfirm={remove} onCancel={() => { setDeleting(undefined); setError(null); }}>
        <p>{deleting?.instances ? `${deleting.instances} instance${deleting.instances === 1 ? "" : "s"} lose${deleting.instances === 1 ? "s" : ""} this policy; what it already applied stays in place.` : "No instance uses it."}</p>
      </ConfirmDialog>
    </div>
  );
}

function TokensTab({ enabled }: { enabled: boolean }) {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("central.write");
  const list = useApiData<CentralToken[]>("/central/tokens");
  const policies = useApiData<CentralPolicy[]>("/central/policies");
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<CentralTokenCreated | null>(null);

  const remove = async (t: CentralToken) => {
    try {
      await api.del(`/central/tokens/${t.id}`);
      toast.success("Token withdrawn");
      list.reload();
    } catch (err) {
      toast.error("Could not withdraw the token", errorMessage(err));
    }
  };

  const policyName = (id: string | null) => (id ? policies.data?.find((p) => p.id === id)?.name ?? "—" : "Default");
  const columns: Column<CentralToken>[] = [
    { key: "label", header: "Label", render: (t) => <span><span className="table__primary" style={{ display: "block" }}>{t.label ?? "Unlabelled"}</span><span className="table__secondary">by {t.created_by}</span></span> },
    { key: "policy", header: "Policy", render: (t) => policyName(t.policy_id) },
    { key: "created", header: "Created", render: (t) => formatDateTime(t.created_at) },
    { key: "state", header: "State", render: (t) => t.used_at ? <Badge tone="ok">Used {formatRelative(t.used_at)}</Badge> : new Date(t.expires_at) < new Date() ? <Badge tone="neutral">Expired</Badge> : <Badge tone="info">Expires {formatRelative(t.expires_at)}</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (t: CentralToken) => t.used_at ? null : <span className="row" style={{ justifyContent: "flex-end" }}><Button size="sm" variant="ghost" icon="trash" aria-label="Withdraw token" onClick={() => void remove(t)} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted" style={{ margin: 0 }}>One-time tokens for enrolling an installation. Each works once and expires after a day.</p>
        {editable ? <Button variant="primary" icon="plus" disabled={!enabled} onClick={() => setCreating(true)}>New token</Button> : null}
      </div>
      {!enabled ? <Callout tone="neutral">Turn the console on to create enrollment tokens.</Callout> : null}
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(t) => t.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Enrollment tokens"
          empty={<EmptyState icon="key" title="No enrollment tokens" />} />
      </Card>
      <TokenDialog open={creating} policies={policies.data ?? []} onClose={() => setCreating(false)} onCreated={(t) => { setShown(t); list.reload(); }} />
      <TokenShownDialog token={shown} onClose={() => setShown(null)} />
    </div>
  );
}

export default function CentralConsolePage() {
  const consoleData = useApiData<CentralConsole>("/central/console");
  const [tab, setTab] = useState("instances");
  const c = consoleData.data;
  return (
    <div className="stack">
      <PageHeader title="Central console" description="Watch and steer several Veyra installations from this one: health, versions, policies and update commands. See docs/CENTRAL_MANAGEMENT.md." />
      {consoleData.error ? <Card><ErrorState error={consoleData.error} onRetry={consoleData.reload} /></Card> : !c ? <Card><LoadingState /></Card> : (
        <>
          <ConsoleCard c={c} reload={consoleData.reload} />
          <Tabs idBase="central" active={tab} onChange={setTab} tabs={[{ id: "instances", label: `Instances (${c.instances})` }, { id: "policies", label: "Policies" }, { id: "tokens", label: "Enrollment tokens" }]} />
          <TabPanel idBase="central" id="instances" active={tab}><InstancesTab /></TabPanel>
          <TabPanel idBase="central" id="policies" active={tab}><PoliciesTab /></TabPanel>
          <TabPanel idBase="central" id="tokens" active={tab}><TokensTab enabled={c.enabled} /></TabPanel>
        </>
      )}
    </div>
  );
}
