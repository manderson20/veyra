// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useMemo, useState } from "react";
import { Button, Callout, Checkbox, Dialog, SearchInput, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Page, VoicemailBox } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";

/** One extended absence for many boxes at once, such as a summer break
 *  (PUT /voicemail/absence, issue #169). */
export function BulkAbsenceDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const [q, setQ] = useState("");
  const boxes = useApiData<Page<VoicemailBox>>("/voicemail", { organization_id: org || undefined, limit: 200 });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [enabled, setEnabled] = useState(true);
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [refuse, setRefuse] = useState(false);
  const [busy, setBusy] = useState(false);
  const items = useMemo(() => boxes.data?.items ?? [], [boxes.data]);
  const shown = useMemo(() => {
    const words = q.trim().toLowerCase();
    return words ? items.filter((b) => `${b.number} ${b.name}`.toLowerCase().includes(words)) : items;
  }, [items, q]);
  const toggle = (id: string, on: boolean) => setPicked((p) => { const n = new Set(p); if (on) n.add(id); else n.delete(id); return n; });
  const allShown = shown.length > 0 && shown.every((b) => picked.has(b.id));

  const apply = async () => {
    setBusy(true);
    try {
      const r = await api.put<{ boxes: number; changed: number }>("/voicemail/absence", {
        box_ids: [...picked], enabled, starts_on: from || null, ends_on: until || null, refuse_messages: refuse,
      });
      toast.success(enabled ? "Extended absence set" : "Extended absence turned off", `${r.changed} of ${r.boxes} box${r.boxes === 1 ? "" : "es"} changed. Takes effect at once; no deployment needed.`);
      onDone();
    } catch (err) {
      toast.error("Could not change the absence", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} busy={busy} size="lg" title="Extended absence for many boxes"
      description="For a break when nobody answers, such as the summer: callers hear each box's extended absence greeting (or its temporary greeting) for these dates."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" onClick={apply} loading={busy} disabled={picked.size === 0}>{enabled ? `Set for ${picked.size} box${picked.size === 1 ? "" : "es"}` : `Turn off for ${picked.size}`}</Button></>}>
      <div className="stack">
        <Switch label="Extended absence on" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} description={enabled ? "On for the dates below." : "Turns it off for the boxes you pick."} />
        {enabled ? (
          <>
            <div className="form-grid">
              <TextField label="First day" type="date" value={from} onChange={(e) => setFrom(e.target.value)} help="Empty: from now." />
              <TextField label="Last day" type="date" value={until} min={from || undefined} onChange={(e) => setUntil(e.target.value)} help="Empty: until it is turned off. After it, it turns itself off." />
            </div>
            <Checkbox label="Take no messages while away" checked={refuse} onChange={(e) => setRefuse(e.target.checked)} description="Callers hear the greeting and the call ends." />
          </>
        ) : null}
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          {organizations.length > 1 ? (
            <SelectField label="Organization" value={org} options={[{ value: "", label: "All" }, ...organizations.map((o) => ({ value: o.id, label: o.name }))]} onChange={(e) => { setOrg(e.target.value); setPicked(new Set()); }} />
          ) : null}
          <SearchInput value={q} onChange={setQ} placeholder="Find a box" label="Find a box" />
          <Button size="sm" onClick={() => setPicked((p) => { const n = new Set(p); shown.forEach((b) => (allShown ? n.delete(b.id) : n.add(b.id))); return n; })} disabled={!shown.length}>
            {allShown ? "Clear these" : `Pick all ${shown.length} shown`}
          </Button>
        </div>
        {boxes.data && boxes.data.total > items.length ? <Callout tone="neutral">Only the first {items.length} of {boxes.data.total} boxes are listed; choose an organization or search to narrow it.</Callout> : null}
        <div className="stack stack--xs" style={{ maxHeight: 280, overflowY: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-2) var(--space-3)" }}>
          {boxes.loading && !boxes.data ? <p className="subtle">Loading boxes…</p> : null}
          {shown.map((b) => (
            <Checkbox key={b.id} label={<><span className="mono">{b.number}</span> {b.name}{b.shared ? " (shared inbox)" : ""}</>} checked={picked.has(b.id)} onChange={(e) => toggle(b.id, e.target.checked)} />
          ))}
          {boxes.data && !shown.length ? <p className="subtle">No box matches.</p> : null}
        </div>
      </div>
    </Dialog>
  );
}
