// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { PickupGroupDialog } from "@/components/groups/PickupGroupDialog";
import { Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Page, PickupGroup } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function PickupGroupsPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<PickupGroup | undefined>();
  const [deleting, setDeleting] = useState<PickupGroup | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<PickupGroup>>("/pickup-groups", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const editable = can("groups.write");
  const manyOrgs = organizations.length > 1;
  const saved = () => { list.reload(); setChanged((n) => n + 1); };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/pickup-groups/${deleting.id}`);
      toast.success(`Pickup group "${deleting.name}" deleted`, "Deploy the configuration to update the phones.");
      setDeleting(undefined);
      saved();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<PickupGroup>[] = [
    {
      key: "name",
      header: "Pickup group",
      render: (g) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{g.name}</span>
          <span className="table__secondary">{g.description ?? <span className="mono">{g.slug}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (g: PickupGroup) => <span>{g.organization_name}</span> }] : []),
    { key: "members", header: "Members", render: (g) => g.members.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{g.members.map((m) => <span key={m.extension_id} className="kv-chip mono" title={m.display_name}>{m.number}</span>)}</span> : <span className="subtle">None</span> },
    { key: "status", header: "Status", render: (g) => g.problems.length ? <Badge tone="warn" icon="alert">{g.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (g: PickupGroup) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(g); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(g); }} aria-label={`Delete ${g.name}`} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Pickup groups"
        description="Phones in a pickup group can answer each other's ringing calls by dialling *8. Picking up one particular phone with ** and its extension number works across the organization, or only within the same pickup group if the organization's setting limits it."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New pickup group</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or description" label="Search pickup groups" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(g) => g.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Pickup groups"
          onRowClick={editable ? (g) => setEditing(g) : undefined}
          rowLabel={(g) => `Edit pickup group ${g.name}`}
          empty={<EmptyState icon="phone" title={debounced || org ? "No matching pickup groups" : "No pickup groups yet"}>{!debounced && !org && editable ? "Create a group with the phones that should cover for each other, then deploy." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <PickupGroupDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={saved} />
      <PickupGroupDialog open={!!editing} group={editing} onClose={() => setEditing(undefined)} onSaved={saved} />
      <ConfirmDialog open={!!deleting} title={`Delete the pickup group "${deleting?.name ?? ""}"?`} confirmLabel="Delete group" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Its members can no longer pick up each other&apos;s calls with *8 after the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}
