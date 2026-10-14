// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PAGING_KIND_LABELS, PagingZoneDialog } from "@/components/paging/PagingZoneDialog";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Page, PagingZone } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function PagingZonesPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<PagingZone | undefined>();
  const [deleting, setDeleting] = useState<PagingZone | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<PagingZone>>("/paging-zones", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const editable = can("paging.write");
  const manyOrgs = organizations.length > 1;
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/paging-zones/${deleting.id}`);
      toast.success(`Paging zone "${deleting.name}" deleted`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<PagingZone>[] = [
    { key: "name", header: "Zone", render: (z) => <span><span className="table__primary" style={{ display: "block" }}>{z.name}</span><span className="table__secondary">{z.site_name ?? z.description ?? <span className="mono">{z.slug}</span>}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (z: PagingZone) => <span>{z.organization_name}</span> }] : []),
    { key: "mc", header: "Speakers (multicast)", render: (z) => <span className="mono">{z.multicast_address}:{z.multicast_port}</span> },
    { key: "poly", header: "Poly group", render: (z) => <span><span className="mono">{z.poly_group}</span> <span className="subtle">on {z.poly_address}:{z.poly_port}</span></span> },
    { key: "kind", header: "Kind", render: (z) => <span>{PAGING_KIND_LABELS[z.kind]} · {z.codec}</span> },
    { key: "profiles", header: "Profiles", render: (z) => z.profiles.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{z.profiles.map((p) => <span key={p.id} className="kv-chip">{p.name}</span>)}</span> : <span className="subtle">None</span> },
    { key: "status", header: "Status", render: (z) => !z.is_enabled ? <Badge tone="neutral">Disabled</Badge> : z.problems.length ? <Badge tone="warn" icon="alert">{z.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (z: PagingZone) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(z); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(z); }} aria-label={`Delete ${z.name}`} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Paging zones"
        description="Each zone pairs the multicast group your speakers already listen to with the Poly group number the phones subscribe to. Device profiles subscribe phones to zones."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New paging zone</Button> : null} />
      <Callout tone="neutral">
        Poly phones only hear Poly group pages, not plain multicast. This milestone writes the groups into the phones; sending pages from Veyra into both formats at once (so phones and speakers stay in sync) comes with the paging milestone.
      </Callout>
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name, description or address" label="Search paging zones" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(z) => z.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Paging zones"
          onRowClick={editable ? (z) => setEditing(z) : undefined} rowLabel={(z) => `Edit paging zone ${z.name}`}
          empty={<EmptyState icon="megaphone" title={debounced || org ? "No matching zones" : "No paging zones yet"}>{!debounced && !org && editable ? "Create a zone per paging area (a building, a wing, a floor, outdoors) with the speakers' multicast address and a Poly group number; a building can have as many zones as it needs." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <PagingZoneDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <PagingZoneDialog open={!!editing} zone={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <ConfirmDialog open={!!deleting} title={`Delete the paging zone "${deleting?.name ?? ""}"?`} confirmLabel="Delete zone" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Zones used by a device profile cannot be deleted; remove them from the profiles first.</p>
      </ConfirmDialog>
    </div>
  );
}
