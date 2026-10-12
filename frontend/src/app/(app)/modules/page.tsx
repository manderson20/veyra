"use client";

import { useState } from "react";
import { MODULE_STATE, TRUST } from "@/components/common/labels";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  toStatus,
  useToast,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { ModuleInfo, ModuleList } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

type Action = "install" | "enable" | "disable" | "update" | "uninstall";

const ACTION_META: Record<Action, { label: string; verb: string; tone: "primary" | "danger" }> = {
  install: { label: "Install", verb: "installed", tone: "primary" },
  enable: { label: "Enable", verb: "enabled", tone: "primary" },
  disable: { label: "Disable", verb: "disabled", tone: "danger" },
  update: { label: "Apply update", verb: "updated", tone: "primary" },
  uninstall: { label: "Uninstall", verb: "uninstalled", tone: "danger" },
};

function actionsFor(m: ModuleInfo): Action[] {
  const out: Action[] = [];
  if (m.state === "available" || m.state === "removed") out.push("install");
  if (m.state === "installed" || m.state === "disabled" || m.state === "failed") out.push("enable");
  if (m.state === "enabled") out.push("disable");
  if (m.update_available) out.push("update");
  if (m.state === "installed" || m.state === "disabled" || m.state === "failed" || m.state === "removed") out.push("uninstall");
  return out;
}

export default function ModulesPage() {
  const { can, refresh } = useSession();
  const toast = useToast();
  const list = useApiData<ModuleList>("/modules");
  const [pending, setPending] = useState<{ module: ModuleInfo; action: Action } | null>(null);
  const [purge, setPurge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const manage = can("modules.manage");

  const run = async () => {
    if (!pending) return;
    const { module: m, action } = pending;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/modules/${encodeURIComponent(m.module_id)}/${action}`,
        action === "uninstall" ? { purge_data: purge, confirm_module_id: purge ? m.module_id : null } : {});
      toast.success(`Module ${ACTION_META[action].verb}`, m.name ?? m.module_id);
      setPending(null);
      list.reload();
      await refresh(); // navigation contributed by modules may have changed
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const open = (m: ModuleInfo, action: Action) => {
    setPurge(false);
    setError(null);
    setPending({ module: m, action });
  };

  return (
    <div className="stack">
      <PageHeader
        title="Module Manager"
        description="Install, enable and update the functional modules that extend Veyra."
        actions={<Button icon="refresh" onClick={list.reload} loading={list.loading && !!list.data}>Refresh</Button>}
      />
      <Callout tone="info">
        Modules are found in the configured module directories. Only modules signed by an official key run inside Veyra;
        community and third-party modules will run as isolated services in a later release. Browsing a module catalog is planned.
      </Callout>
      {list.error ? (
        <Card><ErrorState title="Could not load modules" error={list.error} onRetry={list.reload} /></Card>
      ) : !list.data ? (
        <Card><LoadingState /></Card>
      ) : list.data.items.length === 0 ? (
        <Card><EmptyState icon="modules" title="No modules found">No modules are installed or present in the module directories.</EmptyState></Card>
      ) : (
        <div className="stack stack--sm">
          {list.data.items.map((m) => (
            <ModuleCard key={m.module_id} m={m} manage={manage} onAction={(a) => open(m, a)} />
          ))}
          <p className="subtle">Module API version {list.data.module_api_version}</p>
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={pending ? `${ACTION_META[pending.action].label} ${pending.module.name ?? pending.module.module_id}?` : ""}
        confirmLabel={pending ? (pending.action === "uninstall" && purge ? "Uninstall and delete data" : ACTION_META[pending.action].label) : ""}
        tone={pending ? ACTION_META[pending.action].tone : "primary"}
        typeToConfirm={pending?.action === "uninstall" && purge ? pending.module.module_id : undefined}
        busy={busy}
        error={error}
        onConfirm={run}
        onCancel={() => setPending(null)}
      >
        {pending?.action === "install" ? <p>The module&apos;s database tables are created and its permissions are registered. It stays disabled until you enable it.</p> : null}
        {pending?.action === "enable" ? <p>The module&apos;s features and navigation become available to users with its permissions.</p> : null}
        {pending?.action === "disable" ? <p>The module stops serving requests. Its data and settings are kept.</p> : null}
        {pending?.action === "update" ? <p>Database migrations for version {pending.module.available_version} run now. Restart the Veyra API service afterwards to load the new code.</p> : null}
        {pending?.action === "uninstall" ? (
          <>
            <p>By default the module&apos;s data is kept so it can be reinstalled later.</p>
            <Checkbox label="Also delete all of this module's data" description="This permanently drops the module's tables and settings. It cannot be undone."
              checked={purge} onChange={(e) => setPurge(e.target.checked)} />
          </>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

function ModuleCard({ m, manage, onAction }: { m: ModuleInfo; manage: boolean; onAction: (a: Action) => void }) {
  const state = MODULE_STATE[m.state] ?? { label: m.state, tone: "neutral" as const };
  const trust = TRUST[m.trust_level] ?? { label: m.trust_level, tone: "neutral" as const, icon: "puzzle" };
  const actions = manage ? actionsFor(m) : [];
  return (
    <Card>
      <div className="row row--between" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="row">
            <h2 className="card__title">{m.name ?? m.module_id}</h2>
            <Badge tone={state.tone}>{state.label}</Badge>
            <Badge tone={trust.tone} icon={trust.icon}>{trust.label}</Badge>
            {m.signature_verified ? <Badge tone="ok" icon="check">Signature verified</Badge> : <Badge tone="warn" icon="alert">Not verified</Badge>}
            {m.health ? <StatusBadge status={toStatus(m.health.status)} /> : null}
          </div>
          <p className="muted" style={{ marginTop: 6 }}>{m.description}</p>
          <p className="subtle" style={{ marginTop: 6 }}>
            <span className="mono">{m.module_id}</span>
            {m.installed_version ? ` · installed ${m.installed_version}` : ""}
            {m.available_version && m.available_version !== m.installed_version ? ` · ${m.installed_version ? "available" : "version"} ${m.available_version}` : ""}
            {m.author ? ` · ${m.author}` : ""}
            {m.license ? ` · ${m.license}` : ""}
          </p>
        </div>
        {actions.length ? (
          <div className="row">
            {actions.map((a) => (
              <Button key={a} size="sm" variant={a === "enable" || a === "install" || a === "update" ? "primary" : "secondary"} onClick={() => onAction(a)}>
                {ACTION_META[a].label}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
      <div className="stack stack--sm" style={{ marginTop: 12 }}>
        {m.restart_required ? <Callout tone="warn">Restart the Veyra API service to load the new version of this module.</Callout> : null}
        {m.last_error ? <Callout tone="danger" title="Last error">{m.last_error}</Callout> : null}
        {m.problems.length ? (
          <Callout tone={m.state === "enabled" ? "warn" : "danger"} title="Compatibility or trust problems">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{m.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </Callout>
        ) : null}
        {!m.signature_verified && m.verification_error && !m.problems.length ? (
          <Callout tone="warn">Loaded without a verified signature (development mode): {m.verification_error}</Callout>
        ) : null}
        {m.health?.message ? <p className="subtle">Health: {m.health.message}</p> : null}
        {(m.permissions.length > 0 || m.dependencies.length > 0) ? (
          <details>
            <summary className="subtle" style={{ cursor: "pointer" }}>Permissions and dependencies</summary>
            <div className="grid grid--2" style={{ marginTop: 10 }}>
              <div>
                <p className="field__label">Permissions</p>
                <ul className="list-plain">{m.permissions.map((p) => <li key={p.key} style={{ padding: "6px 0", borderTop: 0 }}><span className="kv-chip">{p.key}</span> <span className="subtle">{p.description}</span></li>)}</ul>
              </div>
              <div>
                <p className="field__label">Dependencies</p>
                {m.dependencies.length === 0 ? <p className="subtle">None</p> : (
                  <ul className="list-plain">{m.dependencies.map((d) => <li key={d.id} style={{ padding: "6px 0", borderTop: 0 }}><span className="mono">{d.id}</span> {d.version}{d.optional ? " (optional)" : ""}</li>)}</ul>
                )}
                {m.compatibility ? <p className="subtle" style={{ marginTop: 8 }}>Requires module API {m.compatibility.core_api}{m.compatibility.engines.length ? ` · engines: ${m.compatibility.engines.join(", ")}` : ""}</p> : null}
              </div>
            </div>
          </details>
        ) : null}
      </div>
    </Card>
  );
}
