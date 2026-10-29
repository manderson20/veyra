// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, Checkbox, EmptyState, TextArea, TextField, useToast } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { FaxJob } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { MoreRows, useRowLimit, useWidgetSize } from "@/components/portal/WidgetSize";

export const FAX_STATE: Record<string, { tone: "ok" | "neutral" | "danger" | "warn" | "info"; label: string }> = {
  queued: { tone: "neutral", label: "Waiting" },
  dialling: { tone: "info", label: "Dialling" },
  sending: { tone: "info", label: "Sending" },
  sent: { tone: "ok", label: "Sent" },
  failed: { tone: "danger", label: "Failed" },
  received: { tone: "ok", label: "Received" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

export const ACTIVE_FAX_STATES = ["queued", "dialling", "sending"];

export function faxPages(n: number): string {
  return `${n} page${n === 1 ? "" : "s"}`;
}

/** Send a PDF as a fax and follow your faxes (docs/USER_PORTAL.md §9). */
export function FaxCard() {
  const toast = useToast();
  const jobs = useApiData<FaxJob[]>("/me/fax");
  const [number, setNumber] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [cover, setCover] = useState(false);
  const [to, setTo] = useState("");
  const [from, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const size = useWidgetSize();
  const [composing, setComposing] = useState(false);
  const showForm = !size.compact || composing;
  const rows = useRowLimit(jobs.data?.length ?? 0, showForm ? 260 : 40);

  // While one of the faxes is on its way, the list follows it.
  const active = (jobs.data ?? []).some((j) => ACTIVE_FAX_STATES.includes(j.state));
  const reload = jobs.reload;
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(reload, 10000);
    return () => window.clearInterval(t);
  }, [active, reload]);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("number", number.trim());
      form.append("file", file);
      form.append("cover", cover ? "true" : "false");
      if (cover) {
        form.append("cover_to", to);
        if (from.trim()) form.append("cover_from", from.trim());
        form.append("cover_subject", subject);
        form.append("cover_note", note);
      }
      const job = await api.upload<FaxJob>("/me/fax", form);
      toast.success(`Fax to ${job.number} queued`, `${faxPages(job.pages)}; you will be emailed when it is delivered.`);
      setNumber("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setCover(false);
      setTo("");
      setSubject("");
      setNote("");
      setComposing(false);
      jobs.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const act = async (j: FaxJob, what: "cancel" | "retry") => {
    try {
      await api.post(`/me/fax/${j.id}/${what}`);
      jobs.reload();
    } catch (err) {
      toast.error(what === "cancel" ? "Could not cancel the fax" : "Could not retry the fax", errorMessage(err));
    }
  };

  return (
    <Card title="Fax">
      <div className="stack stack--sm">
        {!showForm ? <div><Button variant="primary" onClick={() => setComposing(true)}>Send a fax</Button></div> : null}
        {showForm ? <form className="stack stack--sm" onSubmit={send}>
          <TextField label="Fax number" required inputMode="tel" value={number} placeholder="(573) 555-0100" disabled={busy}
            onChange={(e) => setNumber(e.target.value)} />
          <div className="field">
            <label className="field__label" htmlFor="fax-file">PDF to send</label>
            <input id="fax-file" ref={fileRef} type="file" accept="application/pdf,.pdf" required disabled={busy}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="field__help">Up to 20 MB and 50 pages. Sent with your extension&apos;s caller ID.</p>
          </div>
          <Checkbox label="Add a cover sheet" checked={cover} disabled={busy} onChange={(e) => setCover(e.target.checked)} />
          {cover ? (
            <div className="stack stack--sm">
              <div className="grid grid--2">
                <TextField label="To" value={to} maxLength={120} disabled={busy} onChange={(e) => setTo(e.target.value)} />
                <TextField label="From" value={from} maxLength={120} disabled={busy} placeholder="Your name" help="Empty: your name." onChange={(e) => setFrom(e.target.value)} />
                <TextField label="Subject" value={subject} maxLength={120} disabled={busy} onChange={(e) => setSubject(e.target.value)} />
              </div>
              <TextArea label="Note" rows={3} value={note} maxLength={2000} disabled={busy} onChange={(e) => setNote(e.target.value)} />
            </div>
          ) : null}
          {error ? <Callout tone="danger">{error}</Callout> : null}
          <div>
            <Button variant="primary" type="submit" loading={busy} disabled={!file || !number.trim()}>Send fax</Button>
            {size.compact ? <Button onClick={() => setComposing(false)} disabled={busy}>Close</Button> : null}
          </div>
        </form> : null}
        <h3 className="card__title">Your faxes</h3>
        {jobs.error ? (
          <Callout tone="danger">{errorMessage(jobs.error)}</Callout>
        ) : !jobs.data ? (
          <p className="subtle">Loading…</p>
        ) : jobs.data.length === 0 ? (
          <EmptyState compact icon="history" title="No faxes yet">Faxes you send appear here with their state; you are emailed when one is delivered or fails.</EmptyState>
        ) : (
          <ul className="stack stack--sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {jobs.data.slice(0, rows.limit).map((j) => (
              <li key={j.id} className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
                <span style={{ minWidth: 0 }}>
                  <span className="table__primary" style={{ display: "block" }}>
                    {j.direction === "out" ? "To" : "From"} {j.number}{j.original_name ? ` · ${j.original_name}` : ""}
                  </span>
                  <span className="table__secondary">
                    {formatRelative(j.created_at)} · {faxPages(j.pages)}
                    {j.attempts > 1 ? ` · attempt ${j.attempts}` : ""}
                    {j.next_attempt_at && j.state === "queued" && j.attempts > 0 ? ` · next try ${formatRelative(j.next_attempt_at)}` : ""}
                    {j.error ? ` · ${j.error}` : ""}
                  </span>
                </span>
                <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <Badge tone={FAX_STATE[j.state]?.tone ?? "neutral"}>{FAX_STATE[j.state]?.label ?? j.state}</Badge>
                  {j.has_file ? <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/me/fax/${j.id}/file`} download>PDF</a> : null}
                  {ACTIVE_FAX_STATES.includes(j.state) ? <Button size="sm" onClick={() => act(j, "cancel")}>Cancel</Button> : null}
                  {["failed", "cancelled"].includes(j.state) && j.direction === "out" ? <Button size="sm" onClick={() => act(j, "retry")}>Retry</Button> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
        <MoreRows {...rows} />
      </div>
    </Card>
  );
}
