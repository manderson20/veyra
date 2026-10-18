// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { ConferenceRoom, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function ConferencesPage() {
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

  const list = useApiData<Page<ConferenceRoom>>("/conferences", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<ConferenceRoom>[] = [
    { key: "number", header: "Number", render: (c) => <span className="mono">{c.number}</span> },
    {
      key: "name",
      header: "Room",
      render: (c) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{c.name}</span>
          <span className="table__secondary">{c.description ?? <span className="mono">{c.context}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (c: ConferenceRoom) => <span>{c.organization_name}</span> }] : []),
    { key: "pins", header: "PINs", render: (c) => <span className="row" style={{ gap: 4 }}>{c.has_user_pin ? <Badge tone="outline" icon="lock">Participants</Badge> : null}{c.has_admin_pin ? <Badge tone="outline" icon="key">Administrator</Badge> : null}{!c.has_user_pin && !c.has_admin_pin ? <span className="subtle">Open</span> : null}</span> },
    { key: "options", header: "Options", render: (c) => <span className="table__secondary">{[c.max_participants ? `up to ${c.max_participants}` : null, c.record ? "recorded" : null, c.wait_for_admin ? "waits for administrator" : null].filter(Boolean).join(", ") || "—"}</span> },
    { key: "status", header: "Status", render: (c) => !c.is_enabled ? <Badge tone="neutral">Disabled</Badge> : c.problems.length ? <Badge tone="warn" icon="alert">{c.problems.length} problem{c.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Conference rooms"
        description="Meet-me rooms: dial the room's number or point a route or menu key at it. Optional participant and administrator PINs, a participant limit, recording, and a key menu in the room (*1 mutes; administrators lock the room with *2, drop the last caller with *3, mute everyone with *8)."
        actions={can("groups.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New conference room</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name, number or description" label="Search conference rooms" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(c) => c.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Conference rooms"
          onRowClick={(c) => router.push(`/conferences/view/?id=${c.id}`)}
          rowLabel={(c) => `Open conference room ${c.name}`}
          empty={<EmptyState icon="users" title={debounced || org ? "No matching rooms" : "No conference rooms yet"}>{!debounced && !org && can("groups.write") ? "Create a room with a number phones can dial; add PINs if the room should not be open to everyone." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateRoomDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(c) => router.push(`/conferences/view/?id=${c.id}`)} />
    </div>
  );
}

function CreateRoomDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (c: ConferenceRoom) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");

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
      const created = await api.post<ConferenceRoom>("/conferences", { organization_id: effectiveOrg, name: name.trim(), number: number.trim() });
      toast.success(`Conference room "${created.name}" created`, "Set PINs and options, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New conference room" description="PINs and the other options are edited on the room page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="conf-create" loading={busy} disabled={!effectiveOrg || !name.trim() || !/^[0-9]{2,32}$/.test(number.trim())}>Create room</Button></>}>
      <form id="conf-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Board room" onChange={(e) => setName(e.target.value)} />
        <TextField label="Number" required inputMode="numeric" value={number} error={errors.fields.number} placeholder="e.g. 2500" help="Dialled from any phone of the organization." onChange={(e) => setNumber(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
