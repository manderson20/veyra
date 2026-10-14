// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { CalendarDialog } from "@/components/bells/CalendarDialog";
import { Badge, Button, Card, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CalendarEventOut, CalendarSub, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

function EventsDialog({ calendar, onClose }: { calendar: CalendarSub | null; onClose: () => void }) {
  const events = useApiData<CalendarEventOut[]>(calendar ? `/calendars/${calendar.id}/events` : null);
  return (
    <Dialog open={!!calendar} onClose={onClose} size="lg" title={calendar ? `Upcoming events of "${calendar.name}"` : ""} description="The next two days, as fetched at the last check.">
      {!events.data ? <p className="muted">Loading…</p> : events.data.length === 0 ? <p className="muted">No events in the next two days.</p> : (
        <ul className="list-plain">
          {events.data.map((e) => (
            <li key={`${e.uid}-${e.starts_at}`} className="list-row">
              <span>{e.summary || <span className="subtle">(no title)</span>}</span>
              <span className="subtle nowrap">{e.all_day ? "All day" : formatDateTime(e.starts_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

export default function CalendarsPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<CalendarSub | undefined>();
  const [viewing, setViewing] = useState<CalendarSub | null>(null);
  const [deleting, setDeleting] = useState<CalendarSub | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [polling, setPolling] = useState<string | null>(null);
  const list = useApiData<Page<CalendarSub>>("/calendars", { organization_id: org || undefined, limit: 100 });
  const editable = can("bells.write");
  const manyOrgs = organizations.length > 1;
  const poll = async (c: CalendarSub) => {
    setPolling(c.id);
    try {
      const r = await api.post<CalendarSub>(`/calendars/${c.id}/poll`);
      if (r.last_status === "ok") toast.success(`${c.name} fetched`, `${r.event_count} event(s) in the next two days.`);
      else toast.error(`${c.name} could not be fetched`, r.last_error ?? "");
      list.reload();
    } catch (err) {
      toast.error("Could not fetch", errorMessage(err));
    } finally {
      setPolling(null);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/calendars/${deleting.id}`);
      toast.success(`Calendar "${deleting.name}" removed`, "Its bell schedules are removed with it.");
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<CalendarSub>[] = [
    { key: "name", header: "Calendar", render: (c) => <span><span className="table__primary" style={{ display: "block" }}>{c.name}</span><span className="table__secondary mono">{c.url_display}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (c: CalendarSub) => <span>{c.organization_name}</span> }] : []),
    { key: "poll", header: "Checked", render: (c) => <span>{c.last_polled_at ? formatRelative(c.last_polled_at) : <span className="subtle">Not yet</span>}<span className="table__secondary" style={{ display: "block" }}>every {c.poll_minutes} min</span></span> },
    { key: "events", header: "Events (48 h)", render: (c) => <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setViewing(c); }}>{c.event_count}</Button> },
    { key: "schedules", header: "Bell schedules", render: (c) => c.schedules },
    { key: "status", header: "Status", render: (c) => !c.is_enabled ? <Badge tone="neutral">Disabled</Badge> : c.last_status === "failed" ? <Badge tone="danger" icon="alert">{c.last_error ?? "Failed"}</Badge> : c.last_status === "ok" ? <Badge tone="ok">OK</Badge> : <Badge tone="neutral">Pending</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (c: CalendarSub) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" icon="refresh" loading={polling === c.id} onClick={(e) => { e.stopPropagation(); void poll(c); }}>Fetch now</Button><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(c); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(c); }} aria-label={`Remove ${c.name}`} /></span> }] : []),
  ];
  return (
    <div className="stack">
      <PageHeader title="Calendars" description="External calendars whose events drive bell schedules. Google Calendar works through its secret iCal address; any iCal feed works the same way."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>Add calendar</Button> : null} />
      <Card flush>
        {manyOrgs ? <div className="table-toolbar"><SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} /></div> : null}
        <DataTable columns={columns} rows={list.data?.items} rowKey={(c) => c.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Calendars"
          onRowClick={editable ? (c) => setEditing(c) : undefined} rowLabel={(c) => `Edit calendar ${c.name}`}
          empty={<EmptyState icon="clock" title="No calendars yet">{editable ? "Add the calendar that holds the bell times, then create a bell schedule." : null}</EmptyState>} />
      </Card>
      <CalendarDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <CalendarDialog open={!!editing} calendar={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <EventsDialog calendar={viewing} onClose={() => setViewing(null)} />
      <ConfirmDialog open={!!deleting} title={`Remove the calendar "${deleting?.name ?? ""}"?`} confirmLabel="Remove" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Bell schedules using it are removed too; the calendar itself is untouched.</p>
      </ConfirmDialog>
    </div>
  );
}
