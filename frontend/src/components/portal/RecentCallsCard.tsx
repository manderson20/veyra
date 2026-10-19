// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { clock, DIRECTION, OUTCOME, party } from "@/components/calls/format";
import { Badge, Button, Callout, Card, Dialog, Icon, SelectField, TextField, useToast } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { CallHistoryItem, CallOutcome, MyExtension, OriginateResult, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { MoreRows, useRowLimit } from "@/components/portal/WidgetSize";

const FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All calls" }, { value: "missed", label: "Missed" }, { value: "answered", label: "Answered" }, { value: "voicemail", label: "To voicemail" },
];

/** The user's recent calls (docs/USER_PORTAL.md §5): other party resolved against their contacts, call back, recordings when the organization allows it. */
export function RecentCallsCard({ extensions }: { extensions: MyExtension[] }) {
  const toast = useToast();
  const [outcome, setOutcome] = useState("");
  const calls = useApiData<Page<CallHistoryItem>>("/me/calls", { limit: 25, ...(outcome ? { outcome } : {}) });
  const [playing, setPlaying] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [dialing, setDialing] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ number: string; name: string } | null>(null);
  const mine = new Set(extensions.map((x) => x.number));
  const phone = extensions.find((x) => x.is_enabled) ?? extensions[0];

  const other = (c: CallHistoryItem) => {
    const fromMine = !!c.from_extension && mine.has(c.from_extension.number);
    return fromMine
      ? { number: c.to_number, name: null, ext: c.to_extension }
      : { number: c.from_number, name: c.from_name, ext: c.from_extension };
  };
  const dial = async (number: string) => {
    if (!phone) return;
    setDialing(number);
    try {
      const r = await api.post<OriginateResult>("/calls/originate", { extension_id: phone.id, number });
      toast.success(`Ringing ${r.extension_number}`, `Pick up to call ${number}.`);
    } catch (err) {
      toast.error("Could not place the call", errorMessage(err));
    } finally {
      setDialing(null);
    }
  };
  const play = (c: CallHistoryItem) => {
    setBlocked(null);
    setPlaying(playing === c.id ? null : c.id);
  };

  const items = calls.data?.items ?? [];
  const rows = useRowLimit(items.length);
  return (
    <Card title="Recent calls" subtitle="Calls to and from your phones in the last 30 days."
      actions={<div className="row"><SelectField label={<span className="sr-only">Show</span>} value={outcome} options={FILTERS} onChange={(e) => setOutcome(e.target.value)} /><a className={buttonClass("secondary", "md")} href={`${API_BASE}/me/calls/export.csv${outcome ? `?outcome=${outcome}` : ""}`} download><Icon name="download" size={14} /> Export</a></div>}>
      {calls.error ? <Callout tone="danger">{errorMessage(calls.error)}</Callout> : null}
      {blocked ? <Callout tone="warn">{blocked}</Callout> : null}
      {calls.data && calls.data.items.length === 0 ? <p className="subtle">No calls yet.</p> : null}
      <ul className="list-plain">
        {items.slice(0, rows.limit).map((c) => {
          const o = other(c);
          const dir = DIRECTION[c.direction];
          const callable = o.number && !mine.has(o.number) && phone;
          return (
            <li key={c.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0, alignItems: "flex-start" }}>
              <span style={{ minWidth: 0 }}>
                <span className="table__primary">
                  <Icon name={dir.icon} size={14} /> {c.contact_name ? <><span>{c.contact_name}</span> <span className="subtle mono">{o.number}</span></> : party(o.number, o.name, o.ext)}
                  {" "}<Badge tone={OUTCOME[c.outcome as CallOutcome]?.tone ?? "neutral"}>{OUTCOME[c.outcome as CallOutcome]?.label ?? c.outcome}</Badge>
                </span>
                <span className="table__secondary" style={{ display: "block" }}>
                  {formatRelative(c.started_at)} · {dir.label}{c.talk_seconds ? ` · ${clock(c.talk_seconds)}` : ""}{c.recorded ? " · recorded" : ""}
                </span>
                {playing === c.id ? (
                  <audio controls autoPlay preload="auto" src={`${API_BASE}/me/calls/${c.id}/recording`} style={{ width: "100%", marginTop: 6 }}
                    onError={() => { setPlaying(null); setBlocked("The recording cannot be played: your organization may not allow users to play their recordings, or the file is gone. An administrator can check the Call Recording page."); }} />
                ) : null}
              </span>
              <span className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
                {c.recorded ? <Button size="sm" icon={playing === c.id ? "stop" : "play"} onClick={() => play(c)}>{playing === c.id ? "Close" : "Recording"}</Button> : null}
                {callable ? <Button size="sm" icon="phone" loading={dialing === o.number} onClick={() => dial(o.number!)}>Call back</Button> : null}
                {callable && !o.ext && !c.contact_name ? <Button size="sm" icon="plus" onClick={() => setAdding({ number: o.number!, name: o.name ?? "" })}>Add to contacts</Button> : null}
              </span>
            </li>
          );
        })}
      </ul>
      <MoreRows {...rows} />
      {adding ? <AddContactDialog number={adding.number} name={adding.name} onClose={() => setAdding(null)} onAdded={() => { setAdding(null); calls.reload(); }} /> : null}
    </Card>
  );
}

/** Save the other party of a call as a contact (#136). */
function AddContactDialog({ number, name: initial, onClose, onAdded }: { number: string; name: string; onClose: () => void; onAdded: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/me/contacts", { name: name.trim(), numbers: [{ label: "work", number }] });
      toast.success(`${name.trim()} added to your contacts`);
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} busy={busy} title="Add to contacts" description={`Save ${number} so its name shows on your calls and voicemail.`}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name.trim()} onClick={save}>Add contact</Button></>}>
      <div className="stack stack--sm">
        <TextField label="Name" required autoFocus value={name} maxLength={200} placeholder="e.g. Pat Parent" onChange={(e) => setName(e.target.value)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Dialog>
  );
}
