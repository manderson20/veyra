// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { RING_STRATEGY_LABELS } from "@/components/groups/RingGroupFields";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { NextNumber, Page, RingGroup } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function RingGroupsPage() {
  const router = useRouter();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<RingGroup>>("/ring-groups", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<RingGroup>[] = [
    { key: "number", header: "Number", render: (g) => <span className="mono">{g.number}</span> },
    {
      key: "name",
      header: "Ring group",
      render: (g) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{g.name}</span>
          <span className="table__secondary">{g.description ?? RING_STRATEGY_LABELS[g.strategy]}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (g: RingGroup) => <span>{g.organization_name}</span> }] : []),
    { key: "members", header: "Members", render: (g) => g.members.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{g.members.map((m) => <span key={m.extension_id} className="kv-chip mono" title={m.display_name}>{m.number}</span>)}</span> : <span className="subtle">None</span> },
    { key: "failover", header: "If unanswered", render: (g) => <DestinationLabel d={g.failover} /> },
    { key: "status", header: "Status", render: (g) => !g.is_enabled ? <Badge tone="neutral">Disabled</Badge> : g.problems.length ? <Badge tone="warn" icon="alert">{g.problems.length} problem{g.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok">Ready</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Ring groups"
        description="A number that rings several phones at once or one after the other, then sends unanswered calls on. Point an inbound route or an IVR key at a group, or dial its number."
        actions={can("groups.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New ring group</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by number, name or description" label="Search ring groups" />
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
          caption="Ring groups"
          onRowClick={(g) => router.push(`/ring-groups/view/?id=${g.id}`)}
          rowLabel={(g) => `Open ring group ${g.name}`}
          empty={<EmptyState icon="group" title={debounced || org ? "No matching ring groups" : "No ring groups yet"}>{!debounced && !org && can("groups.write") ? "Create a group, add the phones that should ring, and deploy." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(g) => router.push(`/ring-groups/view/?id=${g.id}`)} />
    </div>
  );
}

function CreateDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (g: RingGroup) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const suggestion = useApiData<NextNumber>(open && effectiveOrg ? "/extensions/next-number" : null, { organization_id: effectiveOrg || undefined });

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setName("");
      setNumber("");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<RingGroup>("/ring-groups", { organization_id: effectiveOrg, name: name.trim(), number: number.trim() });
      toast.success(`Ring group "${created.name}" created`, "Add its members, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New ring group" description="Members, strategy and the failover are edited on the group page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="rg-create" loading={busy} disabled={!effectiveOrg || !name.trim() || !number.trim()}>Create group</Button></>}>
      <form id="rg-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front office" onChange={(e) => setName(e.target.value)} />
        <TextField label="Number" required inputMode="numeric" value={number} error={errors.fields.number} placeholder={suggestion.data?.number ?? "e.g. 2300"}
          help={suggestion.data?.number ? `Next free number: ${suggestion.data.number}. Shares the numbering plan with extensions.` : "From the numbering plan; shared with extensions and queues."}
          onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
