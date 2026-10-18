// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, Switch, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { CallFlow, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function CallFlowsPage() {
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<CallFlow>>("/call-flows", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const editable = can("routing.write");

  const toggle = async (f: CallFlow, override: boolean) => {
    setSwitching(f.id);
    try {
      const updated = await api.post<CallFlow>(`/call-flows/${f.id}/state`, { override });
      if (list.data) list.setData({ ...list.data, items: list.data.items.map((x) => (x.id === updated.id ? updated : x)) });
      toast.success(override ? `${f.name} switched` : `${f.name} back to normal`, "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not switch the call flow", errorMessage(err));
    } finally {
      setSwitching(null);
    }
  };

  const columns: Column<CallFlow>[] = [
    {
      key: "state",
      header: "Switched",
      render: (f) => (
        <span onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} role="presentation">
          <Switch label={<span className="sr-only">{f.name} switched</span>} checked={f.override} disabled={!editable || switching === f.id} onChange={(e) => toggle(f, e.target.checked)} />
        </span>
      ),
    },
    {
      key: "name",
      header: "Call flow",
      render: (f) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{f.name}</span>
          <span className="table__secondary">{f.description ?? <span className="mono">{f.context}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (f: CallFlow) => <span>{f.organization_name}</span> }] : []),
    { key: "code", header: "Phone code", render: (f) => f.code ? <span className="mono">{f.code}{f.has_pin ? " (PIN)" : ""}</span> : <Badge tone="warn" icon="alert">Code disabled</Badge> },
    { key: "now", header: "Calls go to", render: (f) => <span><DestinationLabel d={f.override ? f.override_destination : f.normal} />{f.override ? <span className="subtle"> (switched)</span> : null}</span> },
    { key: "status", header: "Status", render: (f) => !f.is_enabled ? <Badge tone="neutral">Disabled</Badge> : f.problems.length ? <Badge tone="warn" icon="alert">{f.problems.length} problem{f.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Call flows"
        description="Day/night switches: a route, menu key or group sends calls into a call flow, which follows its normal destination or, while switched, its override destination. Switch from here, from a phone with the toggle code (a BLF key lights while switched) or from the API; the change takes effect at once."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New call flow</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or description" label="Search call flows" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(f) => f.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Call flows"
          onRowClick={(f) => router.push(`/routing/call-flows/view/?id=${f.id}`)}
          rowLabel={(f) => `Open call flow ${f.name}`}
          empty={<EmptyState icon="power" title={debounced || org ? "No matching call flows" : "No call flows yet"}>{!debounced && !org && editable ? "Create one with a normal and an override destination, then point a route or menu key at it." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateCallFlowDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(f) => router.push(`/routing/call-flows/view/?id=${f.id}`)} />
    </div>
  );
}

function CreateCallFlowDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (f: CallFlow) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [index, setIndex] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setName("");
      setIndex("");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<CallFlow>("/call-flows", { organization_id: effectiveOrg, name: name.trim(), code_index: Number(index) });
      toast.success(`Call flow "${created.name}" created`, "Choose its two destinations, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const indexOk = /^[0-9]{1,2}$/.test(index.trim());
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New call flow" description="The destinations and the PIN are edited on the call flow page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="flow-create" loading={busy} disabled={!effectiveOrg || !name.trim() || !indexOk}>Create call flow</Button></>}>
      <form id="flow-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Night mode" onChange={(e) => setName(e.target.value)} />
        <TextField label="Code index" required inputMode="numeric" value={index} error={errors.fields.code_index} placeholder="0 to 99" help="Dialled after the toggle code: *28 followed by this index." onChange={(e) => setIndex(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
