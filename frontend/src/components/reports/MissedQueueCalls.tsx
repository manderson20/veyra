// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useMemo, useState } from "react";
import { Card, DataTable, EmptyState, SelectField, type Column } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { useApiData } from "@/hooks/useApiData";

interface MissedCall {
  queue_id: string;
  queue: string;
  call_id: string;
  caller: string;
  entered_at: string;
  ended_at: string;
  ended: string;
  wait_seconds: number | null;
  position: number | null;
  agents_rung: { agent: string; times: number; seconds: number }[];
}

const PERIODS: Record<string, number> = { "1": 1, "7": 7, "30": 30 };

/** Q-Xact missed-call detail (issue #392): queue calls nobody answered,
 * with the agents whose phones rang. */
export function MissedQueueCalls() {
  const [days, setDays] = useState("1");
  const { from, to } = useMemo(() => {
    const end = new Date();
    const start = new Date(end.getTime() - (PERIODS[days] ?? 1) * 86_400_000);
    return { from: start.toISOString(), to: end.toISOString() };
  }, [days]);
  const data = useApiData<{ calls: MissedCall[] }>("/reports/queues/missed", { from, to });
  const columns: Column<MissedCall>[] = [
    { key: "when", header: "Came in", render: (c) => <span className="table__primary">{formatDateTime(c.entered_at)}</span> },
    { key: "queue", header: "Queue", render: (c) => c.queue },
    { key: "caller", header: "Caller", render: (c) => c.caller || <span className="subtle">unknown</span> },
    { key: "wait", header: "Waited", render: (c) => (c.wait_seconds === null ? "—" : `${Math.floor(c.wait_seconds / 60)}:${String(c.wait_seconds % 60).padStart(2, "0")}`) },
    { key: "ended", header: "Ended", render: (c) => c.ended + (c.position ? ` (position ${c.position})` : "") },
    {
      key: "agents", header: "Rang without an answer", render: (c) => c.agents_rung.length
        ? c.agents_rung.map((a) => `${a.agent}${a.times > 1 ? ` ×${a.times}` : ""}`).join(", ")
        : <span className="subtle">nobody</span>,
    },
  ];
  return (
    <Card title="Missed queue calls" subtitle="Each queue call nobody answered: the caller, how long they waited, how the call ended, and the agents whose phones rang without an answer. The newest 500 are shown." flush
      actions={<a className="btn btn--secondary btn--sm" href={`/api/v1/reports/queues/queue_log?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`} download>Queue log for QueueMetrics</a>}>
      <div className="table-toolbar">
        <SelectField label="Period" value={days} onChange={(e) => setDays(e.target.value)}
          options={[{ value: "1", label: "Last 24 hours" }, { value: "7", label: "Last 7 days" }, { value: "30", label: "Last 30 days" }]} />
      </div>
      <DataTable columns={columns} rows={data.data?.calls} rowKey={(c) => `${c.queue_id}:${c.call_id}`} loading={data.loading} error={data.error} onRetry={data.reload} caption="Missed queue calls"
        empty={<EmptyState compact icon="activity" title="No missed queue calls in this period" />} />
    </Card>
  );
}
