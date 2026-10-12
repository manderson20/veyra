// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { OUTCOME } from "@/components/common/labels";
import {
  Badge,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  PageHeader,
  Pagination,
  SearchInput,
  SelectField,
  type Column,
} from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const LIMIT = 50;

export default function AuditPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [outcome, setOutcome] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<AuditEvent>>("/audit", { q: debounced, outcome, limit: LIMIT, offset });
  const columns: Column<AuditEvent>[] = [
    { key: "when", header: "Time", render: (e) => <span className="nowrap">{formatDateTime(e.occurred_at)}</span> },
    { key: "action", header: "Action", render: (e) => <span className="mono">{e.action}</span> },
    { key: "actor", header: "Actor", render: (e) => e.actor_label },
    { key: "target", header: "Target", render: (e) => (e.target_type ? <span className="subtle">{e.target_type}{e.target_id ? ` · ${e.target_id.slice(0, 12)}` : ""}</span> : "—") },
    { key: "outcome", header: "Outcome", render: (e) => <Badge tone={OUTCOME[e.outcome] ?? "neutral"}>{e.outcome}</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Audit log" description="An append-only record of administrative actions, sign-ins and denied attempts." />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search action or actor" label="Search audit log" />
          <div style={{ minWidth: 200 }}>
            <SelectField label={<span className="sr-only">Outcome</span>} value={outcome} placeholder="All outcomes"
              options={[{ value: "success", label: "Success" }, { value: "failure", label: "Failure" }, { value: "denied", label: "Denied" }]}
              onChange={(e) => { setOutcome(e.target.value); setOffset(0); }} />
          </div>
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(e) => String(e.id)} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Audit events" onRowClick={setSelected} rowLabel={(e) => `Details for ${e.action}`}
          empty={<EmptyState icon="audit" title="No matching events" />}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <Dialog open={selected !== null} onClose={() => setSelected(null)} variant="drawer" title="Audit event" description={selected?.action}>
        {selected ? (
          <>
            <dl className="dl">
              <dt>Time</dt><dd>{formatDateTime(selected.occurred_at)}</dd>
              <dt>Outcome</dt><dd><Badge tone={OUTCOME[selected.outcome] ?? "neutral"}>{selected.outcome}</Badge></dd>
              <dt>Actor</dt><dd>{selected.actor_label} <span className="subtle">({selected.actor_type})</span></dd>
              <dt>Target</dt><dd>{selected.target_type ?? "—"} <span className="mono">{selected.target_id ?? ""}</span></dd>
              <dt>Organization</dt><dd className="mono">{selected.organization_id ?? "—"}</dd>
              <dt>IP address</dt><dd className="mono">{selected.ip_address ?? "—"}</dd>
              <dt>Request ID</dt><dd className="mono">{selected.request_id ?? "—"}</dd>
            </dl>
            <div>
              <p className="field__label" style={{ marginBottom: 6 }}>Details</p>
              <pre className="code">{JSON.stringify(selected.details, null, 2)}</pre>
            </div>
          </>
        ) : null}
      </Dialog>
    </div>
  );
}
