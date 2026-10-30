// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, PageHeader, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { ActiveCall, ActiveCalls, MyExtension } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useLiveChanges } from "@/hooks/useLiveChanges";
import { useSession } from "@/hooks/useSession";

const REFRESH_MS = 5_000;
// While the live stream is connected (issue #111) the list reloads on each
// call event; polling only catches what the stream cannot see (trunk legs).
const SLOW_REFRESH_MS = 30_000;

const STATE_TONE: Record<string, "ok" | "accent" | "neutral" | "warn"> = {
  Up: "ok",
  Ring: "accent",
  Ringing: "accent",
  Dialing: "accent",
  Down: "neutral",
  Busy: "warn",
};

export default function ActiveCallsPage() {
  const data = useApiData<ActiveCalls>("/calls");
  const reload = data.reload;
  const { can } = useSession();
  const toast = useToast();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [ending, setEnding] = useState<string | null>(null);
  const canHangUp = can("calls.hangup");
  const canRecord = can("calls.record");
  const canMonitor = can("calls.monitor");
  const [monBusy, setMonBusy] = useState<string | null>(null);
  // Which of your phones rings for supervising (several extensions: you choose).
  const myExts = useApiData<MyExtension[]>(canMonitor ? "/me/extensions" : null);
  const usable = (myExts.data ?? []).filter((x) => x.is_enabled);
  const [monitorExt, setMonitorExt] = useState("");
  // Supervisor (issue #167): your phone rings; answering it starts listening.
  const supervise = async (c: ActiveCall, mode: string) => {
    if (!mode) return;
    setMonBusy(c.channel_id);
    try {
      const r = await api.post<{ message: string }>(`/calls/${encodeURIComponent(c.channel_id)}/monitor`, { mode, ...(monitorExt ? { extension_id: monitorExt } : {}) });
      toast.success(r.message, "The session is recorded in the audit log.");
    } catch (err) {
      toast.error("Could not start supervising", errorMessage(err));
    } finally {
      setMonBusy(null);
    }
  };
  const [recBusy, setRecBusy] = useState<string | null>(null);
  const toggleRecord = async (c: ActiveCall) => {
    const on = c.recording;
    setRecBusy(c.channel_id);
    try {
      const r = await api.post<{ message: string }>(`/calls/${encodeURIComponent(c.channel_id)}/record`, { action: on ? "stop" : "start" });
      reload();
      toast.success(r.message, on ? undefined : "It is filed with the call record (Call Recording) when the call ends.");
    } catch (err) {
      toast.error(on ? "Could not stop the recording" : "Could not record", errorMessage(err));
    } finally {
      setRecBusy(null);
    }
  };
  const hangUp = async (c: ActiveCall) => {
    setEnding(c.channel_id);
    try {
      const r = await api.del<{ message: string }>(`/calls/${encodeURIComponent(c.channel_id)}`);
      toast.success("Call ended", r?.message);
      reload();
    } catch (err) {
      toast.error("Could not hang up", errorMessage(err));
    } finally {
      setEnding(null);
      setConfirming(null);
    }
  };
  const live = useLiveChanges(reload);
  useEffect(() => {
    const t = window.setInterval(reload, live ? SLOW_REFRESH_MS : REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reload, live]);

  const columns: Column<ActiveCall>[] = [
    {
      key: "ext",
      header: "Extension",
      render: (c) => c.extension_number ? <span><span className="table__primary mono" style={{ display: "block" }}>{c.extension_number}</span><span className="table__secondary">{c.extension_name}</span></span> : <span className="subtle mono">{c.endpoint ?? "—"}</span>,
    },
    { key: "from", header: "From", render: (c) => <span className="mono">{c.caller ?? "—"}</span> },
    { key: "to", header: "To", render: (c) => <span className="mono">{c.callee ?? "—"}</span> },
    { key: "state", header: "State", render: (c) => <Badge tone={STATE_TONE[c.state] ?? "neutral"}>{c.state}</Badge> },
    { key: "dur", header: "Duration", render: (c) => <span className="nowrap">{formatDuration(c.duration_seconds)}</span> },
    { key: "ch", header: "Channel", render: (c) => <span className="subtle mono">{c.channel_id}</span> },
    ...(canRecord ? [{
      key: "record",
      header: <span className="sr-only">Record</span>,
      render: (c: ActiveCall) => c.recording && !c.recording_stoppable ? <Badge tone="danger" icon="record">Recording</Badge> : (
        <Button size="sm" icon={c.recording ? "stop" : "record"} loading={recBusy === c.channel_id} onClick={() => void toggleRecord(c)}
          aria-label={`${c.recording ? "Stop recording" : "Record"} the call on ${c.extension_number ?? c.endpoint ?? c.channel_id}`}>
          {c.recording ? "Stop recording" : "Record"}
        </Button>
      ),
    }] : []),
    ...(canMonitor ? [{
      key: "monitor",
      header: <span className="sr-only">Supervise</span>,
      render: (c: ActiveCall) => c.extension_number ? (
        <SelectField label={<span className="sr-only">Supervise the call on {c.extension_number}</span>} value="" placeholder="Supervise…" disabled={monBusy === c.channel_id}
          options={[{ value: "listen", label: "Listen" }, { value: "whisper", label: "Whisper to the user" }, { value: "barge", label: "Join the call" }]}
          onChange={(e) => void supervise(c, e.target.value)} />
      ) : null,
    }] : []),
    ...(canHangUp ? [{
      key: "hangup",
      header: <span className="sr-only">Actions</span>,
      render: (c: ActiveCall) => confirming === c.channel_id ? (
        <span className="row nowrap" style={{ gap: 6 }}>
          <Button size="sm" variant="danger" loading={ending === c.channel_id} onClick={() => hangUp(c)}>Hang up</Button>
          <Button size="sm" onClick={() => setConfirming(null)} disabled={ending === c.channel_id}>Keep</Button>
        </span>
      ) : (
        <Button size="sm" icon="phone-off" onClick={() => setConfirming(c.channel_id)} aria-label={`Hang up the call on ${c.extension_number ?? c.endpoint ?? c.channel_id}`}>Hang up</Button>
      ),
    }] : []),
  ];
  const d = data.data;
  return (
    <div className="stack">
      <PageHeader
        title="Active calls"
        description="Channels that are up on the telephony engine right now, refreshed every few seconds. Hang up ends that side of the call; the engine clears the other."
        actions={<Button icon="refresh" onClick={reload} loading={data.loading && !!d}>Refresh</Button>}
      />
      {d && !d.available ? <Callout tone="warn" title="Live call data is not available">{d.message}</Callout> : null}
      {canMonitor && usable.length > 1 ? (
        <div style={{ maxWidth: 360 }}>
          <SelectField label="Supervise from" value={monitorExt} help="The phone that rings when you listen, whisper or join."
            options={[{ value: "", label: `${usable[0]!.number} — ${usable[0]!.display_name} (first)` }, ...usable.slice(1).map((x) => ({ value: x.id, label: `${x.number} — ${x.display_name}` }))]}
            onChange={(e) => setMonitorExt(e.target.value)} />
        </div>
      ) : null}
      <Card flush>
        <DataTable
          columns={columns}
          rows={d?.calls}
          rowKey={(c) => c.channel_id}
          loading={data.loading && !d}
          error={data.error}
          onRetry={reload}
          caption="Active calls"
          empty={<EmptyState icon="activity" title="No calls in progress">Calls appear here while they ring and while they are up.</EmptyState>}
        />
      </Card>
    </div>
  );
}
