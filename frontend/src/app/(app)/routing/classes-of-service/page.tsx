// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { ClassOfServiceDialog } from "@/components/routing/ClassOfServiceDialog";
import { Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { ClassOfService, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function ClassesOfServicePage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<ClassOfService | undefined>();
  const [deleting, setDeleting] = useState<ClassOfService | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<ClassOfService>>("/classes-of-service", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const editable = can("routing.write");
  const manyOrgs = organizations.length > 1;
  const saved = () => { list.reload(); setChanged((n) => n + 1); };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/classes-of-service/${deleting.id}`);
      toast.success(`Class "${deleting.name}" deleted`, "Deploy changes to apply it.");
      setDeleting(undefined);
      saved();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<ClassOfService>[] = [
    { key: "name", header: "Class", render: (c) => <span><span className="table__primary" style={{ display: "block" }}>{c.name}</span><span className="table__secondary">{c.description ?? <span className="mono">{c.slug}</span>}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (c: ClassOfService) => <span>{c.organization_name}</span> }] : []),
    { key: "routes", header: "Outbound routes", render: (c) => c.allowed_outbound_routes.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{c.allowed_outbound_routes.map((r) => <span key={r.id} className="kv-chip">{r.name}</span>)}</span> : <span className="subtle">Emergency only</span> },
    { key: "codes", header: "Feature codes", render: (c) => c.allowed_feature_code_keys === null ? <span className="subtle">All</span> : <span>{c.allowed_feature_code_keys.length} allowed</span> },
    { key: "limits", header: "Also", render: (c) => <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
      {!c.allow_external_forwards ? <Badge tone="warn">No outside forwards</Badge> : null}
      {!c.allow_external_follow_me ? <Badge tone="warn">No outside follow-me</Badge> : null}
      {!c.allow_intercom ? <Badge tone="warn">No intercom</Badge> : null}
      {!c.allow_fax ? <Badge tone="warn">No fax</Badge> : null}
      {c.allow_monitor ? <Badge tone="info">Supervisor codes</Badge> : null}
      {c.monitor_protected ? <Badge tone="neutral">Never monitored</Badge> : null}
      {c.max_outbound_calls ? <Badge tone="neutral">{c.max_outbound_calls} outside call{c.max_outbound_calls === 1 ? "" : "s"}</Badge> : null}
    </span> },
    { key: "ext", header: "Extensions", render: (c) => c.extensions },
    ...(editable ? [{ key: "actions", header: "", render: (c: ClassOfService) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(c); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(c); }} aria-label={`Delete ${c.name}`} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Classes of service"
        description="What a phone may do: which outbound routes and feature codes it can use, whether its forwards and follow-me may leave the building, intercom, and how many outside calls the class may have up at once. An extension without a class may do everything; emergency routes always work."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New class</Button> : null} />
      <PendingChanges key={changed} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search classes" label="Search classes of service" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(c) => c.id} loading={list.loading && !list.data} error={list.error} onRetry={list.reload} caption="Classes of service"
          onRowClick={editable ? (c) => setEditing(c) : undefined} rowLabel={(c) => `Edit ${c.name}`}
          empty={<EmptyState icon="shield" title="No classes of service">{editable ? "Every phone may do everything until a class restricts it." : "No class has been defined."}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : undefined} />
      </Card>
      <ClassOfServiceDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={saved} />
      <ClassOfServiceDialog open={!!editing} onClose={() => setEditing(undefined)} cls={editing} onSaved={saved} />
      <ConfirmDialog open={!!deleting} title={`Delete class "${deleting?.name ?? ""}"`} confirmLabel="Delete" tone="danger" busy={deleteBusy} onCancel={() => { setDeleting(undefined); setDeleteError(null); }} onConfirm={remove}>
        <p>Extensions in the class must be moved first. The phones of a class that no longer exists may do everything.</p>
        {deleteError ? <p className="field__error" role="alert">{deleteError}</p> : null}
      </ConfirmDialog>
    </div>
  );
}
