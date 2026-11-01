// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { ClassOfService, DisaLine, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

interface Draft {
  organization_id: string;
  name: string;
  pin: string;
  class_of_service_id: string;
  caller_id_number: string;
  is_enabled: boolean;
}

function DisaDialog({ open, line, onClose, onSaved }: { open: boolean; line?: DisaLine; onClose: () => void; onSaved: () => void }) {
  const { organizations } = useOrganizationOptions();
  const errors = useFormErrors();
  const toast = useToast();
  const empty: Draft = { organization_id: organizations[0]?.id ?? "", name: "", pin: "", class_of_service_id: "", caller_id_number: "", is_enabled: true };
  const [draft, setDraft] = useState<Draft>(empty);
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stamp = open ? (line?.id ?? "new") : null;
  if (stamp !== openedFor) {
    setOpenedFor(stamp);
    if (open) setDraft(line ? { organization_id: line.organization_id, name: line.name, pin: "", class_of_service_id: line.class_of_service_id, caller_id_number: line.caller_id_number, is_enabled: line.is_enabled } : empty);
  }
  const org = draft.organization_id || organizations[0]?.id || "";
  const classes = useApiData<Page<ClassOfService>>(open && org ? "/classes-of-service" : null, { organization_id: org, limit: 200 });
  const valid = draft.name.trim() && draft.caller_id_number.trim() && draft.class_of_service_id && (line || draft.pin);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const shared = { name: draft.name, class_of_service_id: draft.class_of_service_id, caller_id_number: draft.caller_id_number, is_enabled: draft.is_enabled };
      if (line) await api.patch(`/disa/${line.id}`, { ...shared, ...(draft.pin ? { pin: draft.pin } : {}) });
      else await api.post("/disa", { ...shared, organization_id: org, pin: draft.pin });
      toast.success("Outside line access saved", "Deploy the configuration to apply it.");
      onSaved();
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={line ? `Edit ${line.name}` : "New outside line access"}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="disa-form" loading={busy} disabled={!valid}>Save</Button></>}>
      <form id="disa-form" className="stack stack--sm" onSubmit={save}>
        {!line && organizations.length > 1 ? (
          <SelectField label="Organization" required value={org} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setDraft((d) => ({ ...d, organization_id: e.target.value, class_of_service_id: "" }))} />
        ) : null}
        <TextField label="Name" required maxLength={100} value={draft.name} error={errors.fields.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
        <TextField label={line ? "New PIN" : "PIN"} required={!line} type="password" inputMode="numeric" autoComplete="new-password" value={draft.pin} error={errors.fields.pin}
          help={line ? "Leave empty to keep the current PIN. It can't be shown." : "6 to 10 digits, not a repeated digit or a run. It can't be shown again."} onChange={(e) => setDraft((d) => ({ ...d, pin: e.target.value }))} />
        <SelectField label="Class of service" required value={draft.class_of_service_id} placeholder="Choose a class…" error={errors.fields.class_of_service_id}
          options={(classes.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))}
          help="Calls can use only the outbound routes this class allows, within its call limit." onChange={(e) => setDraft((d) => ({ ...d, class_of_service_id: e.target.value }))} />
        <TextField label="Caller ID number" required value={draft.caller_id_number} error={errors.fields.caller_id_number} help="The number these calls show. A route that forces its own number overrides it." onChange={(e) => setDraft((d) => ({ ...d, caller_id_number: e.target.value }))} />
        <Checkbox label="Enabled" checked={draft.is_enabled} onChange={(e) => setDraft((d) => ({ ...d, is_enabled: e.target.checked }))} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function DisaPage() {
  const { can } = useSession();
  const toast = useToast();
  const list = useApiData<DisaLine[]>("/disa");
  const editable = can("routing.write");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<DisaLine | undefined>();
  const [deleting, setDeleting] = useState<DisaLine | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const saved = () => { list.reload(); setChanged((n) => n + 1); };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/disa/${deleting.id}`);
      toast.success(`"${deleting.name}" deleted`, "Deploy the configuration to apply it.");
      setDeleting(undefined);
      saved();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<DisaLine>[] = [
    { key: "name", header: "Name", render: (l) => <span className="table__primary">{l.name}</span> },
    { key: "class", header: "Class of service", render: (l) => l.class_of_service_name },
    { key: "cid", header: "Caller ID", render: (l) => <span className="mono">{l.caller_id_number}</span> },
    { key: "used", header: "Reached from", render: (l) => l.in_use_by.length ? l.in_use_by.join(", ") : <span className="subtle">Nothing yet</span> },
    { key: "status", header: "Status", render: (l) => <Badge tone={l.is_enabled ? "ok" : "neutral"}>{l.is_enabled ? "Enabled" : "Disabled"}</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (l: DisaLine) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(l); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(l); }} aria-label={`Delete ${l.name}`} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Outside line access"
        description="Callers from outside enter a PIN, hear a dial tone and call out through your lines. Point an inbound route or a menu key at one to use it."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New outside line access</Button> : null}
      />
      <Callout tone="warn" title="This can cost real money if a PIN leaks">
        Anyone with the PIN can run up call charges. Give the class of service only the routes it needs, with a call limit, and never allow international routes unless you must.
      </Callout>
      <PendingChanges refreshKey={changed} />
      <Card flush>
        <DataTable
          columns={columns}
          rows={list.data}
          rowKey={(l) => l.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Outside line access"
          onRowClick={editable ? (l) => setEditing(l) : undefined}
          rowLabel={(l) => `Edit ${l.name}`}
          empty={<EmptyState icon="key" title="No outside line access">{editable ? "Nothing can dial out this way until you add one and point a route at it." : null}</EmptyState>}
        />
      </Card>
      <DisaDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={saved} />
      <DisaDialog open={!!editing} line={editing} onClose={() => setEditing(undefined)} onSaved={saved} />
      <ConfirmDialog open={!!deleting} title={`Delete "${deleting?.name ?? ""}"?`} confirmLabel="Delete" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Its PIN stops working at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}
