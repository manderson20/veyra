// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, IconButton, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatNumberBlock } from "@/lib/format";
import type { OrganizationNumber, Page, Trunk } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";

const SOURCE: Record<OrganizationNumber["source"], string> = {
  manual: "Assigned",
  migration: "From existing routes",
  auto: "From a route",
};

/** The numbers assigned to an organization (docs/MULTI_TENANCY_MSP.md §4):
 * only these can be routed to it. Platform administrators assign them. */
export function NumbersCard({ organizationId, editable }: { organizationId: string; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const list = useApiData<OrganizationNumber[]>(`/organizations/${encodeURIComponent(organizationId)}/numbers`);
  const trunks = useApiData<Page<Trunk>>(editable ? "/trunks" : null, { limit: 200 });
  const [adding, setAdding] = useState(false);
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [trunk, setTrunk] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);

  const open = () => {
    setFirst("");
    setLast("");
    setTrunk("");
    setLabel("");
    errors.clear();
    setAdding(true);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const row = await api.post<OrganizationNumber>(`/organizations/${encodeURIComponent(organizationId)}/numbers`, {
        first: first.trim(),
        last: last.trim() || null,
        trunk_id: trunk || null,
        label: label.trim() || null,
      });
      toast.success(row.count === 1 ? "Number assigned" : `${row.count} numbers assigned`);
      setAdding(false);
      list.reload();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (n: OrganizationNumber) => {
    try {
      await api.del(`/organizations/${encodeURIComponent(organizationId)}/numbers/${n.id}`);
      toast.success(`${formatNumberBlock(n.first, n.last)} withdrawn`);
      list.reload();
    } catch (err) {
      toast.error("Could not withdraw the number", errorMessage(err));
    }
  };
  const usable = (trunks.data?.items ?? []).filter((t) => !t.organization_id || t.organization_id === organizationId);

  const columns: Column<OrganizationNumber>[] = [
    {
      key: "number",
      header: "Number",
      render: (n) => (
        <span>
          <span className="table__primary mono" style={{ display: "block" }}>{formatNumberBlock(n.first, n.last)}</span>
          {n.label || n.count > 1 ? <span className="table__secondary">{[n.label, n.count > 1 ? `${n.count} numbers` : null].filter(Boolean).join(" · ")}</span> : null}
        </span>
      ),
    },
    { key: "trunk", header: "Arrives on", render: (n) => <span>{n.trunk_name ?? "Any trunk"}</span> },
    { key: "routed", header: "Routed", render: (n) => <span>{n.routed}</span> },
    { key: "source", header: "Source", render: (n) => <Badge tone="neutral">{SOURCE[n.source]}</Badge> },
    ...(editable
      ? [{
          key: "actions",
          header: <span className="sr-only">Actions</span>,
          render: (n: OrganizationNumber) => (
            <IconButton size="sm" icon="trash" disabled={n.routed > 0} onClick={() => void remove(n)}
              label={n.routed > 0 ? `${formatNumberBlock(n.first, n.last)} is routed; remove its inbound routes first` : `Withdraw ${formatNumberBlock(n.first, n.last)}`} />
          ),
        }]
      : []),
  ];

  return (
    <Card title="Numbers" subtitle="The phone numbers that belong to this organization. Inbound routes and caller IDs can use only these when several organizations share the server." flush
      actions={editable && !adding ? <Button size="sm" icon="plus" onClick={open}>Assign numbers</Button> : null}>
      {adding ? (
        <form className="stack stack--sm" style={{ padding: "var(--space-4)" }} onSubmit={submit}>
          <div className="form-grid">
            <TextField label="Number" required autoFocus inputMode="tel" value={first} error={errors.fields.first} placeholder="573 555 0100" onChange={(e) => setFirst(e.target.value)} />
            <TextField label="Last number of a block" inputMode="tel" value={last} error={errors.fields.last} placeholder="573 555 0199"
              help="For a block such as 0100 to 0199; leave empty for one number. At most 10,000." onChange={(e) => setLast(e.target.value)} />
            <SelectField label="Arrives on" value={trunk} error={errors.fields.trunk_id} placeholder="Any trunk"
              options={usable.map((t) => ({ value: t.id, label: t.name }))} onChange={(e) => setTrunk(e.target.value)} />
            <TextField label="Label" value={label} error={errors.fields.label} maxLength={100} placeholder="e.g. Main line" onChange={(e) => setLabel(e.target.value)} />
          </div>
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
          <div className="form-actions">
            <Button onClick={() => setAdding(false)} disabled={busy}>Cancel</Button>
            <Button variant="primary" type="submit" loading={busy} disabled={!first.trim()}>Assign</Button>
          </div>
        </form>
      ) : null}
      <DataTable columns={columns} rows={list.data} rowKey={(n) => n.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Numbers"
        empty={<EmptyState compact icon="phone" title="No numbers yet">{editable ? "Assign the numbers this organization's calls arrive on." : "A platform administrator assigns this organization's numbers."}</EmptyState>} />
    </Card>
  );
}
