// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

/* The fixed overview of Telephony → Reports (docs/REPORTING.md §5.1). */

import { useState } from "react";
import { clock } from "@/components/calls/format";
import { MetricCard } from "@/components/common/Metric";
import { HourGrid, StackedBars } from "@/components/reports/Charts";
import { Button, Card, DataTable, EmptyState, ErrorState, LoadingState, SelectField, TextField, type Column } from "@/components/ui";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";


interface CallsReport {
  timezone: string;
  totals: {
    calls: number;
    answered: number;
    missed: number;
    voicemail: number;
    avg_ring_seconds: number;
    avg_talk_seconds: number;
    inbound: number;
    inbound_answered_within_sl: number;
    service_level_seconds: number;
  };
  by_day: { day: string; inbound: number; outbound: number; internal: number; answered: number; missed: number; total: number }[];
  heatmap: number[][];
  extensions: { extension_id: string; number: string; display_name: string; answered: number; talk_seconds: number; missed: number }[];
  trunks: { trunk_id: string; name: string; inbound: number; outbound: number; talk_seconds: number; peak_calls?: number }[];
  peak_external_calls: number;
}

interface QueueRow {
  queue_id: string;
  number: string;
  name: string;
  offered: number;
  answered: number;
  abandoned: number;
  timed_out: number;
  avg_wait_seconds: number;
  answered_within_sl: number;
  service_level_seconds: number;
  /** Callers who left through the break-out menu (#135). */
  left_with_key?: number;
  agents: { agent: string; answered: number; logged_in_seconds?: number | null; paused_seconds?: number | null }[];
}

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 365 days" },
  { value: "custom", label: "Custom range" },
];
const DIRECTIONS = [
  { key: "inbound", label: "Inbound", color: "var(--viz-1)" },
  { key: "outbound", label: "Outbound", color: "var(--viz-2)" },
  { key: "internal", label: "Internal", color: "var(--viz-3)" },
];

const pct = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : "—");
const dayLabel = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", weekday: "short" });

export function ReportsOverview() {
  const { organizations } = useOrganizationOptions(true);
  const [org, setOrg] = useState("");
  const [period, setPeriod] = useState("7");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [anchor, setAnchor] = useState(() => Date.now());
  const range = period === "custom"
    ? { from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined, to: to ? new Date(`${to}T23:59:59`).toISOString() : undefined }
    : { from: new Date(anchor - Number(period) * 86_400_000).toISOString(), to: new Date(anchor).toISOString() };
  const query = { ...range, organization_id: org || undefined };
  const calls = useApiData<CallsReport>("/reports/calls", query);
  const queues = useApiData<{ queues: QueueRow[] }>("/reports/queues", query);
  const r = calls.data;

  const extColumns: Column<CallsReport["extensions"][number]>[] = [
    { key: "ext", header: "Extension", render: (e) => <><span>{e.display_name}</span> <span className="subtle mono">{e.number}</span></> },
    { key: "answered", header: "Answered", render: (e) => e.answered },
    { key: "missed", header: "Missed", render: (e) => e.missed },
    { key: "talk", header: "Talk time", render: (e) => <span className="mono">{clock(e.talk_seconds)}</span> },
  ];
  const trunkColumns: Column<CallsReport["trunks"][number]>[] = [
    { key: "name", header: "Trunk", render: (t) => t.name },
    { key: "in", header: "Inbound", render: (t) => t.inbound },
    { key: "out", header: "Outbound", render: (t) => t.outbound },
    { key: "talk", header: "Talk time", render: (t) => <span className="mono">{clock(t.talk_seconds)}</span> },
    { key: "peak", header: "Most at once", render: (t) => <span title="The most calls up at the same time on this trunk in the period: compare with the carrier's channel limit">{t.peak_calls ?? "—"}</span> },
  ];
  const queueColumns: Column<QueueRow>[] = [
    { key: "q", header: "Queue", render: (q) => <><span>{q.name}</span> <span className="subtle mono">{q.number}</span></> },
    { key: "offered", header: "Callers", render: (q) => q.offered },
    { key: "answered", header: "Answered", render: (q) => q.answered },
    { key: "abandoned", header: "Hung up waiting", render: (q) => q.abandoned + q.timed_out },
    { key: "wait", header: "Average wait", render: (q) => <span className="mono">{clock(q.avg_wait_seconds)}</span> },
    { key: "sl", header: "Answered within 20 s", render: (q) => pct(q.answered_within_sl, q.offered) },
    { key: "menu", header: "Left by the menu", render: (q) => q.left_with_key ?? 0 },
    {
      key: "agents", header: "Agents", render: (q) => q.agents.length ? (
        <ul className="list-plain" style={{ margin: 0 }}>
          {q.agents.map((a) => (
            <li key={a.agent}>
              {a.agent}: {a.answered} answered
              {a.logged_in_seconds != null ? <span className="subtle"> · logged in {clock(a.logged_in_seconds)}{a.paused_seconds ? `, paused ${clock(a.paused_seconds)}` : ""}</span> : null}
            </li>
          ))}
        </ul>
      ) : "—",
    },
  ];

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <p className="subtle" style={{ margin: 0 }}>{r ? `Days and hours in ${r.timezone}.` : ""}</p>
        <Button icon="refresh" onClick={() => setAnchor(Date.now())} loading={calls.loading && !!calls.data}>Refresh</Button>
      </div>
      <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <div style={{ minWidth: 170 }}>
          <SelectField label="Period" value={period} options={PERIODS} onChange={(e) => setPeriod(e.target.value)} />
        </div>
        {period === "custom" ? (
          <>
            <TextField label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            <TextField label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </>
        ) : null}
        {organizations.length > 1 ? (
          <div style={{ minWidth: 200 }}>
            <SelectField label="Organization" value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
          </div>
        ) : null}
      </div>
      {calls.error ? <ErrorState error={calls.error} onRetry={calls.reload} title="Could not load the report" /> : !r ? <LoadingState /> : (
        <>
          <div className="grid grid--4">
            <MetricCard icon="phone" label="Calls" value={r.totals.calls} hint={`${r.totals.answered} answered`} />
            <MetricCard icon="alert" label="Missed" value={r.totals.missed} hint={`${r.totals.voicemail} went to voicemail`} />
            <MetricCard icon="clock" label="Average ring / talk" value={`${clock(r.totals.avg_ring_seconds)} / ${clock(r.totals.avg_talk_seconds)}`} />
            <MetricCard icon="arrowIn" label={`Inbound answered within ${r.totals.service_level_seconds} s`} value={pct(r.totals.inbound_answered_within_sl, r.totals.inbound)}
              hint={`${r.totals.inbound} inbound · peak ${r.peak_external_calls} outside calls at once`} />
          </div>
          {r.totals.calls === 0 ? (
            <Card><EmptyState icon="history" title="No calls in this period" compact>Reports fill in as calls are made.</EmptyState></Card>
          ) : (
            <div className="grid grid--2" style={{ alignItems: "start" }}>
              <Card title="Calls per day" subtitle="By direction">
                <StackedBars data={r.by_day} series={DIRECTIONS} xKey="day" xLabel={dayLabel} caption="Calls per day by direction" unit=" per day" />
              </Card>
              <Card title="Busiest hours" subtitle="Calls by weekday and hour">
                <HourGrid grid={r.heatmap} caption="Calls by weekday and hour" />
              </Card>
            </div>
          )}
          <div className="grid grid--2" style={{ alignItems: "start" }}>
            <Card title="Extensions" subtitle="Answered, missed (including voicemail) and talk time" flush>
              <DataTable columns={extColumns} rows={r.extensions} rowKey={(e) => e.extension_id} caption="Extensions"
                empty={<EmptyState icon="phone" title="No answered or missed calls" compact />} />
            </Card>
            <Card title="Trunks" subtitle="Calls through each carrier connection" flush>
              <DataTable columns={trunkColumns} rows={r.trunks} rowKey={(t) => t.trunk_id} caption="Trunks"
                empty={<EmptyState icon="trunk" title="No calls through trunks" compact />} />
            </Card>
          </div>
        </>
      )}
      <Card title="Queues" subtitle="Callers waiting for agents" flush>
        <DataTable columns={queueColumns} rows={queues.data?.queues} rowKey={(q) => q.queue_id} loading={queues.loading} error={queues.error} onRetry={queues.reload}
          caption="Queues" empty={<EmptyState icon="queue" title="No queues" compact />} />
      </Card>
    </div>
  );
}
