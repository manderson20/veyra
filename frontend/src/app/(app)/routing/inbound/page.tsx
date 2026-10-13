// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_INBOUND_ROUTE, InboundRouteFields, inboundRouteBody, inboundRouteValid, type InboundRouteDraft } from "@/components/routing/InboundRouteFields";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { InboundRoute, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

function Destination({ r }: { r: InboundRoute }) {
  if (r.destination_missing || !r.destination_number) return <Badge tone="danger" icon="alert">No destination</Badge>;
  return (
    <span>
      <span className="table__primary mono" style={{ display: "block" }}>{r.destination_number}</span>
      <span className="table__secondary">{r.destination_name}</span>
    </span>
  );
}

export default function InboundRoutesPage() {
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

  const list = useApiData<Page<InboundRoute>>("/routing/inbound", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<InboundRoute>[] = [
    {
      key: "did",
      header: "DID",
      render: (r) => (
        <span>
          <span className="table__primary mono" style={{ display: "block" }}>{r.did === "any" ? "Any number" : r.did}</span>
          {r.aliases.length ? <span className="table__secondary mono">{r.aliases.join(", ")}</span> : null}
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (r: InboundRoute) => <span>{r.organization_name}</span> }] : []),
    { key: "trunk", header: "Trunk", render: (r) => r.trunk_name ? <span>{r.trunk_name}</span> : <span className="subtle">Any trunk</span> },
    { key: "dest", header: "Destination", render: (r) => <Destination r={r} /> },
    {
      key: "tc",
      header: "Time condition",
      render: (r) => r.time_condition_name ? <span>{r.time_condition_name}{r.after_hours_number ? <span className="table__secondary" style={{ display: "block" }}>Closed: {r.after_hours_number}</span> : null}</span> : <span className="subtle">Always</span>,
    },
    { key: "enabled", header: "Enabled", render: (r) => <Badge tone={r.is_enabled ? "ok" : "neutral"}>{r.is_enabled ? "Enabled" : "Disabled"}</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Inbound routes"
        description="Which extension answers each number (DID) that carriers deliver, optionally only during a time condition's open hours."
        actions={can("routing.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New inbound route</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by number or description" label="Search inbound routes" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(r) => r.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Inbound routes"
          onRowClick={(r) => router.push(`/routing/inbound/view/?id=${r.id}`)}
          rowLabel={(r) => `Open inbound route ${r.did}`}
          empty={<EmptyState icon="arrowIn" title={debounced || org ? "No matching inbound routes" : "No inbound routes yet"}>{!debounced && !org && can("routing.write") ? "Create a route for each number the carrier delivers, then deploy the configuration." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateInboundRouteDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(r) => router.push(`/routing/inbound/view/?id=${r.id}`)} />
    </div>
  );
}

function CreateInboundRouteDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (r: InboundRoute) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [draft, setDraft] = useState<InboundRouteDraft>(EMPTY_INBOUND_ROUTE);
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setDraft(EMPTY_INBOUND_ROUTE);
      errors.clear();
    }
  });

  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<InboundRoute>("/routing/inbound", { organization_id: effectiveOrg, ...inboundRouteBody(draft) });
      toast.success(`Inbound route for ${created.did === "any" ? "any number" : created.did} created`, "Deploy the configuration so calls follow it.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      size="lg"
      title="New inbound route"
      description="Calls to the number go to the destination extension; with a time condition, closed-hours calls go to the after-hours extension."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="inbound-create" loading={busy} disabled={!effectiveOrg || !inboundRouteValid(draft)}>Create route</Button></>}
    >
      <form id="inbound-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))}
            onChange={(e) => { setOrg(e.target.value); setDraft((d) => ({ ...d, destination_extension_id: "", time_condition_id: "", after_hours_extension_id: "" })); }} />
        ) : null}
        <InboundRouteFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={effectiveOrg} autoFocus />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
