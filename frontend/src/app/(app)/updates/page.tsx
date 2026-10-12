// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  SelectField,
  Switch,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { AvailableUpdate, Page, UpdateCheck, UpdateHistoryItem, UpdateMode, UpdatePolicies, UpdatePolicy } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const MODES: { value: UpdateMode; label: string; help: string }[] = [
  { value: "manual", label: "Manual only", help: "Veyra never checks automatically. An administrator checks and installs updates." },
  { value: "notify", label: "Notify", help: "Check on a schedule and notify administrators. Nothing is downloaded or installed." },
  { value: "download_approve", label: "Download, install on approval", help: "Download automatically; an administrator approves installation." },
  { value: "auto_install_window", label: "Install automatically in a maintenance window", help: "Install approved categories during a maintenance window." },
];

const CHECK_OUTCOME: Record<string, { tone: "ok" | "neutral" | "danger" | "warn"; label: string }> = {
  ok: { tone: "ok", label: "Succeeded" },
  not_configured: { tone: "neutral", label: "No update source" },
  failed: { tone: "danger", label: "Failed" },
  rejected: { tone: "warn", label: "Rejected" },
};

export default function UpdatesPage() {
  const { can } = useSession();
  const toast = useToast();
  const policies = useApiData<UpdatePolicies>("/updates/policies");
  const latest = useApiData<UpdateCheck | null>("/updates/checks/latest");
  const available = useApiData<AvailableUpdate[]>("/updates/available");
  const [histOffset, setHistOffset] = useState(0);
  const history = useApiData<Page<UpdateHistoryItem>>("/updates/history", { limit: 10, offset: histOffset });
  const [checking, setChecking] = useState(false);
  const manage = can("updates.manage");

  const checkNow = async () => {
    setChecking(true);
    try {
      const r = await api.post<UpdateCheck>("/updates/check");
      latest.setData(r);
      available.reload();
      if (r.outcome === "ok") toast.success("Update check complete", r.message ?? undefined);
      else if (r.outcome === "not_configured") toast.info("No update source configured", r.message ?? undefined);
      else toast.error("Update check failed", r.message ?? undefined);
    } catch (err) {
      toast.error("Update check failed", errorMessage(err));
    } finally {
      setChecking(false);
    }
  };

  const availableColumns: Column<AvailableUpdate>[] = [
    { key: "target", header: "Component", render: (u) => <span className="table__primary">{u.target}</span> },
    { key: "version", header: "Version", render: (u) => <span className="mono">{u.current_version ?? "?"} → {u.version}</span> },
    { key: "category", header: "Type", render: (u) => <Badge tone={u.category === "security" ? "danger" : u.category === "bugfix" ? "warn" : "info"}>{u.category}</Badge> },
    { key: "channel", header: "Channel", render: (u) => u.channel },
    { key: "found", header: "Found", render: (u) => <span className="subtle">{formatRelative(u.created_at)}</span> },
  ];
  const historyColumns: Column<UpdateHistoryItem>[] = [
    { key: "target", header: "Component", render: (h) => h.target },
    { key: "version", header: "Version", render: (h) => <span className="mono">{h.from_version ?? "?"} → {h.to_version}</span> },
    { key: "outcome", header: "Result", render: (h) => <Badge tone={h.outcome === "success" ? "ok" : h.outcome === "running" ? "info" : "danger"}>{h.outcome}</Badge> },
    { key: "by", header: "Started by", render: (h) => h.initiated_by },
    { key: "when", header: "Started", render: (h) => <span className="subtle nowrap">{formatDateTime(h.started_at)}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Updates"
        description="Control how Veyra checks for and applies updates. Nothing is installed without your configuration."
        actions={manage ? <Button icon="refresh" onClick={checkNow} loading={checking}>Check now</Button> : null}
      />
      <Callout tone="info" title="Update installation is not available yet">
        This release checks for updates and verifies signed update information. Downloading and installing updates from this
        page arrives in Milestone 12. Veyra never installs updates unattended by default.
      </Callout>

      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Last check">
          {latest.error ? <ErrorState compact error={latest.error} onRetry={latest.reload} /> : latest.loading && latest.data === undefined ? <LoadingState /> : !latest.data ? (
            <EmptyState compact icon="clock" title="Never checked">{manage ? "Use “Check now” to check for updates." : "No update check has run yet."}</EmptyState>
          ) : (
            <dl className="dl">
              <dt>Result</dt><dd><Badge tone={CHECK_OUTCOME[latest.data.outcome]?.tone ?? "neutral"}>{CHECK_OUTCOME[latest.data.outcome]?.label ?? latest.data.outcome}</Badge></dd>
              <dt>When</dt><dd>{formatDateTime(latest.data.checked_at)}</dd>
              <dt>Details</dt><dd>{latest.data.message ?? "—"}</dd>
              {latest.data.source ? <><dt>Source</dt><dd className="mono">{latest.data.source}</dd></> : null}
            </dl>
          )}
        </Card>
        <Card title="Update source">
          {policies.data ? (
            policies.data.source_configured ? (
              <p>An authenticated update source is configured. Update information must be signed by an official Veyra key.</p>
            ) : (
              <Callout tone="neutral">
                No update source is configured, so checks report “No update source”. The installer sets
                <code> VEYRA_UPDATE_METADATA_URL</code> in <code>/etc/veyra/veyra.env</code> once official update channels are published.
              </Callout>
            )
          ) : <LoadingState />}
        </Card>
      </div>

      <Card title="Available updates" flush>
        <DataTable columns={availableColumns} rows={available.data} rowKey={(u) => u.id} loading={available.loading} error={available.error} onRetry={available.reload}
          caption="Available updates" empty={<EmptyState compact icon="checkCircle" title="No updates found">No updates were found as of the last check.</EmptyState>} />
      </Card>

      <section aria-labelledby="policies-title" className="stack stack--sm">
        <div>
          <h2 className="card__title" id="policies-title">Update policies</h2>
          <p className="muted">Each component has its own policy. Operating system and telephony engine updates follow separate maintenance practices.</p>
        </div>
        {policies.error ? <Card><ErrorState error={policies.error} onRetry={policies.reload} /></Card> : !policies.data ? <Card><LoadingState /></Card> : (
          policies.data.items.map((p) => (
            <PolicyCard key={p.component} policy={p} availableModes={policies.data?.available_modes ?? []} editable={manage}
              onSaved={(np) => policies.setData(policies.data ? { ...policies.data, items: policies.data.items.map((x) => (x.component === np.component ? { ...np, label: x.label } : x)) } : undefined)} />
          ))
        )}
      </section>

      <Card title="Update history" flush>
        <DataTable columns={historyColumns} rows={history.data?.items} rowKey={(h) => h.id} loading={history.loading} error={history.error} onRetry={history.reload}
          caption="Update history" empty={<EmptyState compact icon="history" title="No updates have been applied" />}
          pagination={history.data && history.data.total > 0 ? <Pagination total={history.data.total} limit={10} offset={histOffset} onChange={setHistOffset} /> : null} />
      </Card>
    </div>
  );
}

function PolicyCard({ policy, availableModes, editable, onSaved }: {
  policy: UpdatePolicy; availableModes: UpdateMode[]; editable: boolean; onSaved: (p: UpdatePolicy) => void;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<UpdateMode>(policy.mode);
  const [channel, setChannel] = useState(policy.channel);
  const [checkEnabled, setCheckEnabled] = useState(policy.check_enabled);
  const [interval, setInterval_] = useState(String(policy.check_interval_hours));
  const [notify, setNotify] = useState(policy.notify_admins);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useOnChange(policy, (p) => {
    setMode(p.mode);
    setChannel(p.channel);
    setCheckEnabled(p.check_enabled);
    setInterval_(String(p.check_interval_hours));
    setNotify(p.notify_admins);
  });

  const external = policy.component === "operating_system" || policy.component === "telephony_engine";
  const dirty = mode !== policy.mode || channel !== policy.channel || checkEnabled !== policy.check_enabled
    || interval !== String(policy.check_interval_hours) || notify !== policy.notify_admins;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.put<UpdatePolicy>(`/updates/policies/${policy.component}`, {
        mode, channel, check_enabled: checkEnabled, check_interval_hours: Number(interval), notify_admins: notify,
        auto_download: false, auto_install_categories: [], require_approval: true, maintenance_window: null,
      });
      onSaved({ ...saved, label: policy.label });
      toast.success("Policy saved", policy.label);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const modeHelp = MODES.find((m) => m.value === mode)?.help;
  return (
    <Card title={policy.label} subtitle={`Last changed ${formatRelative(policy.updated_at)}`}
      footer={editable ? <Button variant="primary" size="sm" onClick={save} loading={busy} disabled={!dirty}>Save policy</Button> : undefined}>
      <div className="stack stack--sm">
        {external ? (
          <Callout tone="neutral">Managed with the server&apos;s package manager in this release. Veyra does not check these updates yet.</Callout>
        ) : null}
        <div className="form-grid">
          <SelectField label="Update behaviour" value={mode} disabled={!editable} help={modeHelp}
            options={MODES.map((m) => ({ value: m.value, label: availableModes.includes(m.value) ? m.label : `${m.label} (not available yet)`, disabled: !availableModes.includes(m.value) }))}
            onChange={(e) => setMode(e.target.value as UpdateMode)} />
          <SelectField label="Release channel" value={channel} disabled={!editable}
            help={channel === "stable" ? "Recommended for production." : "Pre-release software. Not recommended for production systems."}
            options={[{ value: "stable", label: "Stable" }, { value: "beta", label: "Beta" }, { value: "development", label: "Development" }]}
            onChange={(e) => setChannel(e.target.value as UpdatePolicy["channel"])} />
        </div>
        <div className="form-grid">
          <Switch label="Check for updates automatically" checked={checkEnabled} disabled={!editable || external || mode === "manual"} onChange={(e) => setCheckEnabled(e.target.checked)} />
          <TextField label="Check every (hours)" type="number" min={1} max={720} value={interval} disabled={!editable || !checkEnabled || mode === "manual"} onChange={(e) => setInterval_(e.target.value)} />
        </div>
        <Switch label="Notify administrators" checked={notify} disabled={!editable} onChange={(e) => setNotify(e.target.checked)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Card>
  );
}
