// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, SelectField, Switch, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { BellRing, BellSchedule, BellScheduleInput, BellTrigger, CalendarSub, Page, PagingPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const TRIGGER_LABELS: Record<BellTrigger, string> = { start: "When an event starts", end: "When an event ends", both: "At start and end" };

function ScheduleDialog({ open, onClose, schedule, onSaved }: { open: boolean; onClose: () => void; schedule?: BellSchedule; onSaved: () => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !schedule);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [calendarId, setCalendarId] = useState("");
  const [pageId, setPageId] = useState("");
  const [match, setMatch] = useState("*");
  const [trigger, setTrigger] = useState<BellTrigger>("start");
  const [tolerance, setTolerance] = useState("90");
  const [allDay, setAllDay] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = schedule?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const calendars = useApiData<Page<CalendarSub>>(open && effectiveOrg ? "/calendars" : null, { organization_id: effectiveOrg, limit: 100 });
  const pages = useApiData<Page<PagingPage>>(open && effectiveOrg ? "/pages" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(schedule?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(schedule?.name ?? "");
      setCalendarId(schedule?.calendar_id ?? "");
      setPageId(schedule?.page_id ?? "");
      setMatch(schedule?.match ?? "*");
      setTrigger(schedule?.trigger ?? "start");
      setTolerance(String(schedule?.tolerance_seconds ?? 90));
      setAllDay(schedule?.all_day_events ?? false);
      setEnabled(schedule?.is_enabled ?? true);
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: BellScheduleInput = { name: name.trim(), calendar_id: calendarId, page_id: pageId, match: match.trim() || "*", trigger, tolerance_seconds: Number(tolerance) || 90, all_day_events: allDay, is_enabled: enabled };
      if (schedule) await api.patch<BellSchedule>(`/bell-schedules/${schedule.id}`, body);
      else await api.post<BellSchedule>("/bell-schedules", { organization_id: effectiveOrg, ...body });
      toast.success(schedule ? "Bell schedule saved" : "Bell schedule created");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const recordedPages = (pages.data?.items ?? []).filter((p) => p.audio);
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={schedule ? `Edit "${schedule.name}"` : "New bell schedule"}
      description="Every matching event of the calendar rings the page (a recording into its zones) at the event's start, its end, or both, as chosen below."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="bell-form" loading={busy} disabled={!effectiveOrg || !name.trim() || !calendarId || !pageId}>{schedule ? "Save changes" : "Create schedule"}</Button></>}>
      <form id="bell-form" className="stack stack--sm" onSubmit={submit}>
        {!schedule && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setCalendarId(""); setPageId(""); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Class periods" onChange={(e) => setName(e.target.value)} />
        <div className="form-grid">
          <SelectField label="Calendar" required value={calendarId} error={errors.fields.calendar_id} placeholder="Choose a calendar" options={(calendars.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setCalendarId(e.target.value)} />
          <SelectField label="Page to ring" required value={pageId} error={errors.fields.page_id} placeholder="Choose a recorded page" help="Only pages with a recording can be rung by a schedule."
            options={recordedPages.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setPageId(e.target.value)} />
        </div>
        <div className="form-grid">
          <TextField label="Events to ring" value={match} error={errors.fields.match} help="Pattern on the event title; * matches everything, Bell:* only titles starting with Bell:." onChange={(e) => setMatch(e.target.value)} />
          <SelectField label="Ring" value={trigger} options={(Object.keys(TRIGGER_LABELS) as BellTrigger[]).map((t) => ({ value: t, label: TRIGGER_LABELS[t] }))} onChange={(e) => setTrigger(e.target.value as BellTrigger)} />
        </div>
        <div className="form-grid">
          <TextField label="Late tolerance (seconds)" type="number" min={0} max={900} value={tolerance} error={errors.fields.tolerance_seconds} help="A bell missed by this much is still rung; later ones are skipped." onChange={(e) => setTolerance(e.target.value)} />
          <div className="field" style={{ justifyContent: "flex-end" }}><Checkbox label="Include all-day events" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} /></div>
        </div>
        <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function RingsDialog({ schedule, onClose }: { schedule: BellSchedule | null; onClose: () => void }) {
  const rings = useApiData<BellRing[]>(schedule ? `/bell-schedules/${schedule.id}/rings` : null);
  return (
    <Dialog open={!!schedule} onClose={onClose} size="lg" title={schedule ? `Rings of "${schedule.name}"` : ""} description="The last 50 rings.">
      {!rings.data ? <p className="muted">Loading…</p> : rings.data.length === 0 ? <p className="muted">Nothing rung yet.</p> : (
        <ul className="list-plain">
          {rings.data.map((r) => (
            <li key={r.id} className="list-row">
              <span><span>{r.summary}</span><span className="subtle" style={{ display: "block" }}>due {formatDateTime(r.due_at)}{typeof r.detail.message === "string" ? ` · ${r.detail.message}` : ""}</span></span>
              <Badge tone={r.outcome === "started" ? "ok" : r.outcome === "failed" ? "danger" : "neutral"}>{r.outcome}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}

export default function BellsPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<BellSchedule | undefined>();
  const [viewing, setViewing] = useState<BellSchedule | null>(null);
  const [deleting, setDeleting] = useState<BellSchedule | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [ringing, setRinging] = useState<string | null>(null);
  const list = useApiData<Page<BellSchedule>>("/bell-schedules", { organization_id: org || undefined, limit: 100 });
  const editable = can("bells.write");
  const manyOrgs = organizations.length > 1;
  const ringNow = async (s: BellSchedule) => {
    setRinging(s.id);
    try {
      const r = await api.post<{ started: boolean; message: string }>(`/bell-schedules/${s.id}/ring`);
      if (r.started) toast.success("Ringing", r.message);
      else toast.error("Not rung", r.message);
    } catch (err) {
      toast.error("Not rung", errorMessage(err));
    } finally {
      setRinging(null);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/bell-schedules/${deleting.id}`);
      toast.success(`Bell schedule "${deleting.name}" deleted`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<BellSchedule>[] = [
    { key: "name", header: "Schedule", render: (s) => <span><span className="table__primary" style={{ display: "block" }}>{s.name}</span><span className="table__secondary">{s.calendar_name} → {s.page_name}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (s: BellSchedule) => <span>{s.organization_name}</span> }] : []),
    { key: "match", header: "Events", render: (s) => <span><span className="mono">{s.match}</span><span className="table__secondary" style={{ display: "block" }}>{TRIGGER_LABELS[s.trigger]}</span></span> },
    { key: "next", header: "Next ring", render: (s) => s.next_rings[0] ? <span>{s.next_rings[0].summary}<span className="table__secondary" style={{ display: "block" }}>{formatRelative(s.next_rings[0].due_at)} · {formatDateTime(s.next_rings[0].due_at)}</span></span> : <span className="subtle">Nothing upcoming</span> },
    { key: "status", header: "Status", render: (s) => !s.is_enabled ? <Badge tone="neutral">Disabled</Badge> : s.problems.length ? <Badge tone="warn" icon="alert">{s.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
    { key: "actions", header: "", render: (s) => (
      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
        <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setViewing(s); }}>History</Button>
        {editable ? <Button size="sm" icon="megaphone" loading={ringing === s.id} onClick={(e) => { e.stopPropagation(); void ringNow(s); }}>Ring now</Button> : null}
        {editable ? <Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(s); }}>Edit</Button> : null}
        {editable ? <Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(s); }} aria-label={`Delete ${s.name}`} /> : null}
      </span>
    ) },
  ];
  return (
    <div className="stack">
      <PageHeader title="Bell schedules" description="A calendar's events ring a recorded page into its zones. The worker checks the calendars every few minutes and rings each event once."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New bell schedule</Button> : null} />
      <Card flush>
        {manyOrgs ? <div className="table-toolbar"><SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} /></div> : null}
        <DataTable columns={columns} rows={list.data?.items} rowKey={(s) => s.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Bell schedules"
          onRowClick={editable ? (s) => setEditing(s) : undefined} rowLabel={(s) => `Edit bell schedule ${s.name}`}
          empty={<EmptyState icon="clock" title="No bell schedules yet">{editable ? "Add a calendar and a page with a recording, then link them here." : null}</EmptyState>} />
      </Card>
      <ScheduleDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <ScheduleDialog open={!!editing} schedule={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <RingsDialog schedule={viewing} onClose={() => setViewing(null)} />
      <ConfirmDialog open={!!deleting} title={`Delete the bell schedule "${deleting?.name ?? ""}"?`} confirmLabel="Delete" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>The calendar and the page stay.</p>
      </ConfirmDialog>
    </div>
  );
}
