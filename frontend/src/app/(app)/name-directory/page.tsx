// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, DataTable, Dialog, EmptyState, IconButton, PageHeader, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

interface Entry { id: string; organization_id: string; name: string; number: string; created_at: string; updated_at: string }
interface NameDirectory { organization_id: string; operator_number: string | null; entries: Entry[] }

/** The dial-by-name directory (docs/CALL_FEATURES.md §4.2; #135): people with
 * a voicemail box are listed by themselves; here go the other names callers
 * may spell ("Front office", "Nurse") and the operator for 0. */
export default function NameDirectoryPage() {
  const { can, session } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const orgId = org || session?.user.home_organization_id || organizations[0]?.id || "";
  const data = useApiData<NameDirectory>(orgId ? "/name-directory" : null, { organization_id: orgId });
  const editable = can("ivr.write");
  const [editing, setEditing] = useState<Entry | "new" | null>(null);
  const [operator, setOperator] = useState("");
  const [savingOp, setSavingOp] = useState(false);
  const opErrors = useFormErrors();
  useOnChange(data.data?.operator_number ?? null, (v) => setOperator(v ?? ""));

  const saveOperator = async (e: FormEvent) => {
    e.preventDefault();
    setSavingOp(true);
    opErrors.clear();
    try {
      data.setData(await api.put<NameDirectory>("/name-directory/operator", { organization_id: orgId, operator_number: operator.trim() || null }));
      toast.success("Operator saved", "Deploy changes to update the phone system.");
    } catch (err) {
      opErrors.set(err);
    } finally {
      setSavingOp(false);
    }
  };
  const remove = async (e: Entry) => {
    try {
      await api.del(`/name-directory/entries/${e.id}`);
      toast.success(`${e.name} removed`, "Deploy changes to update the phone system.");
      data.reload();
    } catch (err) {
      toast.error("Not removed", errorMessage(err));
    }
  };

  const columns: Column<Entry>[] = [
    { key: "name", header: "Name callers spell", render: (e) => <span className="table__primary">{e.name}</span> },
    { key: "number", header: "Connects to", render: (e) => <span className="mono">{e.number}</span> },
    ...(editable ? [{ key: "actions", header: <span className="sr-only">Actions</span>, render: (e: Entry) => <IconButton icon="trash" size="sm" label={`Remove ${e.name}`} onClick={(ev) => { ev.stopPropagation(); void remove(e); }} /> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Dial by name"
        description="The directory callers reach from a menu or an inbound route: they spell a first or last name on the keypad, hear the extension and are connected. Everyone with a voicemail box is listed by themselves; add other names here, such as an office or a role."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setEditing("new")} disabled={!orgId}>Add a name</Button> : null} />
      {organizations.length > 1 ? (
        <SelectField label="Organization" value={orgId} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
      ) : null}
      <Card title="Names" flush>
        <DataTable columns={columns} rows={data.data?.entries} rowKey={(e) => e.id} loading={data.loading} error={data.error} onRetry={data.reload} caption="Directory names"
          onRowClick={editable ? (e) => setEditing(e) : undefined} rowLabel={(e) => `Edit ${e.name}`}
          empty={<EmptyState compact icon="search" title="No extra names">{editable ? "For example “Front office” on the office ring group." : null}</EmptyState>} />
      </Card>
      <Card title="Operator" subtitle="Where a caller in the directory goes on 0. Empty: 0 says goodbye.">
        <form className="stack stack--sm" onSubmit={saveOperator}>
          <TextField label="Operator number" inputMode="numeric" disabled={!editable} value={operator} error={opErrors.fields.operator_number} placeholder="None"
            help="An extension, ring group or queue of the organization." onChange={(e) => setOperator(e.target.value.replace(/\D/g, ""))} />
          {opErrors.message ? <Callout tone="danger">{opErrors.message}</Callout> : null}
          {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={savingOp} disabled={(data.data?.operator_number ?? "") === operator.trim()}>Save</Button></div> : null}
        </form>
      </Card>
      {editing ? <EntryDialog orgId={orgId} entry={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); data.reload(); }} /> : null}
    </div>
  );
}

function EntryDialog({ orgId, entry, onClose, onSaved }: { orgId: string; entry: Entry | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState(entry?.name ?? "");
  const [number, setNumber] = useState(entry?.number ?? "");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (entry) await api.patch(`/name-directory/entries/${entry.id}`, { name: name.trim(), number: number.trim() });
      else await api.post("/name-directory/entries", { organization_id: orgId, name: name.trim(), number: number.trim() });
      toast.success(entry ? "Name saved" : `${name.trim()} added`, "Deploy changes to update the phone system.");
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} busy={busy} title={entry ? `Edit ${entry.name}` : "Add a name"}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="dir-entry" loading={busy} disabled={!name.trim() || !number.trim()}>{entry ? "Save" : "Add"}</Button></>}>
      <form id="dir-entry" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} maxLength={100} placeholder="Front office"
          help="What callers spell: the first or the last word. Letters, digits, spaces and . ' & ( ) / -" onChange={(e) => setName(e.target.value)} />
        <TextField label="Number" required inputMode="numeric" value={number} error={errors.fields.number} placeholder="2000"
          help="An extension, ring group or queue of the organization." onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
