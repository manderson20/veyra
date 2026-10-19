// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Canvas } from "@/components/portal/Canvas";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, SelectField, Switch, Tabs, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { PortalScope, PortalTemplate, Role } from "@/lib/types";
import { addWidget, newTabId, removeWidget, type Layout, type Placed } from "@/portal/layout";
import { DEFAULT_LAYOUT, WIDGETS, widgetByKey } from "@/portal/widgets";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

// Building and department scopes exist in the API and in the resolution;
// their pickers arrive with the buildings and departments pages (M21/M22).
const SCOPES: { value: PortalScope; label: string }[] = [
  { value: "organization", label: "Whole organization" },
  { value: "role", label: "A role" },
  { value: "system", label: "System-wide (every organization)" },
  { value: "building", label: "A building" },
  { value: "department", label: "A department" },
];
const PICKABLE: PortalScope[] = ["organization", "role", "system"];

/** Default portal layouts by scope (docs/USER_PORTAL.md §10). */
export default function PortalLayoutsPage() {
  const { can, session } = useSession();
  const list = useApiData<PortalTemplate[]>("/portal-templates");
  const [editing, setEditing] = useState<PortalTemplate | "new" | null>(null);
  const editable = can("portal.templates");
  const columns: Column<PortalTemplate>[] = [
    { key: "name", header: "Layout", render: (t) => <span><span className="table__primary">{t.name}</span>{t.description ? <span className="table__secondary" style={{ display: "block" }}>{t.description}</span> : null}</span> },
    { key: "scope", header: "Applies to", render: (t) => <span>{SCOPES.find((s) => s.value === t.scope)?.label ?? t.scope}{t.scope_label ? `: ${t.scope_label}` : ""}{t.organization_name ? <span className="table__secondary" style={{ display: "block" }}>{t.organization_name}</span> : null}</span> },
    { key: "widgets", header: "Widgets", render: (t) => <span>{t.layout.tabs.reduce((n, tab) => n + tab.widgets.length, 0)} on {t.layout.tabs.length} tab{t.layout.tabs.length === 1 ? "" : "s"}{t.locked_widgets.length ? <span className="table__secondary" style={{ display: "block" }}>{t.locked_widgets.length} locked</span> : null}</span> },
    { key: "priority", header: "Priority", render: (t) => <span>{t.priority}</span> },
    { key: "enabled", header: "", render: (t) => <Badge tone={t.is_enabled ? "ok" : "neutral"}>{t.is_enabled ? "Enabled" : "Disabled"}</Badge> },
  ];
  return (
    <div className="stack">
      <PageHeader title="Portal layouts" description="Default arrangements of My Phone. A user gets the nearest one: a role's, then their department's, their building's, the organization's, the system's. Users may rearrange; locked widgets always stay."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New layout</Button> : null} />
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(t) => t.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Portal layouts"
          onRowClick={editable ? (t) => setEditing(t) : undefined} rowLabel={(t) => `Edit ${t.name}`}
          empty={<EmptyState icon="dashboard" title="No layouts yet">Users see the built-in arrangement until you make one. A layout named for the whole organization is the usual start.</EmptyState>} />
      </Card>
      <TemplateDialog template={editing} isPlatform={!!session?.is_platform_admin} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} />
    </div>
  );
}

function TemplateDialog({ template, isPlatform, onClose, onSaved }: { template: PortalTemplate | "new" | null; isPlatform: boolean; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(template !== null);
  const t = template && template !== "new" ? template : null;
  const [name, setName] = useState(t?.name ?? "");
  const [description, setDescription] = useState(t?.description ?? "");
  const [org, setOrg] = useState(t?.organization_id ?? organizations[0]?.id ?? "");
  const [scope, setScope] = useState<PortalScope>(t?.scope ?? "organization");
  const [ref, setRef] = useState(t?.scope_ref ?? "");
  const [priority, setPriority] = useState(String(t?.priority ?? 0));
  const [enabled, setEnabled] = useState(t?.is_enabled ?? true);
  const [locked, setLocked] = useState<string[]>(t?.locked_widgets ?? []);
  const [layout, setLayout] = useState<Layout>((t?.layout as Layout | undefined) ?? (DEFAULT_LAYOUT as Layout));
  const [tab, setTab] = useState(layout.tabs[0]?.id ?? "home");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const roles = useApiData<Role[]>(scope === "role" ? "/roles" : null);
  const current = layout.tabs.find((x) => x.id === tab) ?? layout.tabs[0]!;
  const update = (widgets: Placed[]) => setLayout({ ...layout, tabs: layout.tabs.map((x) => (x.id === current.id ? { ...x, widgets } : x)) });

  const body = () => ({
    ...(template === "new" ? { organization_id: scope === "system" ? null : org || null } : {}),
    name: name.trim(), description: description.trim() || null, scope, scope_ref: scope === "organization" || scope === "system" ? null : ref || null,
    layout, locked_widgets: locked, priority: Number(priority) || 0, is_enabled: enabled,
  });
  const valid = name.trim().length > 0 && (scope === "system" ? isPlatform : !!org) && (scope === "organization" || scope === "system" || !!ref);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (t) await api.patch(`/portal-templates/${t.id}`, body());
      else await api.post("/portal-templates", body());
      toast.success(t ? "Layout saved" : "Layout created", "Users under this scope see it unless they arranged their own page.");
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const push = async () => {
    if (!t) return;
    setBusy(true);
    try {
      const r = await api.post<{ reset: number }>(`/portal-templates/${t.id}/push`);
      toast.success(`Pushed to ${r.reset} user${r.reset === 1 ? "" : "s"}`, "Their own arrangements were reset to this layout.");
    } catch (err) {
      toast.error("Could not push", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!t) return;
    setBusy(true);
    try {
      await api.del(`/portal-templates/${t.id}`);
      toast.success("Layout deleted");
      onSaved();
    } catch (err) {
      toast.error("Could not delete", errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Dialog open={template !== null} onClose={onClose} busy={busy} size="lg" title={t ? `Edit ${t.name}` : "New portal layout"}
      footer={<>
        {t ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)} disabled={busy}>Delete</Button> : null}
        {t ? <Button onClick={push} disabled={busy}>Push to users</Button> : null}
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="primary" type="submit" form="portal-template-form" loading={busy} disabled={!valid}>Save</Button>
      </>}>
      <form id="portal-template-form" className="stack" onSubmit={submit}>
        <div className="grid grid--2">
          <TextField label="Name" required value={name} error={errors.fields.name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Priority" type="number" min={0} max={100} value={priority} help="Among layouts of the same scope, the higher wins." onChange={(e) => setPriority(e.target.value)} />
        </div>
        <TextArea label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="grid grid--2">
          <SelectField label="Applies to" value={scope} disabled={!!t} options={SCOPES.filter((s) => (s.value !== "system" || isPlatform) && (PICKABLE.includes(s.value) || s.value === t?.scope))} onChange={(e) => { setScope(e.target.value as PortalScope); setRef(""); }} />
          {scope !== "system" ? <SelectField label="Organization" value={org} disabled={!!t} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} /> : null}
        </div>
        {scope === "building" || scope === "department" ? <TextField label={scope === "building" ? "Building id" : "Department id"} value={ref} onChange={(e) => setRef(e.target.value)} error={errors.fields.scope_ref} help="A picker comes with the buildings and departments pages; until then the id from the API." /> : null}
        {scope === "role" ? <SelectField label="Role" value={ref} placeholder="Choose a role" options={(roles.data ?? []).map((r) => ({ value: r.key, label: r.name }))} onChange={(e) => setRef(e.target.value)} error={errors.fields.scope_ref} /> : null}
        <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <div className="stack stack--sm">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
            <Tabs idBase="tpl" active={current.id} onChange={setTab} tabs={layout.tabs.map((x) => ({ id: x.id, label: x.name }))} />
            <span className="row">
              <TextField label={<span className="sr-only">Tab name</span>} value={current.name} maxLength={40} style={{ width: 150 }} onChange={(e) => setLayout({ ...layout, tabs: layout.tabs.map((x) => (x.id === current.id ? { ...x, name: e.target.value } : x)) })} />
              <Button size="sm" icon="plus" onClick={() => { const id = newTabId(layout.tabs); setLayout({ ...layout, tabs: [...layout.tabs, { id, name: `Tab ${layout.tabs.length + 1}`, widgets: [] }] }); setTab(id); }} disabled={layout.tabs.length >= 8}>Tab</Button>
              <Button size="sm" variant="ghost" icon="trash" aria-label="Remove this tab" disabled={layout.tabs.length <= 1} onClick={() => { const rest = layout.tabs.filter((x) => x.id !== current.id); setLayout({ ...layout, tabs: rest }); setTab(rest[0]!.id); }} />
            </span>
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {WIDGETS.map((w) => <Button key={w.key} size="sm" icon="plus" onClick={() => update(addWidget(current.widgets, w.key, w.needs ? "first" : "default", w.defaultSize))}>{w.title}</Button>)}
          </div>
          <Canvas widgets={current.widgets} arranging locked={new Set(locked)} onChange={update} onRemove={(id) => update(removeWidget(current.widgets, id))}
            render={(p) => {
              const m = widgetByKey(p.key);
              const isLocked = locked.includes(p.key);
              return (
                <Card title={m?.title ?? p.key} subtitle={m?.description}>
                  <div className="stack stack--sm">
                    {p.key === "announce" ? <TextArea label="Text" rows={2} value={String(p.settings?.text ?? "")} onChange={(e) => update(current.widgets.map((q) => (q === p ? { ...q, settings: { ...q.settings, text: e.target.value } } : q)))} /> : null}
                    <Switch label="Users cannot remove it" checked={isLocked} onChange={(e) => setLocked(e.target.checked ? [...new Set([...locked, p.key])] : locked.filter((k) => k !== p.key))} />
                  </div>
                </Card>
              );
            }} />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
      <Dialog open={deleting} onClose={() => setDeleting(false)} busy={busy} title="Delete this layout?" footer={<><Button onClick={() => setDeleting(false)} disabled={busy}>Cancel</Button><Button variant="danger" loading={busy} onClick={remove}>Delete</Button></>}>
        <p>Users under this scope fall back to the next layout or the built-in one; their own arrangements stay.</p>
      </Dialog>
    </Dialog>
  );
}
