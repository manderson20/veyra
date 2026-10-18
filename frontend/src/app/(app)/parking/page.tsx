// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { Page, ParkingLot } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function ParkingPage() {
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

  const list = useApiData<Page<ParkingLot>>("/parking-lots", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<ParkingLot>[] = [
    { key: "park", header: "Park at", render: (l) => <span className="mono">{l.park_exten}</span> },
    {
      key: "name",
      header: "Lot",
      render: (l) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{l.name}</span>
          <span className="table__secondary">{l.description ?? <span className="mono">{l.context}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (l: ParkingLot) => <span>{l.organization_name}</span> }] : []),
    { key: "slots", header: "Slots", render: (l) => <span className="mono">{l.slot_first}–{l.slot_last}</span> },
    { key: "timeout", header: "Timeout", render: (l) => <span>{l.timeout_seconds} s, then the parker for {l.return_ring_seconds} s, then <DestinationLabel d={l.timeout} /></span> },
    { key: "status", header: "Status", render: (l) => !l.is_enabled ? <Badge tone="neutral">Disabled</Badge> : l.problems.length ? <Badge tone="warn" icon="alert">{l.problems.length} problem{l.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Call parking"
        description="Park a call by transferring it to the lot's park extension; the parker hears the slot number, and anyone picks the call up by dialling the slot. Line keys with the slot numbers light while a call waits. A parked call that times out rings the parker back, then goes to the lot's destination."
        actions={can("groups.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New parking lot</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name, park extension or description" label="Search parking lots" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(l) => l.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Parking lots"
          onRowClick={(l) => router.push(`/parking/view/?id=${l.id}`)}
          rowLabel={(l) => `Open parking lot ${l.name}`}
          empty={<EmptyState icon="pause" title={debounced || org ? "No matching lots" : "No parking lots yet"}>{!debounced && !org && can("groups.write") ? "Create a lot: a park extension such as 70 and slots 71 to 79, in the organization's number space." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateLotDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(l) => router.push(`/parking/view/?id=${l.id}`)} />
    </div>
  );
}

function CreateLotDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (l: ParkingLot) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [park, setPark] = useState("70");
  const [first, setFirst] = useState("71");
  const [last, setLast] = useState("79");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setName("");
      setPark("70");
      setFirst("71");
      setLast("79");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<ParkingLot>("/parking-lots", { organization_id: effectiveOrg, name: name.trim(), park_exten: park.trim(), slot_first: Number(first), slot_last: Number(last) });
      toast.success(`Parking lot "${created.name}" created`, "Set the timeout destination, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const ok = /^[0-9]{1,32}$/.test(park.trim()) && /^[0-9]+$/.test(first) && /^[0-9]+$/.test(last) && Number(last) >= Number(first);
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New parking lot" description="The timeout and the other options are edited on the lot page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="lot-create" loading={busy} disabled={!effectiveOrg || !name.trim() || !ok}>Create lot</Button></>}>
      <form id="lot-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front office lot" onChange={(e) => setName(e.target.value)} />
        <div className="form-grid">
          <TextField label="Park extension" required inputMode="numeric" value={park} error={errors.fields.park_exten} onChange={(e) => setPark(e.target.value)} />
          <TextField label="First slot" required type="number" min={1} value={first} error={errors.fields.slot_first} onChange={(e) => setFirst(e.target.value)} />
          <TextField label="Last slot" required type="number" min={1} value={last} error={errors.fields.slot_last} onChange={(e) => setLast(e.target.value)} />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
