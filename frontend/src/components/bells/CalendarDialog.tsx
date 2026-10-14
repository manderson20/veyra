// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Dialog, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { CalendarSub, CalendarSubInput } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** Subscribe to or edit an iCal feed (docs/PAGING_RECORDINGS.md §4.1). */
export function CalendarDialog({ open, onClose, calendar, onSaved }: { open: boolean; onClose: () => void; calendar?: CalendarSub; onSaved: (c: CalendarSub) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !calendar);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [pollMinutes, setPollMinutes] = useState("3");
  const [timezone, setTimezone] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = calendar?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));

  useOnChange(open, () => {
    if (open) {
      setOrg(calendar?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(calendar?.name ?? "");
      setUrl("");
      setPollMinutes(String(calendar?.poll_minutes ?? 3));
      setTimezone(calendar?.timezone ?? "");
      setEnabled(calendar?.is_enabled ?? true);
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: CalendarSubInput = { name: name.trim(), poll_minutes: Number(pollMinutes) || 3, timezone: timezone.trim() || null, is_enabled: enabled };
      if (url.trim()) body.url = url.trim();
      const saved = calendar
        ? await api.patch<CalendarSub>(`/calendars/${calendar.id}`, body)
        : await api.post<CalendarSub>("/calendars", { organization_id: effectiveOrg, ...body });
      toast.success(calendar ? "Calendar saved" : `Calendar "${saved.name}" added`, "It is fetched within a minute; events appear on its page.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={calendar ? `Edit calendar "${calendar.name}"` : "Add a calendar"}
      description="An iCal feed. For Google Calendar, copy the calendar's secret address in iCal format from its settings; the address is stored encrypted and never shown again."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="calendar-form" loading={busy} disabled={!effectiveOrg || !name.trim() || (!calendar && !url.trim())}>{calendar ? "Save changes" : "Add calendar"}</Button></>}>
      <form id="calendar-form" className="stack stack--sm" onSubmit={submit}>
        {!calendar && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Bell schedule" onChange={(e) => setName(e.target.value)} />
        <TextField label={calendar ? "New feed address (leave blank to keep the current one)" : "Feed address"} required={!calendar} type="url" value={url} error={errors.fields.url}
          placeholder="https://calendar.google.com/calendar/ical/…/private-…/basic.ics" help={calendar ? `Current: ${calendar.url_display}` : "https, http or webcal."} onChange={(e) => setUrl(e.target.value)} />
        <div className="form-grid">
          <TextField label="Check every (minutes)" type="number" min={1} max={60} value={pollMinutes} error={errors.fields.poll_minutes} onChange={(e) => setPollMinutes(e.target.value)} />
          <TextField label="Time zone" value={timezone} error={errors.fields.timezone} placeholder="From the feed" help="IANA name for feeds without one, e.g. America/Chicago." onChange={(e) => setTimezone(e.target.value)} />
        </div>
        <Switch label="Enabled" description="Disabled calendars are not fetched and ring nothing." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
