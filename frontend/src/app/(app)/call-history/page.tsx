// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  buttonClass,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  Icon,
  PageHeader,
  Pagination,
  SearchInput,
  SelectField,
  TextField,
  type Column,
} from "@/components/ui";
import { clock, DIRECTION, OUTCOME, party } from "@/components/calls/format";
import { API_BASE } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { CallHistoryDetail, CallHistoryItem, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 50;

const RANGES = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "custom", label: "Custom range" },
];

function rangeQuery(range: string, from: string, to: string, anchor: number): { from?: string; to?: string } {
  if (range === "custom") {
    return {
      from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
      to: to ? new Date(`${to}T23:59:59`).toISOString() : undefined,
    };
  }
  return { from: new Date(anchor - Number(range) * 86_400_000).toISOString() };
}

function CallDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useApiData<CallHistoryDetail>(id ? `/calls/history/${id}` : null);
  const c = detail.data;
  return (
    <Dialog open={id !== null} onClose={onClose} variant="drawer" title="Call" description={c ? formatDateTime(c.started_at) : undefined}>
      {c ? (
        <div className="stack">
          <dl className="dl">
            <dt>Direction</dt><dd>{DIRECTION[c.direction].label}{c.trunk_name ? ` · ${c.trunk_name}` : ""}</dd>
            <dt>From</dt><dd>{party(c.from_number, c.from_name, c.from_extension)}</dd>
            <dt>To</dt><dd>{party(c.to_number, null, c.to_extension)}{c.did && c.did !== c.to_number ? <span className="subtle"> · DID {c.did}</span> : null}</dd>
            <dt>Outcome</dt><dd><Badge tone={OUTCOME[c.outcome].tone}>{OUTCOME[c.outcome].label}</Badge>{c.in_progress ? <span className="subtle"> · in progress</span> : null}</dd>
            <dt>Answered by</dt><dd>{c.answered_by ? party(null, null, c.answered_by) : "—"}</dd>
            <dt>Ringing</dt><dd>{clock(c.ring_seconds)}</dd>
            <dt>Talking</dt><dd>{clock(c.talk_seconds)}</dd>
            <dt>Organization</dt><dd>{c.organization_name ?? "—"}</dd>
          </dl>
          <div>
            <p className="field__label" style={{ marginBottom: 6 }}>Legs ({c.legs.length})</p>
            <ol className="list-plain">
              {c.legs.map((l, i) => (
                <li key={i} className="list-row">
                  <span style={{ minWidth: 0 }}>
                    <span className="mono">{l.channel}</span>{l.dstchannel ? <> → <span className="mono">{l.dstchannel}</span></> : null}
                    <span className="subtle" style={{ display: "block" }}>{formatDateTime(l.start)} · {l.lastapp || "—"} · {l.disposition}{l.billsec ? ` · ${clock(l.billsec)}` : ""}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      ) : <p className="subtle">Loading…</p>}
    </Dialog>
  );
}

export default function CallHistoryPage() {
  const { can } = useSession();
  const { organizations } = useOrganizationOptions(true);
  const [range, setRange] = useState("1");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [org, setOrg] = useState("");
  const [direction, setDirection] = useState("");
  const [outcome, setOutcome] = useState("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  // Relative ranges are fixed when the page opens; Refresh moves them to now.
  const [anchor, setAnchor] = useState(() => Date.now());

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const stable = {
    ...rangeQuery(range, from, to, anchor),
    organization_id: org || undefined,
    direction: direction || undefined,
    outcome: outcome || undefined,
    q: debounced || undefined,
  };
  const list = useApiData<Page<CallHistoryItem>>("/calls/history", { ...stable, limit: LIMIT, offset });
  const exportHref = `${API_BASE}/calls/history/export.csv?${new URLSearchParams(
    Object.entries(stable).filter(([, v]) => v !== undefined) as [string, string][],
  ).toString()}`;

  const columns: Column<CallHistoryItem>[] = [
    { key: "when", header: "Time", render: (c) => <span className="nowrap">{formatDateTime(c.started_at)}</span> },
    { key: "dir", header: <span className="sr-only">Direction</span>, render: (c) => <span title={DIRECTION[c.direction].label}><Icon name={DIRECTION[c.direction].icon} label={DIRECTION[c.direction].label} size={16} /></span> },
    { key: "from", header: "From", render: (c) => party(c.from_number, c.from_name, c.from_extension) },
    { key: "to", header: "To", render: (c) => party(c.to_number, null, c.to_extension) },
    { key: "answered", header: "Answered by", render: (c) => (c.answered_by ? party(null, null, c.answered_by) : <span className="subtle">—</span>) },
    { key: "talk", header: "Talk", render: (c) => <span className="mono">{c.talk_seconds ? clock(c.talk_seconds) : "—"}</span> },
    { key: "outcome", header: "Outcome", render: (c) => <><Badge tone={OUTCOME[c.outcome].tone}>{OUTCOME[c.outcome].label}</Badge>{c.recorded ? <> <Icon name="record" label="Recorded" size={14} /></> : null}</> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Call history" description="Every call through the phone system: who called whom, who answered, and how long it lasted."
        actions={<>
          <Button icon="refresh" onClick={() => setAnchor(Date.now())} loading={list.loading && !!list.data}>Refresh</Button>
          {can("calls.history.export") ? <a className={buttonClass("secondary")} href={exportHref} download><Icon name="download" size={16} /> Export CSV</a> : null}
        </>} />
      <Card flush>
        <div className="table-toolbar" style={{ flexWrap: "wrap" }}>
          <SearchInput value={q} onChange={setQ} placeholder="Number, name or extension" label="Search calls" />
          <div style={{ minWidth: 170 }}>
            <SelectField label={<span className="sr-only">Period</span>} value={range} options={RANGES} onChange={(e) => { setRange(e.target.value); setOffset(0); }} />
          </div>
          {range === "custom" ? (
            <>
              <TextField label={<span className="sr-only">From</span>} type="date" value={from} onChange={(e) => { setFrom(e.target.value); setOffset(0); }} />
              <TextField label={<span className="sr-only">To</span>} type="date" value={to} onChange={(e) => { setTo(e.target.value); setOffset(0); }} />
            </>
          ) : null}
          {organizations.length > 1 ? (
            <div style={{ minWidth: 180 }}>
              <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
                options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
            </div>
          ) : null}
          <div style={{ minWidth: 150 }}>
            <SelectField label={<span className="sr-only">Direction</span>} value={direction} placeholder="All directions"
              options={Object.entries(DIRECTION).map(([value, d]) => ({ value, label: d.label }))} onChange={(e) => { setDirection(e.target.value); setOffset(0); }} />
          </div>
          <div style={{ minWidth: 150 }}>
            <SelectField label={<span className="sr-only">Outcome</span>} value={outcome} placeholder="All outcomes"
              options={Object.entries(OUTCOME).map(([value, o]) => ({ value, label: o.label }))} onChange={(e) => { setOutcome(e.target.value); setOffset(0); }} />
          </div>
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(c) => c.id} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Calls" onRowClick={(c) => setSelected(c.id)} rowLabel={(c) => `Call at ${formatDateTime(c.started_at)}`}
          empty={<EmptyState icon="history" title="No calls in this period" compact>Calls appear here within a few seconds of ending.</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <CallDetail id={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
