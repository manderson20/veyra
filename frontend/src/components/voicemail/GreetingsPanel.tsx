// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Callout, Dialog, Icon, useToast } from "@/components/ui";
import { API_BASE, api, errorMessage } from "@/lib/api";
import type { VoicemailGreeting } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const HELP: Record<VoicemailGreeting["kind"], string> = {
  unavail: "Played when you do not answer.",
  busy: "Played when you are on another call.",
  greet: "Your name, used by the directory and the default greetings.",
  temp: "Played instead of the others while it exists; remove it when you are back.",
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
      <RecordDialog key={recording?.kind ?? "none"} greeting={recording} busy={!!busy} onClose={() => setRecording(null)} onSave={(blob) => recording && upload(recording, blob, "recording.webm")} />
    </div>
  );
}

/** Record a greeting with the microphone (MediaRecorder), preview, save. */
function RecordDialog({ greeting, busy, onClose, onSave }: { greeting: VoicemailGreeting | null; busy: boolean; onClose: () => void; onSave: (blob: Blob) => void }) {
  const [state, setState] = useState<"idle" | "recording" | "done" | "unsupported" | "denied">("idle");
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number | null>(null);

  const stop = () => {
    if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
    const r = recorder.current;
    if (r && r.state !== "inactive") r.stop();
    r?.stream.getTracks().forEach((t) => t.stop());
  };
  const reset = () => {
    stop();
    recorder.current = null;
    chunks.current = [];
    setSeconds(0);
    setBlob(null);
    if (url) URL.revokeObjectURL(url);
    setUrl(null);
    setState("idle");
  };
  // The dialog is keyed on the greeting, so a new greeting remounts it with
  // fresh state; on unmount the microphone is released.
  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    const r = recorder.current;
    if (r && r.state !== "inactive") r.stop();
    r?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  const start = async () => {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) { setState("unsupported"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m));
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      r.onstop = () => {
        const b = new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
        setBlob(b);
        setUrl(URL.createObjectURL(b));
        setState("done");
      };
      recorder.current = r;
      r.start(250);
      setSeconds(0);
      setState("recording");
      timer.current = window.setInterval(() => setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) stop();
        return s + 1;
      }), 1000);
    } catch {
      setState("denied");
    }
  };

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
