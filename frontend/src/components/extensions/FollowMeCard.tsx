// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, Checkbox, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { FollowMe, FollowMeMember } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

/** Find me / follow me of one extension (docs/CALL_FEATURES.md §3.4); `base` is the extension's API path. */
export function FollowMeCard({ base, editable }: { base: string; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const fm = useApiData<FollowMe>(`${base}/follow-me`);
  const [busy, setBusy] = useState(false);
  const [strategy, setStrategy] = useState("ringall");
  const [initial, setInitial] = useState("0");
  const [confirm, setConfirm] = useState(false);
  const [cidMode, setCidMode] = useState("caller");
  const [members, setMembers] = useState<FollowMeMember[]>([]);
  const [dest, setDest] = useState("");
  useOnChange(fm.data, (v) => {
    if (v) { setStrategy(v.strategy); setInitial(String(v.initial_ring_seconds)); setConfirm(v.confirm_calls); setCidMode(v.caller_id_mode); setMembers(v.members.map((m) => ({ ...m }))); setDest(v.no_answer_destination ?? ""); }
  });
  const d = fm.data;
  const body = { strategy, initial_ring_seconds: Number(initial), confirm_calls: confirm, caller_id_mode: cidMode, members: members.map((m) => ({ ...m, target: m.target.trim(), ring_seconds: Number(m.ring_seconds) })), no_answer_destination: dest.trim() || null };
  const dirty = !!d && JSON.stringify(body) !== JSON.stringify({ strategy: d.strategy, initial_ring_seconds: d.initial_ring_seconds, confirm_calls: d.confirm_calls, caller_id_mode: d.caller_id_mode, members: d.members, no_answer_destination: d.no_answer_destination });
  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      await api.put(`${base}/state`, { fmfm_enabled: on });
      fm.setData(d ? { ...d, enabled: on } : d);
      toast.success(on ? "Follow me on" : "Follow me off", "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not switch follow me", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      fm.setData(await api.put<FollowMe>(`${base}/follow-me`, body));
      toast.success("Follow me saved", "Deploy changes to apply the legs to the phone system.");
    } catch (err) {
      errors.set(err);
      toast.error("Could not save follow me", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const setMember = (i: number, patch: Partial<FollowMeMember>) => setMembers((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  return (
    <Card title="Find me / follow me" subtitle={d?.updated_at ? `Legs last changed ${formatRelative(d.updated_at)}.` : undefined}>
      <form className="stack stack--sm" onSubmit={save}>
        <Switch label="Follow me" checked={d?.enabled ?? false} disabled={!editable || busy || !d || !(d.members.length)} onChange={(e) => void toggle(e.target.checked)}
          description={d && !d.members.length ? "Add at least one number below and save before switching it on." : "Rings the numbers below as well as the phone. From the phone: the follow-me toggle code; a lamp key on it shows the state."} />
        <div className="grid grid--2">
          <SelectField label="Ring" value={strategy} disabled={!editable || !d} options={[{ value: "ringall", label: "All at once" }, { value: "sequential", label: "One after another" }]} onChange={(e) => setStrategy(e.target.value)} />
          <TextField label="Ring the phone alone first (seconds)" type="number" min={0} max={60} disabled={!editable || !d} value={initial} error={errors.fields.initial_ring_seconds} onChange={(e) => setInitial(e.target.value)} help="0 skips it." />
        </div>
        <div className="stack stack--sm">
          {members.map((m, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-end", gap: 8 }}>
              <SelectField label={i === 0 ? "Type" : <span className="sr-only">Type</span>} value={m.type} disabled={!editable} options={[{ value: "extension", label: "Extension" }, { value: "external", label: "Outside number" }]} onChange={(e) => setMember(i, { type: e.target.value as FollowMeMember["type"] })} />
              <TextField label={i === 0 ? "Number" : <span className="sr-only">Number</span>} inputMode="tel" disabled={!editable} value={m.target} error={errors.fields[`members.${i + 1}`]} onChange={(e) => setMember(i, { target: e.target.value })} />
              <TextField label={i === 0 ? "Ring (s)" : <span className="sr-only">Ring seconds</span>} type="number" min={5} max={60} disabled={!editable} value={String(m.ring_seconds)} onChange={(e) => setMember(i, { ring_seconds: Number(e.target.value) })} />
              {editable ? <Button variant="ghost" size="sm" onClick={() => setMembers((ms) => ms.filter((_, j) => j !== i))} aria-label="Remove">Remove</Button> : null}
            </div>
          ))}
          {editable && members.length < 10 ? <div><Button size="sm" icon="plus" onClick={() => setMembers((ms) => [...ms, { type: "external", target: "", ring_seconds: 20 }])}>Add a number</Button></div> : null}
        </div>
        <div className="grid grid--2">
          <SelectField label="Outside numbers see" value={cidMode} disabled={!editable || !d} options={[{ value: "caller", label: "The caller’s number" }, { value: "extension", label: "This extension’s outbound caller ID" }]} onChange={(e) => setCidMode(e.target.value)} />
          <TextField label="When nobody answers, send to extension" inputMode="numeric" disabled={!editable || !d} value={dest} error={errors.fields.no_answer_destination} onChange={(e) => setDest(e.target.value)} help="Empty: this extension’s own no-answer handling (forward, voicemail)." />
        </div>
        <Checkbox label="Outside numbers must press 1 to accept" checked={confirm} disabled={!editable || !d} onChange={(e) => setConfirm(e.target.checked)} description="Keeps a mobile’s voicemail from swallowing the call." />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save follow me</Button></div> : null}
      </form>
    </Card>
  );
}
