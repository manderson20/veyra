// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { ExtensionTemplateDialog } from "@/components/extensions/ExtensionTemplateDialog";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { ExtensionTemplate, ExtensionTemplateApply, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const LABELS: Record<string, string> = {
  class_of_service_id: "Class of service",
  intercom: "Intercom",
  max_registrations: "Phones that may register",
  department_id: "Department",
  ring_seconds: "Ring time",
  call_waiting_off: "Call waiting off",
  anonymous_reject: "Refuse hidden numbers",
};

function shown(v: unknown): string {
  if (v === null || v === undefined || v === "") return "none";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/** Extension templates (issue #172): settings a group of extensions follows. */
export default function ExtensionTemplatesPage() {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("extensions.write");
  const list = useApiData<Page<ExtensionTemplate>>("/extension-templates", { limit: 200 });
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ExtensionTemplate | undefined>();
  const [deleting, setDeleting] = useState<ExtensionTemplate | undefined>();
  const [applying, setApplying] = useState<ExtensionTemplate | undefined>();
  const [preview, setPreview] = useState<ExtensionTemplateApply | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  const openApply = async (t: ExtensionTemplate) => {
    setApplying(t);
    setPreview(null);
    setError(null);
    try {
      setPreview(await api.post<ExtensionTemplateApply>(`/extension-templates/${t.id}/apply`, { dry_run: true }));
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const apply = async () => {
    if (!applying) return;
    setBusy(true);
    try {
      const r = await api.post<ExtensionTemplateApply>(`/extension-templates/${applying.id}/apply`, { dry_run: false });
      toast.success(`${r.extensions.length} extension${r.extensions.length === 1 ? "" : "s"} updated`, r.needs_deployment ? "Deploy changes to put them on the phone system." : "Takes effect at once.");
      setApplying(undefined);
      list.reload();
      setChanged((n) => n + 1);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.del(`/extension-templates/${deleting.id}`);
      toast.success(`Template "${deleting.name}" deleted`, "Its extensions keep their settings.");
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<ExtensionTemplate>[] = [
    { key: "name", header: "Template", render: (t) => <span><span className="table__primary" style={{ display: "block" }}>{t.name}</span>{t.description ? <span className="table__secondary">{t.description}</span> : null}</span> },
    { key: "sets", header: "Sets", render: (t) => <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
      {Object.keys(t.settings).map((k) => <Badge key={k} tone={t.locked.includes(k as keyof ExtensionTemplate["settings"]) ? "warn" : "neutral"}>{LABELS[k] ?? k}{t.locked.includes(k as keyof ExtensionTemplate["settings"]) ? " (locked)" : ""}</Badge>)}
    </span> },
    { key: "ext", header: "Extensions", render: (t) => t.extensions },
    ...(editable ? [{ key: "actions", header: "", render: (t: ExtensionTemplate) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
      <Button size="sm" onClick={(e) => { e.stopPropagation(); void openApply(t); }} disabled={!t.extensions}>Apply…</Button>
      <Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(t); }}>Edit</Button>
      <Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(t); }} aria-label={`Delete ${t.name}`} />
    </span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Extension templates"
        description="One set of settings many extensions follow: class of service, intercom, ring time, call waiting and more. Pick a template when creating an extension (or in a bulk import's template column); apply it again after changing it. Locked settings cannot be changed on the extensions."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New template</Button> : null} />
      <PendingChanges key={changed} />
      <Card flush>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(t) => t.id} loading={list.loading && !list.data} error={list.error} onRetry={list.reload} caption="Extension templates"
          onRowClick={editable ? (t) => setEditing(t) : undefined} rowLabel={(t) => `Edit ${t.name}`}
          empty={<EmptyState icon="template" title="No extension templates">{editable ? "Create one to set many extensions alike." : "No template has been defined."}</EmptyState>} />
      </Card>
      <ExtensionTemplateDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <ExtensionTemplateDialog open={!!editing} onClose={() => setEditing(undefined)} template={editing} onSaved={() => list.reload()} />
      <Dialog open={!!applying} onClose={() => setApplying(undefined)} busy={busy} size="lg" title={`Apply "${applying?.name ?? ""}"`}
        description="These extensions follow the template and differ from it; applying gives them the template's settings."
        footer={<><Button onClick={() => setApplying(undefined)} disabled={busy}>Cancel</Button><Button variant="primary" loading={busy} disabled={!preview?.extensions.length} onClick={apply}>Apply to {preview?.extensions.length ?? 0} extension{preview?.extensions.length === 1 ? "" : "s"}</Button></>}>
        {error ? <Callout tone="danger">{error}</Callout> : !preview ? <p className="subtle">Checking…</p> : preview.extensions.length ? (
          <ul className="list-plain">
            {preview.extensions.map((x) => (
              <li key={x.extension_id} className="list-row" style={{ paddingLeft: 0 }}>
                <span className="mono">{x.number}</span>
                <span className="subtle">{Object.entries(x.changes).map(([k, c]) => `${LABELS[k] ?? k}: ${shown(c.from)} → ${shown(c.to)}`).join("; ")}</span>
              </li>
            ))}
          </ul>
        ) : <p>Every extension already matches the template.</p>}
        {preview?.needs_deployment ? <Callout tone="neutral">Some of these changes reach the phone system at the next deployment.</Callout> : null}
      </Dialog>
      <ConfirmDialog open={!!deleting} title={`Delete template "${deleting?.name ?? ""}"`} confirmLabel="Delete" tone="danger" busy={busy} onCancel={() => setDeleting(undefined)} onConfirm={remove}>
        <p>Its extensions keep their current settings and stop following it; nothing is locked any more.</p>
      </ConfirmDialog>
    </div>
  );
}
