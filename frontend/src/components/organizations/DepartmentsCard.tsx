// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, DataTable, EmptyState, IconButton, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Department, Page, Site } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";

/** Departments of an organization (#126): extensions belong to one, and My
 * Phone layout templates can be assigned by department. */
export function DepartmentsCard({ organizationId, editable }: { organizationId: string; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const list = useApiData<Department[]>("/departments", { organization_id: organizationId });
  const sites = useApiData<Page<Site>>(editable ? "/sites" : null, { organization_id: organizationId, limit: 200 });
  const [editing, setEditing] = useState<Department | "new" | null>(null);
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [busy, setBusy] = useState(false);

  const open = (d: Department | "new") => {
    setName(d === "new" ? "" : d.name);
    setSite(d === "new" ? "" : d.site_id ?? "");
    errors.clear();
    setEditing(d);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (editing === "new") await api.post("/departments", { organization_id: organizationId, name: name.trim(), site_id: site || null });
      else if (editing) await api.patch(`/departments/${editing.id}`, { name: name.trim(), site_id: site || null });
      toast.success(editing === "new" ? `Department "${name.trim()}" added` : "Department saved");
      setEditing(null);
      list.reload();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (d: Department) => {
    try {
      await api.del(`/departments/${d.id}`);
      toast.success(`Department "${d.name}" deleted`, d.extensions ? `${d.extensions} extension(s) no longer have a department.` : undefined);
      list.reload();
    } catch (err) {
      toast.error("Could not delete the department", errorMessage(err));
    }
  };

  const columns: Column<Department>[] = [
    { key: "name", header: "Department", render: (d) => <span><span className="table__primary" style={{ display: "block" }}>{d.name}</span>{d.site_name ? <span className="table__secondary">{d.site_name}</span> : null}</span> },
    { key: "ext", header: "Extensions", render: (d) => <span>{d.extensions}</span> },
    ...(editable ? [{ key: "actions", header: <span className="sr-only">Actions</span>, render: (d: Department) => (
      <IconButton size="sm" icon="trash" label={`Delete ${d.name}`} onClick={(e) => { e.stopPropagation(); void remove(d); }} />
    ) }] : []),
  ];

  return (
    <Card title="Departments" subtitle="Groups of extensions, such as Front Office or Nurses; My Phone layout templates can be assigned by department." flush
      actions={editable && !editing ? <Button size="sm" icon="plus" onClick={() => open("new")}>Add department</Button> : null}>
      {editing ? (
        <form className="stack stack--sm" style={{ padding: "var(--space-4)" }} onSubmit={submit}>
          <div className="form-grid">
            <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front Office" onChange={(e) => setName(e.target.value)} />
            <SelectField label="Site" value={site} error={errors.fields.site_id} placeholder="Any site" options={(sites.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => setSite(e.target.value)} />
          </div>
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
          <div className="form-actions">
            <Button onClick={() => setEditing(null)} disabled={busy}>Cancel</Button>
            <Button variant="primary" type="submit" loading={busy} disabled={!name.trim()}>{editing === "new" ? "Add department" : "Save changes"}</Button>
          </div>
        </form>
      ) : null}
      <DataTable columns={columns} rows={list.data} rowKey={(d) => d.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Departments"
        onRowClick={editable ? (d) => open(d) : undefined} rowLabel={(d) => `Edit department ${d.name}`}
        empty={<EmptyState compact icon="users" title="No departments yet">{editable ? "Add departments, then choose one on each extension (Location)." : null}</EmptyState>} />
    </Card>
  );
}
