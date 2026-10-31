// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, Checkbox, DataTable, Dialog, EmptyState, PageHeader, SelectField, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { DeviceProfile, Page, ProvisioningVariable, Site, VariableScope } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const SCOPE_LABEL: Record<VariableScope, string> = { installation: "Installation", organization: "Organization", site: "Site", profile: "Template" };
const SCOPE_ORDER: VariableScope[] = ["installation", "organization", "site", "profile"];

/** Provisioning variables (docs/PROVISIONING_BREADTH.md §2): values defined
 * once that templates (`vars.name`) and key lists (`$name`) use. */
export default function VariablesPage() {
  const { can, session } = useSession();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const [editing, setEditing] = useState<ProvisioningVariable | "new" | null>(null);
  const list = useApiData<ProvisioningVariable[]>("/provisioning/variables", { organization_id: org || undefined });
  const manage = can("provisioning.write");
  const defined = (list.data ?? []).filter((v) => v.source === "defined")
    .sort((a, b) => a.name.localeCompare(b.name) || SCOPE_ORDER.indexOf(a.scope!) - SCOPE_ORDER.indexOf(b.scope!));
  const core = (list.data ?? []).filter((v) => v.source === "core");

  const columns: Column<ProvisioningVariable>[] = [
    { key: "name", header: "Variable", render: (v) => <span><span className="table__primary mono" style={{ display: "block" }}>{v.name}</span>{v.description ? <span className="table__secondary">{v.description}</span> : null}</span> },
    { key: "value", header: "Value", render: (v) => <span className="mono">{v.value}</span> },
    { key: "scope", header: "Defined for", render: (v) => <span><Badge tone={v.scope === "installation" ? "info" : "neutral"}>{SCOPE_LABEL[v.scope!]}</Badge> {v.scope !== "installation" ? v.scope_name : null}</span> },
    { key: "use", header: "Use", render: (v) => <span className="subtle mono">{"{{ vars." + v.name + " }}"} · ${v.name}</span> },
  ];
  const coreColumns: Column<ProvisioningVariable>[] = [
    { key: "name", header: "Variable", render: (v) => <span className="mono">{v.name}</span> },
    { key: "description", header: "Comes from", render: (v) => <span>{v.description}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Provisioning variables"
        description="Values phones share, defined once: an all-call zone per building, the time server, an admin password. Base files read them as {{ vars.name }}, line keys and paging zones as $name; each phone takes the value of its nearest scope (template, then site, then organization, then installation). Changing a value asks the phones it reaches to re-read their configuration."
        actions={manage ? <Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New variable</Button> : null} />
      <Card title="Defined variables" flush>
        {organizations.length > 1 ? (
          <div className="table-toolbar">
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
          </div>
        ) : null}
        <DataTable columns={columns} rows={defined} rowKey={(v) => v.id!} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Defined variables" onRowClick={manage ? (v) => setEditing(v) : undefined} rowLabel={(v) => `Edit ${v.name}`}
          empty={<EmptyState compact icon="settings" title="No variables yet">{manage ? "Define a value once, for example all_call per site, and use $all_call on a page key of a template." : "Nothing is defined yet."}</EmptyState>} />
      </Card>
      <Card title="Built-in values" subtitle="Every template has these from the phone, its extension and the server; they need no definition." flush>
        <DataTable columns={coreColumns} rows={core} rowKey={(v) => v.name} loading={list.loading} caption="Built-in values" />
      </Card>
      {editing ? (
        <VariableDialog variable={editing === "new" ? null : editing} isPlatform={!!session?.is_platform_admin}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} />
      ) : null}
    </div>
  );
}

function VariableDialog({ variable, isPlatform, onClose, onSaved }: { variable: ProvisioningVariable | null; isPlatform: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(true);
  const [scope, setScope] = useState<VariableScope>(variable?.scope ?? "organization");
  const [org, setOrg] = useState(variable?.organization_id ?? session?.user.home_organization_id ?? "");
  const [target, setTarget] = useState(variable?.scope_id ?? "");
  const [name, setName] = useState(variable?.name ?? "");
  const [value, setValue] = useState(variable?.sensitive ? "" : (variable?.value ?? ""));
  const [description, setDescription] = useState(variable?.description ?? "");
  const [sensitive, setSensitive] = useState(variable?.sensitive ?? false);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const sites = useApiData<Page<Site>>(!variable && scope === "site" && effectiveOrg ? "/sites" : null, { organization_id: effectiveOrg, limit: 200 });
  const profiles = useApiData<Page<DeviceProfile>>(!variable && scope === "profile" && effectiveOrg ? "/device-profiles" : null, { organization_id: effectiveOrg, limit: 200 });
  const scopes = SCOPE_ORDER.filter((s) => s !== "installation" || isPlatform);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    errors.clear();
    try {
      let saved: ProvisioningVariable;
      if (variable) {
        saved = await api.patch<ProvisioningVariable>(`/provisioning/variables/${variable.id}`, {
          ...(variable.sensitive && !value ? {} : { value }), description: description.trim() || null, sensitive,
        });
      } else {
        saved = await api.post<ProvisioningVariable>("/provisioning/variables", {
          scope, scope_id: scope === "installation" ? null : scope === "organization" ? effectiveOrg : target,
          name: name.trim(), value, sensitive, description: description.trim() || null,
        });
      }
      const n = saved.affected_devices ?? 0;
      toast.success(`Variable ${saved.name} saved`, n ? `${n} phone${n === 1 ? "" : "s"} asked to re-read the configuration.` : undefined);
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    if (!variable?.id) return;
    setBusy("delete");
    errors.clear();
    try {
      await api.del(`/provisioning/variables/${variable.id}`);
      toast.success(`Variable ${variable.name} removed`);
      onSaved();
    } catch (err) {
      errors.set(err);
      setConfirmDelete(false);
    } finally {
      setBusy(null);
    }
  };
  const needsTarget = !variable && (scope === "site" || scope === "profile");
  const targetOptions = scope === "site"
    ? (sites.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))
    : (profiles.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }));

  return (
    <Dialog open onClose={onClose} busy={!!busy} title={variable ? `Variable ${variable.name}` : "New variable"}
      description={variable ? `Defined for ${SCOPE_LABEL[variable.scope!]}${variable.scope_name && variable.scope !== "installation" ? ` ${variable.scope_name}` : ""}.` : "Define it at the widest scope that shares the value; narrower scopes override it."}
      footer={(
        <>
          {variable ? (confirmDelete
            ? <Button variant="danger" onClick={remove} loading={busy === "delete"}>Yes, remove</Button>
            : <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={!!busy}>Remove</Button>) : null}
          <Button onClick={onClose} disabled={!!busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="var-form" loading={busy === "save"}
            disabled={!variable && (!name.trim() || (scope !== "installation" && !effectiveOrg) || (needsTarget && !target))}>{variable ? "Save" : "Create variable"}</Button>
        </>
      )}>
      <form id="var-form" className="stack stack--sm" onSubmit={submit}>
        {!variable ? (
          <>
            <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="all_call" spellCheck={false}
              help="Lower-case letters, digits and underscores; used as {{ vars.name }} in templates and $name in keys." onChange={(e) => setName(e.target.value.toLowerCase())} />
            <SelectField label="Defined for" value={scope} options={scopes.map((s) => ({ value: s, label: SCOPE_LABEL[s] }))} onChange={(e) => { setScope(e.target.value as VariableScope); setTarget(""); }} />
            {scope !== "installation" && organizations.length > 1 ? (
              <SelectField label="Organization" required value={effectiveOrg} placeholder="Choose an organization" options={organizations.map((o) => ({ value: o.id, label: o.name }))}
                onChange={(e) => { setOrg(e.target.value); setTarget(""); }} />
            ) : null}
            {needsTarget ? (
              <SelectField label={scope === "site" ? "Site" : "Template"} required value={target} error={errors.fields.scope_id}
                placeholder={targetOptions.length ? "Choose…" : scope === "site" ? "No sites (Organizations → Sites)" : "No templates"}
                options={targetOptions} onChange={(e) => setTarget(e.target.value)} />
            ) : null}
          </>
        ) : null}
        <TextArea label="Value" rows={2} value={value} error={errors.fields.value} spellCheck={false}
          placeholder={variable?.sensitive ? "Saved (enter a new value to replace it)" : "building-a"} onChange={(e) => setValue(e.target.value)} />
        <TextField label="Description" value={description} error={errors.fields.description} placeholder="What the value is for" onChange={(e) => setDescription(e.target.value)} />
        <Checkbox label="Sensitive (shown masked to those who cannot change it)" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {confirmDelete ? <Callout tone="warn">Remove this variable? Phones that use it from this scope fall back to the same variable in a wider scope. A variable that line keys still use cannot be removed until those keys change.</Callout> : null}
      </form>
    </Dialog>
  );
}
