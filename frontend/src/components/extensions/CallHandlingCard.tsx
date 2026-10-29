// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button, Callout, Card, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { ExtensionState } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

/** Do Not Disturb (with the callers who still ring), forwards, call waiting, anonymous call rejection and ring time of one extension (docs/CALL_FEATURES.md §3.2, §3.3; issues #163, #165, #170); `base` is the extension's API path, the administrator's or the user's own. */
export function CallHandlingCard({ base, dnd, editable, onChanged, onDirty, ringTime = true }: { base: string; dnd?: boolean; editable: boolean; onChanged?: () => void; onDirty?: (dirty: boolean) => void; ringTime?: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const state = useApiData<ExtensionState>(`${base}/state`);
  const [busy, setBusy] = useState(false);
  const [always, setAlways] = useState("");
  const [onBusy, setOnBusy] = useState("");
  const [noAnswer, setNoAnswer] = useState("");
  const [offline, setOffline] = useState("");
  const [allow, setAllow] = useState("");
  const [ring, setRing] = useState("30");
  useOnChange(state.data, (v) => {
    if (v) { setAlways(v.cf_always ?? ""); setOnBusy(v.cf_busy ?? ""); setNoAnswer(v.cf_no_answer ?? ""); setOffline(v.cf_unavailable ?? ""); setAllow((v.dnd_allow ?? []).join("\n")); setRing(String(v.ring_seconds)); }
  });
  const s = state.data;
  const allowList = allow.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);
  const allowDirty = !!s && allowList.join("\n") !== (s.dnd_allow ?? []).join("\n");
  const dirty = !!s && (always.trim() !== (s.cf_always ?? "") || onBusy.trim() !== (s.cf_busy ?? "") || noAnswer.trim() !== (s.cf_no_answer ?? "") || offline.trim() !== (s.cf_unavailable ?? "") || allowDirty || (ringTime && ring !== String(s.ring_seconds)));
  // Tell the page (its tab bar warns before a switch would lose the edits).
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  const put = async (body: Record<string, unknown>, done: string, detail?: string) => {
    setBusy(true);
    errors.clear();
    try {
      state.setData(await api.put<ExtensionState>(`${base}/state`, body));
      toast.success(done, detail);
      onChanged?.();
    } catch (err) {
      errors.set(err);
      toast.error("Could not change the call handling", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    const ringChanged = ringTime && !!s && ring !== String(s.ring_seconds);
    void put({ cf_always: always.trim(), cf_busy: onBusy.trim(), cf_no_answer: noAnswer.trim(), cf_unavailable: offline.trim(), ...(allowDirty ? { dnd_allow: allowList } : {}), ...(ringChanged ? { ring_seconds: Number(ring) } : {}) },
      "Call handling saved", ringChanged ? "Forwards take effect at once; the ring time needs a deployment." : "Takes effect at once; no deployment needed.");
  };
  const by = s?.updated_by === "phone" ? "from the phone" : s?.updated_by === "sync" ? "by the engine sync" : "here";
  return (
    <Card title="Call handling" subtitle={s?.updated_at ? `Last changed ${formatRelative(s.updated_at)} ${by}.` : undefined}>
      <form className="stack stack--sm" onSubmit={save}>
        <Switch label="Do Not Disturb" checked={s?.dnd ?? dnd ?? false} disabled={!editable || busy || !s}
          onChange={(e) => void put({ dnd: e.target.checked }, e.target.checked ? "Do Not Disturb on" : "Do Not Disturb off", "Takes effect at once; no deployment needed.")}
          description="Callers hear busy, or the busy greeting when the extension has a voicemail box. From the phone: the Do Not Disturb feature codes; a lamp key on the toggle code shows the state." />
        <TextArea label="Callers who still ring during Do Not Disturb" rows={3} disabled={!editable || !s} value={allow} error={errors.fields.dnd_allow}
          onChange={(e) => setAllow(e.target.value)} help="One number or extension per line, up to 20. A North American number matches however the carrier sends it." />
        <Switch label="Call waiting" checked={!(s?.call_waiting_off ?? false)} disabled={!editable || busy || !s}
          onChange={(e) => void put({ call_waiting_off: !e.target.checked }, e.target.checked ? "Call waiting on" : "Call waiting off", "Takes effect at once; no deployment needed.")}
          description="Off: while you are on a call, other callers hear busy (or go to your busy forward or greeting). *70 before a number turns it off for that call only." />
        <Switch label="Refuse callers who hide their number" checked={s?.anonymous_reject ?? false} disabled={!editable || busy || !s}
          onChange={(e) => void put({ anonymous_reject: e.target.checked }, e.target.checked ? "Anonymous callers refused" : "Anonymous callers accepted", "Takes effect at once; no deployment needed.")}
          description="Outside callers without caller ID hear that this phone does not take such calls. Calls from colleagues always ring. From the phone: *77 / *87." />
        <div className="form-grid">
          <TextField label="Forward all calls to" inputMode="tel" disabled={!editable || !s} value={always} error={errors.fields.cf_always} onChange={(e) => setAlways(e.target.value)} help="An extension or an outside number. Empty: off." />
          <TextField label="Forward when busy to" inputMode="tel" disabled={!editable || !s} value={onBusy} error={errors.fields.cf_busy} onChange={(e) => setOnBusy(e.target.value)} help="Also used while Do Not Disturb is on." />
          <TextField label="Forward when unanswered to" inputMode="tel" disabled={!editable || !s} value={noAnswer} error={errors.fields.cf_no_answer} onChange={(e) => setNoAnswer(e.target.value)} help="After the ring time below." />
          <TextField label="Forward when the phone is offline to" inputMode="tel" disabled={!editable || !s} value={offline} error={errors.fields.cf_unavailable} onChange={(e) => setOffline(e.target.value)} help="While no phone of this extension is connected (power, network or internet outage). Empty: as unanswered." />
          {ringTime ? <TextField label="Ring time (seconds)" type="number" min={5} max={120} disabled={!editable || !s} value={ring} error={errors.fields.ring_seconds} onChange={(e) => setRing(e.target.value)} help="Before voicemail or the no-answer forward. Needs a deployment." /> : null}
        </div>
        <p className="subtle">From the phone: forwarding has its own codes (by default *72 / *73 for all calls, *90 / *91 when busy, *52 / *53 when unanswered); the codes in use are listed on My Phone under Codes. Outside numbers leave through the organization’s outbound routes with this extension’s outbound caller ID.</p>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save call handling</Button></div> : null}
      </form>
    </Card>
  );
}
