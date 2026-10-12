// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, PageHeader, type Column } from "@/components/ui";
import { formatDuration } from "@/lib/format";
import type { ActiveCall, ActiveCalls } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

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
  ];
  const d = data.data;
  return (
    <div className="stack">
      <PageHeader
        title="Active calls"
        description="Channels that are up on the telephony engine right now, refreshed every few seconds. Call history arrives in Milestone 10."
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
