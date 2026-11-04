// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Checkbox, Dialog, Icon, Switch, TextField, useToast } from "@/components/ui";
import { API_BASE, api, errorMessage } from "@/lib/api";
import type { VoicemailAbsence, VoicemailAlternate, VoicemailGreeting } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import { useRecorder } from "@/hooks/useRecorder";

const HELP: Record<VoicemailGreeting["kind"], string> = {
  unavail: "Played when you do not answer.",
  busy: "Played when you are on another call.",
  greet: "Your name, used by the directory and the default greetings.",
  temp: "Played instead of the others while it exists; remove it when you are back.",
  absence: "For a long absence (summer break, leave): played as the temporary greeting between the dates below, then removed by itself.",
  afterhours: "Played instead of the unavailable greeting while the office is closed, when your administrator has set the box's hours. A temporary greeting still wins.",
  alternate: "A second greeting you keep ready (testing week, a field trip, a busy season). Turn it on below and it plays instead of the unavailable and busy greetings. A temporary greeting still wins.",
};
const MAX_SECONDS = 60;

/**
 * The four greetings of a voicemail box (docs/USER_PORTAL.md §3): play,
 * upload, record in the browser, delete. `base` is `/me/voicemail/<id>` or
 * `/voicemail/<id>`.
 */
export function GreetingsPanel({ base, editable = true }: { base: string; editable?: boolean }) {
  const toast = useToast();
  const list = useApiData<VoicemailGreeting[]>(`${base}/greetings`);
  const [playing, setPlaying] = useState<string | null>(null);
  const [recording, setRecording] = useState<VoicemailGreeting | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stamp, setStamp] = useState(0);

  const upload = async (g: VoicemailGreeting, file: Blob, filename: string) => {
    setBusy(g.kind);
    setError(null);
    try {
      const form = new FormData();
      form.set("file", file, filename);
      list.setData(await api.upload<VoicemailGreeting[]>(`${base}/greetings/${g.kind}`, form, "PUT"));
      setStamp((n) => n + 1);
      setPlaying(null);
      toast.success(`${g.label} greeting saved`, "Converted for the phone system; it plays from the next call.");
      setRecording(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const remove = async (g: VoicemailGreeting) => {
    setBusy(g.kind);
    setError(null);
    try {
      list.setData(await api.del<VoicemailGreeting[]>(`${base}/greetings/${g.kind}`));
      setPlaying(null);
      toast.success(`${g.label} greeting removed`, "The phone system's standard greeting plays instead.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  if (list.error) {
    const code = (list.error as { code?: string } | null)?.code;
    return <Callout tone={code === "vmstore_unavailable" ? "warn" : "danger"} title="Greetings are not available">{errorMessage(list.error)}</Callout>;
  }
  return (
    <div className="stack stack--sm">
      {error ? <Callout tone="danger">{error}</Callout> : null}
      <ul className="list-plain">
        {(list.data ?? []).map((g) => (
          <li key={g.kind} className="list-row" style={{ paddingLeft: 0, paddingRight: 0, alignItems: "flex-start" }}>
            <span style={{ minWidth: 0 }}>
              <span className="table__primary">{g.label} {g.recorded ? <Badge tone="ok">Recorded</Badge> : <Badge tone="neutral">Standard</Badge>}</span>
              <span className="table__secondary" style={{ display: "block" }}>{HELP[g.kind]}</span>
              {playing === g.kind && g.recorded ? (
                <audio controls autoPlay preload="auto" src={`${API_BASE}${base}/greetings/${g.kind}/audio?v=${stamp}`} style={{ width: "100%", marginTop: 6 }} />
              ) : null}
            </span>
            <span className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
              {g.recorded ? <Button size="sm" icon={playing === g.kind ? "stop" : "play"} onClick={() => setPlaying(playing === g.kind ? null : g.kind)}>{playing === g.kind ? "Close" : "Play"}</Button> : null}
              {editable ? (
                <>
                  <label className="btn btn--secondary btn--sm" style={{ cursor: busy ? "wait" : "pointer" }}>
                    <Icon name="upload" size={14} /> Upload
                    <input type="file" accept="audio/*,.wav,.mp3,.ogg,.m4a,.webm" style={{ display: "none" }} disabled={!!busy}
                      onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void upload(g, f, f.name); }} />
                  </label>
                  <Button size="sm" icon="mic" onClick={() => { setError(null); setRecording(g); }} disabled={!!busy}>Record</Button>
                  {g.recorded ? <Button size="sm" variant="danger" icon="trash" loading={busy === g.kind} onClick={() => remove(g)}>Remove</Button> : null}
                </>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="subtle" style={{ margin: 0 }}>Up to {MAX_SECONDS} seconds each. You can also record from your phone: dial *97, then 0 for mailbox options.</p>
      <AlternateSwitch base={base} editable={editable} recorded={!!list.data?.find((g) => g.kind === "alternate")?.recorded} />
      <AbsenceCard base={base} editable={editable} />
      <RecordDialog key={recording?.kind ?? "none"} greeting={recording} busy={!!busy} onClose={() => setRecording(null)} onSave={(blob) => recording && upload(recording, blob, "recording.webm")} />
    </div>
  );
}

/** The alternate greeting's switch (issue #392): applies at once. */
function AlternateSwitch({ base, editable, recorded }: { base: string; editable: boolean; recorded: boolean }) {
  const toast = useToast();
  const alt = useApiData<VoicemailAlternate>(`${base}/alternate`);
  const [busy, setBusy] = useState(false);
  if (alt.error || !alt.data) return null;
  const on = alt.data.enabled;
  const put = async (enabled: boolean) => {
    setBusy(true);
    try {
      alt.setData(await api.put<VoicemailAlternate>(`${base}/alternate`, { enabled }));
      toast.success(enabled ? "Alternate greeting on" : "Alternate greeting off", "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not change the greeting", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack stack--xs" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <Switch label="Use the alternate greeting" checked={on} disabled={!editable || busy || (!on && !recorded)}
        onChange={(e) => void put(e.target.checked)}
        description={on ? (recorded ? "On: callers hear your alternate greeting." : "On, but the alternate greeting was removed: callers hear the usual greetings.") : recorded ? "Off: callers hear the usual greetings." : "Record or upload the alternate greeting above first."} />
    </div>
  );
}

/** Extended absence (issue #169): dates, and whether callers may still leave a message. */
function AbsenceCard({ base, editable }: { base: string; editable: boolean }) {
  const toast = useToast();
  const absence = useApiData<VoicemailAbsence>(`${base}/absence`);
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const a = absence.data;
  useOnChange(a, (v) => {
    if (v) { setFrom(v.starts_on ?? ""); setUntil(v.ends_on ?? ""); }
  });
  const put = async (body: Partial<VoicemailAbsence>, done: string) => {
    setBusy(true);
    try {
      absence.setData(await api.put<VoicemailAbsence>(`${base}/absence`, body));
      toast.success(done, "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not change the absence", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  if (absence.error || !a) return null;
  const datesDirty = from !== (a.starts_on ?? "") || until !== (a.ends_on ?? "");
  return (
    <div className="stack stack--xs" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <Switch label="Extended absence" checked={a.enabled} disabled={!editable || busy}
        onChange={(e) => void put({ enabled: e.target.checked, starts_on: from || null, ends_on: until || null }, e.target.checked ? "Extended absence on" : "Extended absence off")}
        description={a.active ? (a.applied ? "On now: callers hear your extended absence greeting." : "On now; record an extended absence greeting above, or callers hear your temporary greeting.") : a.enabled ? "Scheduled: starts on the first day below." : "Record the extended absence greeting above, pick the dates, then turn this on."} />
      <div className="form-grid">
        <TextField label="First day" type="date" disabled={!editable || busy} value={from} onChange={(e) => setFrom(e.target.value)} help="Empty: from now." />
        <TextField label="Last day" type="date" disabled={!editable || busy} value={until} min={from || undefined} onChange={(e) => setUntil(e.target.value)} help="Empty: until you turn it off. After it, the absence turns itself off." />
      </div>
      <Checkbox label="Take no messages while away" checked={a.refuse_messages} disabled={!editable || busy}
        onChange={(e) => void put({ refuse_messages: e.target.checked }, e.target.checked ? "Messages refused while away" : "Messages taken while away")}
        description="Callers hear the greeting and the call ends; nothing waits in the box when you come back." />
      {editable && datesDirty ? <div className="form-actions"><Button size="sm" variant="primary" loading={busy} onClick={() => void put({ starts_on: from || null, ends_on: until || null }, "Absence dates saved")}>Save dates</Button></div> : null}
    </div>
  );
}

/** Record a greeting with the microphone (MediaRecorder), preview, save. */
function RecordDialog({ greeting, busy, onClose, onSave }: { greeting: VoicemailGreeting | null; busy: boolean; onClose: () => void; onSave: (blob: Blob) => void }) {
  const { state, seconds, blob, url, start, stop, reset } = useRecorder(MAX_SECONDS);

  return (
    <Dialog open={greeting !== null} onClose={onClose} busy={busy} title={`Record the ${greeting?.label.toLowerCase() ?? ""} greeting`}
      footer={<>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        {state === "done" ? <Button onClick={reset} disabled={busy}>Record again</Button> : null}
        <Button variant="primary" disabled={!blob || busy} loading={busy} onClick={() => blob && onSave(blob)}>Save greeting</Button>
      </>}>
      <div className="stack stack--sm">
        {state === "unsupported" ? <Callout tone="warn">This browser cannot record audio. Upload a file instead, or record from your phone with *97.</Callout> : null}
        {state === "denied" ? <Callout tone="warn">The microphone is not available: allow it for this site and try again, or upload a file.</Callout> : null}
        {state === "idle" ? <p>Click Start, speak after the counter begins, then Stop. Up to {MAX_SECONDS} seconds.</p> : null}
        {state === "recording" ? <p><Badge tone="danger">Recording</Badge> <span className="mono">{seconds}s</span> of {MAX_SECONDS}</p> : null}
        {state === "done" && url ? <><p>Listen before saving:</p><audio controls src={url} style={{ width: "100%" }} /></> : null}
        <div className="row">
          {state === "idle" || state === "denied" || state === "unsupported" ? <Button icon="mic" onClick={start} disabled={state === "unsupported"}>Start</Button> : null}
          {state === "recording" ? <Button icon="stop" onClick={stop}>Stop</Button> : null}
        </div>
      </div>
    </Dialog>
  );
}
