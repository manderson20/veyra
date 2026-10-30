// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, EmptyState, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";

export interface LiveParticipant { channel: string; caller_id: string; admin: boolean; marked: boolean; muted: boolean }
export interface LiveConferenceState { running: boolean; locked: boolean; recording: boolean; always_recorded: boolean; participants: LiveParticipant[] }

type Action = "mute" | "unmute" | "kick" | "mute_all" | "unmute_all" | "lock" | "unlock" | "end" | "record_start" | "record_stop" | "invite";

/** Who is in a conference room now, with mute, kick, lock, end, recording and
 * invitations (issue #96). Refreshes every 5 s while shown. `base`: the room
 * page's API, or the My Phone one for a room the user owns. */
export function LiveConference({ roomId, editable, base = "/conferences", title: heading = "Live" }: { roomId: string; editable: boolean; base?: string; title?: string }) {
  const toast = useToast();
  const url = `${base}/${encodeURIComponent(roomId)}/live`;
  const live = useApiData<LiveConferenceState>(url);
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);
  const reload = live.reload;
  useEffect(() => {
    const t = window.setInterval(reload, 5000);
    return () => window.clearInterval(t);
  }, [reload]);

  const act = async (action: Action, channel?: string, invite?: string) => {
    setBusy(`${action}:${channel ?? ""}`);
    try {
      const r = await api.post<LiveConferenceState>(url, { action, channel, number: invite });
      live.setData(r);
      setEnding(false);
      if (action === "invite") {
        setNumber("");
        toast.success("Calling", `${invite} joins the room on answering.`);
      }
    } catch (err) {
      toast.error("Not done", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const invite = (e: FormEvent) => {
    e.preventDefault();
    if (number.trim()) void act("invite", undefined, number.trim());
  };

  const s = live.data;
  const count = s?.participants.length ?? 0;
  const title = s?.running ? `${heading}: ${count} participant${count === 1 ? "" : "s"}` : heading;
  return (
    <Card title={title} subtitle={s?.running ? (s.locked ? "Locked: nobody else can join." : "Updates every few seconds.") : undefined}
      footer={editable && s?.running ? (
        <div className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
          <Button size="sm" onClick={() => act("mute_all")} loading={busy === "mute_all:"}>Mute everyone else</Button>
          <Button size="sm" onClick={() => act("unmute_all")} loading={busy === "unmute_all:"}>Unmute all</Button>
          {s.recording && s.always_recorded ? null : <Button size="sm" onClick={() => act(s.recording ? "record_stop" : "record_start")} loading={busy === "record_start:" || busy === "record_stop:"}>{s.recording ? "Stop recording" : "Start recording"}</Button>}
          <Button size="sm" icon="lock" onClick={() => act(s.locked ? "unlock" : "lock")} loading={busy === "lock:" || busy === "unlock:"}>{s.locked ? "Unlock" : "Lock"}</Button>
          <Button size="sm" variant="danger" onClick={() => setEnding(true)}>End</Button>
        </div>
      ) : undefined}>
      {s?.recording ? <p style={{ marginBottom: 8 }}><Badge tone="danger">Recording</Badge></p> : null}
      {live.error ? <Callout tone="warn">{errorMessage(live.error)}</Callout> : !s ? <p className="subtle">Loading…</p> : !s.running ? (
        <EmptyState compact icon="group" title="Nobody is in the room">Participants show here as soon as someone dials in.</EmptyState>
      ) : (
        <ul className="list-plain">
          {s.participants.map((p) => (
            <li key={p.channel} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
              <span style={{ minWidth: 0 }}>
                <span className="table__primary">{p.caller_id || "Unknown"} {p.admin ? <Badge tone="info">Admin</Badge> : null} {p.muted ? <Badge tone="warn">Muted</Badge> : null}</span>
                <span className="table__secondary mono" style={{ display: "block", overflowWrap: "anywhere" }}>{p.channel}</span>
              </span>
              {editable ? (
                <span className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <Button size="sm" icon={p.muted ? "mic" : "pause"} onClick={() => act(p.muted ? "unmute" : "mute", p.channel)} loading={busy === `${p.muted ? "unmute" : "mute"}:${p.channel}`}>{p.muted ? "Unmute" : "Mute"}</Button>
                  <Button size="sm" variant="danger" onClick={() => act("kick", p.channel)} loading={busy === `kick:${p.channel}`}>Remove</Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {editable && s ? (
        <form className="row" style={{ alignItems: "flex-end", marginTop: 12 }} onSubmit={invite}>
          <div style={{ flex: 1, minWidth: 0 }}><TextField label="Invite a number" value={number} onChange={(e) => setNumber(e.target.value)} maxLength={40} inputMode="tel" help="Rings an extension or outside number; they join without the PIN." /></div>
          <Button type="submit" disabled={!number.trim()} loading={busy === "invite:"}>Call</Button>
        </form>
      ) : null}
      <ConfirmDialog open={ending} title="End the conference?" confirmLabel="End for everyone" tone="danger" busy={busy === "end:"} onConfirm={() => act("end")} onCancel={() => setEnding(false)}>
        <p>Everyone in the room is disconnected.</p>
      </ConfirmDialog>
    </Card>
  );
}
