// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Card, DataTable, EmptyState, TextField, type Column } from "@/components/ui";
import type { UsageRow } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

function lastMonth(): string {
  const d = new Date();
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() - 1);
  return d.toISOString().slice(0, 7);
}

/** Outside calls and minutes per organization and trunk, for billing
 * (docs/MULTI_TENANCY_MSP.md §9). */
export function UsageReport() {
  const [month, setMonth] = useState(lastMonth);
  const data = useApiData<{ month: string; rows: UsageRow[] }>(/^\d{4}-\d{2}$/.test(month) ? "/reports/usage" : null, { month });
  const columns: Column<UsageRow>[] = [
    { key: "org", header: "Organization", render: (r) => <span className="table__primary">{r.organization}</span> },
    { key: "trunk", header: "Trunk", render: (r) => r.trunk || <span className="subtle">Internal calls</span> },
    { key: "in", header: "Inbound", render: (r) => `${r.inbound_calls} · ${r.inbound_minutes} min` },
    { key: "out", header: "Outbound", render: (r) => `${r.outbound_calls} · ${r.outbound_minutes} min` },
    { key: "bill", header: "Billable minutes", render: (r) => <strong>{r.billable_minutes}</strong> },
    { key: "e911", header: "Emergency", render: (r) => r.emergency_calls },
    { key: "internal", header: "Internal", render: (r) => r.internal_calls },
    { key: "peak", header: "Most at once", render: (r) => r.peak_concurrent },
  ];
  return (
    <Card title="Usage by organization" subtitle="Outside calls and their minutes per organization and trunk. Billable minutes round each call up to a whole minute; emergency calls are never billable. Most at once is the organization's peak of outside calls across its trunks." flush
      actions={/^\d{4}-\d{2}$/.test(month) ? <a className="btn btn--secondary btn--sm" href={`/api/v1/reports/usage.csv?month=${month}`} download>Download CSV</a> : null}>
      <div className="table-toolbar">
        <TextField label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
      </div>
      <DataTable columns={columns} rows={data.data?.rows} rowKey={(r) => `${r.organization_id}:${r.trunk}`} loading={data.loading} error={data.error} onRetry={data.reload} caption="Usage"
        empty={<EmptyState compact icon="activity" title="No calls that month" />} />
    </Card>
  );
}
