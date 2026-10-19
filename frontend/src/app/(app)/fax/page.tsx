// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { ACTIVE_FAX_STATES, FAX_STATE } from "@/components/portal/FaxCard";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SelectField, Switch, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { FaxInbox, FaxJob, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;
const STATES = ["queued", "dialling", "sending", "sent", "failed", "received", "cancelled"];

export default function FaxPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const manage = can("fax.manage");
  const [org, setOrg] = useState("");
  const [state, setState] = useState("");
  const [direction, setDirection] = useState("");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<FaxInbox | "new" | null>(null);
  const jobs = useApiData<Page<FaxJob>>("/fax/jobs", {
    organization_id: org || undefined, state: state || undefined, direction: direction || undefined, limit: LIMIT, offset,
  });
  const inboxes = useApiData<Page<FaxInbox>>("/fax/inboxes", { organization_id: org || undefined, limit: 200 });
  const manyOrgs = organizations.length > 1;

  // Faxes on their way: keep the list fresh.
  const active = (jobs.data?.items ?? []).some((j) => ACTIVE_FAX_STATES.includes(j.state));
  const reloadJobs = jobs.reload;
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(reloadJobs, 10000);
    return () => window.clearInterval(t);
  }, [active, reloadJobs]);

  const act = async (j: FaxJob, what: "cancel" | "retry") => {
    try {
      await api.post(`/fax/jobs/${j.id}/${what}`);
      jobs.reload();
    } catch (err) {
      toast.error(what === "cancel" ? "Could not cancel" : "Could not retry", errorMessage(err));
    }
  };

  const jobColumns: Column<FaxJob>[] = [
    {
      key: "who", header: "Fax", render: (j) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{j.direction === "out" ? "To" : "From"} <span className="mono">{j.number}</span></span>
          <span className="table__secondary">
            {j.direction === "out" ? `${j.user_name ?? "—"}${j.extension_number ? ` (${j.extension_number})` : ""}` : `Inbox ${j.inbox_name ?? "—"}`}
            {j.original_name ? ` · ${j.original_name}` : ""}
          </span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (j: FaxJob) => <span>{organizations.find((o) => o.id === j.organization_id)?.name ?? "—"}</span> }] : []),
    { key: "pages", header: "Pages", render: (j) => <span>{j.pages}</span> },
    {
      key: "state", header: "State", render: (j) => (
        <span className="stack stack--sm">
          <Badge tone={FAX_STATE[j.state]?.tone ?? "neutral"}>{FAX_STATE[j.state]?.label ?? j.state}{j.attempts > 1 ? ` · attempt ${j.attempts}` : ""}</Badge>
          {j.error ? <span className="subtle">{j.error}</span> : null}
        </span>
      ),
    },
    { key: "when", header: "When", render: (j) => <span className="subtle nowrap">{formatDateTime(j.finished_at ?? j.created_at)}</span> },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (j) => (
        <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
          {manage && j.has_file ? <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/fax/jobs/${j.id}/file`} download>PDF</a> : null}
          {manage && ACTIVE_FAX_STATES.includes(j.state) ? <Button size="sm" onClick={() => act(j, "cancel")}>Cancel</Button> : null}
          {manage && ["failed", "cancelled"].includes(j.state) && j.direction === "out" ? <Button size="sm" onClick={() => act(j, "retry")}>Retry</Button> : null}
        </span>
      ),
    },
  ];
  const inboxColumns: Column<FaxInbox>[] = [
    { key: "name", header: "Inbox", render: (i) => <span><span className="table__primary" style={{ display: "block" }}>{i.name}</span><span className="table__secondary mono">{i.context}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (i: FaxInbox) => <span>{i.organization_name}</span> }] : []),
    { key: "to", header: "Emails the PDF to", render: (i) => i.recipients.length ? <span>{i.recipients.join(", ")}</span> : <Badge tone="warn">No recipients</Badge> },
    { key: "station", header: "Station ID", render: (i) => <span className="mono">{i.station_id ?? <span className="subtle">organization&apos;s</span>}</span> },
    { key: "status", header: "Status", render: (i) => i.is_enabled ? <Badge tone="ok">Enabled</Badge> : <Badge tone="neutral">Disabled</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Fax"
        description="Faxes users send from My Phone and faxes received on the inboxes. An inbox is a destination, “Fax to email”: point a DID or inbound route at it and the pages arrive as a PDF at its recipients."
        actions={manage ? <Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New fax inbox</Button> : null}
      />
      <PendingChanges refreshKey={inboxes.data?.total} />
      <Card title="Fax inboxes" flush>
        <DataTable columns={inboxColumns} rows={inboxes.data?.items} rowKey={(i) => i.id} loading={inboxes.loading} error={inboxes.error} onRetry={inboxes.reload}
          caption="Fax inboxes" onRowClick={manage ? (i) => setEditing(i) : undefined} rowLabel={(i) => `Edit fax inbox ${i.name}`}
          empty={<EmptyState compact icon="file" title="No fax inboxes">{manage ? "Create one, then point a DID or an inbound route at “Fax to email”." : "No inbox has been created yet."}</EmptyState>} />
      </Card>
      <Card title="Faxes" flush>
        <div className="table-toolbar">
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
          <SelectField label={<span className="sr-only">Direction</span>} value={direction} placeholder="Sent and received"
            options={[{ value: "out", label: "Sent" }, { value: "in", label: "Received" }]} onChange={(e) => { setDirection(e.target.value); setOffset(0); }} />
          <SelectField label={<span className="sr-only">State</span>} value={state} placeholder="Any state"
            options={STATES.map((s) => ({ value: s, label: FAX_STATE[s]?.label ?? s }))} onChange={(e) => { setState(e.target.value); setOffset(0); }} />
        </div>
        <DataTable columns={jobColumns} rows={jobs.data?.items} rowKey={(j) => j.id} loading={jobs.loading} error={jobs.error} onRetry={jobs.reload}
          caption="Faxes" empty={<EmptyState compact icon="history" title="No faxes">{state || direction || org ? "No faxes match the filters." : "Faxes appear here as users send them and inboxes receive them."}</EmptyState>}
          pagination={jobs.data && jobs.data.total > LIMIT ? <Pagination total={jobs.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      {editing ? (
        <InboxDialog inbox={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); inboxes.reload(); }} />
      ) : null}
    </div>
  );
}

function InboxDialog({ inbox, onClose, onSaved }: { inbox: FaxInbox | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(true);
  const [org, setOrg] = useState(inbox?.organization_id ?? session?.user.home_organization_id ?? "");
  const [name, setName] = useState(inbox?.name ?? "");
  const [recipients, setRecipients] = useState((inbox?.recipients ?? []).join("\n"));
  const [station, setStation] = useState(inbox?.station_id ?? "");
  const [header, setHeader] = useState(inbox?.header ?? "");
  const [enabled, setEnabled] = useState(inbox?.is_enabled ?? true);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  useOnChange(inbox?.id, () => setConfirmDelete(false));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    errors.clear();
    const body = {
      name: name.trim(),
      recipients: recipients.split(/[\s,;]+/).filter(Boolean),
      station_id: station.trim() || null,
      header: header.trim() || null,
      is_enabled: enabled,
    };
    try {
      if (inbox) {
        await api.patch<FaxInbox>(`/fax/inboxes/${inbox.id}`, body);
        toast.success(`Fax inbox “${body.name}” saved`, "Deploy the configuration for the engine to follow.");
      } else {
        await api.post<FaxInbox>("/fax/inboxes", { organization_id: effectiveOrg, ...body });
        toast.success(`Fax inbox “${body.name}” created`, "Point a DID or an inbound route at it, then deploy.");
      }
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    if (!inbox) return;
    setBusy("delete");
    errors.clear();
    try {
      await api.del(`/fax/inboxes/${inbox.id}`);
      toast.success(`Fax inbox “${inbox.name}” deleted`);
      onSaved();
    } catch (err) {
      errors.set(err);
      setConfirmDelete(false);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog open onClose={onClose} busy={!!busy} title={inbox ? `Fax inbox: ${inbox.name}` : "New fax inbox"}
      description="Faxes that reach this inbox are emailed as PDFs to the recipients and listed under Faxes."
      footer={(
        <>
          {inbox ? (
            confirmDelete
              ? <Button variant="danger" onClick={remove} loading={busy === "delete"}>Yes, delete</Button>
              : <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={!!busy}>Delete</Button>
          ) : null}
          <Button onClick={onClose} disabled={!!busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="fax-inbox" loading={busy === "save"} disabled={!effectiveOrg || !name.trim()}>{inbox ? "Save" : "Create inbox"}</Button>
        </>
      )}>
      <form id="fax-inbox" className="stack stack--sm" onSubmit={submit}>
        {!inbox && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front office" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Email the PDF to" rows={3} value={recipients} error={errors.fields.recipients} placeholder="office@example.org" spellCheck={false}
          help="One address per line. System → Settings → Email must be on for the mail to leave." onChange={(e) => setRecipients(e.target.value)} />
        <div className="grid grid--2">
          <TextField label="Station ID" value={station} error={errors.fields.station_id} inputMode="tel" placeholder="Organization's"
            help="Announced to the sending machine; empty uses the organization's." onChange={(e) => setStation(e.target.value)} />
          <TextField label="Page header" value={header} error={errors.fields.header} maxLength={64} placeholder="Organization's" onChange={(e) => setHeader(e.target.value)} />
        </div>
        <Switch label="Enabled" description="A disabled inbox is kept but the routes pointing at it stop receiving." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {confirmDelete ? <Callout tone="warn">Delete this inbox? Routes pointing at it must be changed first; received faxes stay listed.</Callout> : null}
      </form>
    </Dialog>
  );
}
