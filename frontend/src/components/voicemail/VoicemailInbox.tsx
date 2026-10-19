// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Callout, Dialog, EmptyState, Icon, SelectField, Tabs, useToast } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatDateTime, formatDuration, formatRelative } from "@/lib/format";
import type { VoicemailMessage, VoicemailMessages } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface ForwardTarget { id: string; label: string }

/**
 * The messages of one voicemail box (docs/USER_PORTAL.md §2): folders with
 * counts, playback, download, move, forward and delete. `base` is
 * `/me/voicemail/<id>` for the user's own box or `/voicemail/<id>` for an
 * administrator; the same routes exist under both.
 */
export function VoicemailInbox({ base, targets, editable = true, refreshSeconds = 15 }: {
  base: string;
  /** Boxes a message may be forwarded to (the box itself is filtered out). */
  targets: ForwardTarget[];
  editable?: boolean;
  refreshSeconds?: number;
}) {
  const toast = useToast();
  const [folder, setFolder] = useState("INBOX");
  const list = useApiData<VoicemailMessages>(`${base}/messages`, { folder });
  const [playing, setPlaying] = useState<VoicemailMessage | null>(null);
  const [moving, setMoving] = useState<VoicemailMessage | null>(null);
  const [forwarding, setForwarding] = useState<VoicemailMessage | null>(null);
  const [deleting, setDeleting] = useState<VoicemailMessage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reload = list.reload;

  // Counts move when a phone leaves or plays a message: refresh while shown.
  useEffect(() => {
    if (!refreshSeconds) return;
    const t = window.setInterval(reload, refreshSeconds * 1000);
    return () => window.clearInterval(t);
  }, [reload, refreshSeconds]);

  const act = async (what: "move" | "forward" | "delete", m: VoicemailMessage, arg?: string) => {
    setBusy(true);
    setError(null);
    try {
      if (what === "move") await api.post(`${base}/messages/${m.number}/move`, { folder: m.folder, to: arg, msg_id: m.msg_id });
      else if (what === "forward") await api.post(`${base}/messages/${m.number}/forward`, { folder: m.folder, box_id: arg, msg_id: m.msg_id });
      else await api.del(`${base}/messages/${m.number}?folder=${encodeURIComponent(m.folder)}&msg_id=${encodeURIComponent(m.msg_id)}`);
      toast.success(what === "move" ? "Message moved" : what === "forward" ? "Message forwarded" : "Message deleted");
      setMoving(null); setForwarding(null); setDeleting(null);
      if (playing?.msg_id === m.msg_id) setPlaying(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (list.error) {
    const code = (list.error as { code?: string } | null)?.code;
    return (
      <Callout tone={code === "vmstore_unavailable" ? "warn" : "danger"} title={code === "vmstore_unavailable" ? "Messages are not available on this server" : "Could not load the messages"}>
        {errorMessage(list.error)}
      </Callout>
    );
  }
  const data = list.data;
  const tabs = (data?.folders ?? [{ key: "INBOX", label: "New" }]).map((f) => ({
    id: f.key,
    label: `${f.label}${data?.counts[f.key] ? ` (${data.counts[f.key]})` : ""}`,
  }));
  return (
    <div className="stack stack--sm">
      <Tabs tabs={tabs} active={folder} onChange={setFolder} idBase={`vm-${base.replace(/[^a-z0-9]/gi, "")}`} />
      {error ? <Callout tone="danger">{error}</Callout> : null}
      {!data ? <p className="subtle">Loading…</p> : data.messages.length === 0 ? (
        <EmptyState icon="voicemail" title={folder === "INBOX" ? "No new messages" : "This folder is empty"}>
          {folder === "INBOX" ? "New messages appear here as soon as they are left." : "Messages you move here stay until you delete them."}
        </EmptyState>
      ) : (
        <ul className="list-plain">
          {data.messages.map((m) => (
            <li key={`${m.folder}-${m.msg_id}`} className="list-row" style={{ paddingLeft: 0, paddingRight: 0, alignItems: "flex-start" }}>
              <span style={{ minWidth: 0 }}>
                <span className="table__primary">
                  {m.caller_name || m.caller_number || "Unknown caller"}
                  {m.caller_name && m.caller_number ? <span className="mono subtle"> {m.caller_number}</span> : null}
                  {m.urgent ? <> <Badge tone="warn">Urgent</Badge></> : null}
                </span>
                <span className="table__secondary" style={{ display: "block" }}>
                  {m.received_at ? `${formatRelative(m.received_at)} · ${formatDateTime(m.received_at)}` : "Date unknown"} · {formatDuration(m.duration_seconds)}
                </span>
                {playing?.msg_id === m.msg_id ? (
                  <MessagePlayer src={`${API_BASE}${base}/messages/${m.number}/audio?folder=${encodeURIComponent(m.folder)}`} />
                ) : null}
              </span>
              <span className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
                <Button size="sm" icon={playing?.msg_id === m.msg_id ? "stop" : "play"} onClick={() => setPlaying(playing?.msg_id === m.msg_id ? null : m)}>
                  {playing?.msg_id === m.msg_id ? "Close" : "Play"}
                </Button>
                <a className={buttonClass("secondary", "sm")} href={`${API_BASE}${base}/messages/${m.number}/audio?folder=${encodeURIComponent(m.folder)}&download=true`} download>
                  <Icon name="download" size={14} /> Download
                </a>
                {editable ? (
                  <>
                    <Button size="sm" onClick={() => { setError(null); setMoving(m); }}>Move</Button>
                    {targets.length ? <Button size="sm" onClick={() => { setError(null); setForwarding(m); }}>Forward</Button> : null}
                    <Button size="sm" variant="danger" icon="trash" onClick={() => { setError(null); setDeleting(m); }}>Delete</Button>
                  </>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      <MoveDialog message={moving} folders={data?.folders ?? []} busy={busy} error={error} onClose={() => setMoving(null)} onMove={(to) => moving && act("move", moving, to)} />
      <ForwardDialog message={forwarding} targets={targets} busy={busy} error={error} onClose={() => setForwarding(null)} onForward={(id) => forwarding && act("forward", forwarding, id)} />
      <Dialog open={deleting !== null} onClose={() => setDeleting(null)} busy={busy} title="Delete this message?"
        footer={<><Button onClick={() => setDeleting(null)} disabled={busy}>Cancel</Button><Button variant="danger" loading={busy} onClick={() => deleting && act("delete", deleting)}>Delete</Button></>}>
        <p>The message from {deleting?.caller_name || deleting?.caller_number || "an unknown caller"} is removed from the phone system; there is no undo.</p>
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </Dialog>
    </div>
  );
}

function MessagePlayer({ src }: { src: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  useEffect(() => { void ref.current?.play().catch(() => undefined); }, [src]);
  return (
    <audio ref={ref} controls preload="auto" src={src} style={{ width: "100%", marginTop: 6 }}>
      Your browser cannot play this recording; download it instead.
    </audio>
  );
}

function MoveDialog({ message, folders, busy, error, onClose, onMove }: {
  message: VoicemailMessage | null; folders: { key: string; label: string }[]; busy: boolean; error: string | null;
  onClose: () => void; onMove: (to: string) => void;
}) {
  const [to, setTo] = useState("Old");
  const options = folders.filter((f) => f.key !== message?.folder).map((f) => ({ value: f.key, label: f.label }));
  const valid = options.some((o) => o.value === to);
  return (
    <Dialog open={message !== null} onClose={onClose} busy={busy} title="Move the message"
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={() => onMove(to)}>Move</Button></>}>
      <div className="stack stack--sm">
        <SelectField label="To folder" value={valid ? to : (options[0]?.value ?? "")} options={options} onChange={(e) => setTo(e.target.value)} />
        <p className="subtle" style={{ margin: 0 }}>Moving a new message to Old marks it as heard on the phone as well.</p>
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Dialog>
  );
}

function ForwardDialog({ message, targets, busy, error, onClose, onForward }: {
  message: VoicemailMessage | null; targets: ForwardTarget[]; busy: boolean; error: string | null;
  onClose: () => void; onForward: (boxId: string) => void;
}) {
  const [target, setTarget] = useState(targets[0]?.id ?? "");
  const valid = targets.some((t) => t.id === target);
  return (
    <Dialog open={message !== null} onClose={onClose} busy={busy} title="Forward the message"
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={() => onForward(target)}>Forward</Button></>}>
      <div className="stack stack--sm">
        <SelectField label="To voicemail box" value={valid ? target : (targets[0]?.id ?? "")} options={targets.map((t) => ({ value: t.id, label: t.label }))} onChange={(e) => setTarget(e.target.value)} />
        <p className="subtle" style={{ margin: 0 }}>A copy lands in that box as a new message, marked as forwarded by you; your copy stays.</p>
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Dialog>
  );
}
