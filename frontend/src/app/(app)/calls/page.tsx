// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, PageHeader, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { ActiveCall, ActiveCalls } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const REFRESH_MS = 5_000;

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
  useEffect(() => {
    const t = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reload]);

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
