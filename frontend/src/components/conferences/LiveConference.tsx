// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, EmptyState, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";

export interface LiveParticipant { channel: string; caller_id: string; admin: boolean; marked: boolean; muted: boolean }
export interface LiveConferenceState { running: boolean; locked: boolean; participants: LiveParticipant[] }

type Action = "mute" | "unmute" | "kick" | "mute_all" | "unmute_all" | "lock" | "unlock" | "end";

/** Who is in a conference room now, with mute, kick, lock and end
 * (issue #96). Refreshes every 5 s while shown. */
export function LiveConference({ roomId, editable }: { roomId: string; editable: boolean }) {
  const toast = useToast();
  const live = useApiData<LiveConferenceState>(`/conferences/${encodeURIComponent(roomId)}/live`);
  const [busy, setBusy] = useState<string | null>(null);
  const [ending, setEnding] = useState(false);
  const reload = live.reload;
  useEffect(() => {
    const t = window.setInterval(reload, 5000);
    return () => window.clearInterval(t);
  }, [reload]);

  const act = async (action: Action, channel?: string) => {
    setBusy(`${action}:${channel ?? ""}`);
    try {
      const r = await api.post<LiveConferenceState>(`/conferences/${encodeURIComponent(roomId)}/live`, { action, channel });
      live.setData(r);
      setEnding(false);
    } catch (err) {
      toast.error("Not done", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const s = live.data;
  const count = s?.participants.length ?? 0;
  const title = s?.running ? `Live: ${count} participant${count === 1 ? "" : "s"}` : "Live";
  return (
    <Card title={title} subtitle={s?.running ? (s.locked ? "Locked: nobody else can join." : "Updates every few seconds.") : undefined}
      footer={editable && s?.running ? (
        <div className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
          <Button size="sm" onClick={() => act("mute_all")} loading={busy === "mute_all:"}>Mute everyone else</Button>
          <Button size="sm" onClick={() => act("unmute_all")} loading={busy === "unmute_all:"}>Unmute all</Button>
          <Button size="sm" icon="lock" onClick={() => act(s.locked ? "unlock" : "lock")} loading={busy === "lock:" || busy === "unlock:"}>{s.locked ? "Unlock" : "Lock"}</Button>
          <Button size="sm" variant="danger" onClick={() => setEnding(true)}>End</Button>
        </div>
      ) : undefined}>
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
      <ConfirmDialog open={ending} title="End the conference?" confirmLabel="End for everyone" tone="danger" busy={busy === "end:"} onConfirm={() => act("end")} onCancel={() => setEnding(false)}>
        <p>Everyone in the room is disconnected.</p>
      </ConfirmDialog>
    </Card>
  );
}
