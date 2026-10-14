// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { SiteDialog } from "@/components/sites/SiteDialog";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Page, Site } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function SitesPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Site | undefined>();
  const [deleting, setDeleting] = useState<Site | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Site>>("/sites", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const editable = can("organizations.write");
  const manyOrgs = organizations.length > 1;
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/sites/${deleting.id}`);
      toast.success(`Site "${deleting.name}" deleted`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<Site>[] = [
    { key: "name", header: "Site", render: (s) => <span><span className="table__primary" style={{ display: "block" }}>{s.name}</span><span className="table__secondary">{[s.street, s.city, s.region].filter(Boolean).join(", ") || <span className="mono">{s.slug}</span>}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (s: Site) => <span>{s.organization_name}</span> }] : []),
    { key: "tz", header: "Time zone", render: (s) => s.timezone ?? <span className="subtle">Organization default</span> },
    { key: "ecid", header: "Emergency caller ID", render: (s) => s.emergency_caller_id_number ? <span className="mono">{s.emergency_caller_id_number}</span> : <span className="subtle">—</span> },
    { key: "counts", header: "Extensions / phones", render: (s) => <span>{s.extensions} / {s.devices}</span> },
    ...(editable ? [{ key: "actions", header: "", render: (s: Site) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(s); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(s); }} aria-label={`Delete ${s.name}`} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Sites" description="Buildings and campuses. Device profiles and paging zones can belong to a site (as many zones per site as the building needs); a site's time zone and emergency caller ID are defaults for its extensions."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New site</Button> : null} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or city" label="Search sites" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(s) => s.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Sites"
          onRowClick={editable ? (s) => setEditing(s) : undefined} rowLabel={(s) => `Edit site ${s.name}`}
          empty={<EmptyState icon="building" title={debounced || org ? "No matching sites" : "No sites yet"}>{!debounced && !org && editable ? "Add a site per building to group its paging zones, phones and emergency caller ID." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <SiteDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <SiteDialog open={!!editing} site={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <ConfirmDialog open={!!deleting} title={`Delete the site "${deleting?.name ?? ""}"?`} confirmLabel="Delete site" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Extensions, phones, profiles and zones of this site keep working without a site.</p>
      </ConfirmDialog>
    </div>
  );
}
