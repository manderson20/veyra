// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Card, Checkbox, DataTable, EmptyState, PageHeader, Pagination, SelectField, TextField, type Column } from "@/components/ui";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { formatDateTime } from "@/lib/format";
import type { Page } from "@/lib/types";

interface ProvisioningRequestItem {
  id: string;
  at: string;
  mac_address: string | null;
  mac_display: string | null;
  filename: string;
  method: string;
  ip_address: string | null;
  user_agent: string | null;
  organization_id: string | null;
  organization_name: string | null;
  device_id: string | null;
  result: string;
  status: number;
}

const LIMIT = 50;

/** What each result means to someone whose phone will not configure itself. */
const RESULTS: Record<string, { label: string; tone: "ok" | "warn" | "danger" | "neutral"; reason: string }> = {
  ok: { label: "Sent", tone: "ok", reason: "The phone received this file." },
  uploaded: { label: "Uploaded", tone: "ok", reason: "The phone uploaded this file." },
  bootstrap: { label: "First contact", tone: "ok", reason: "The phone received its first-contact settings and should now come back over HTTPS." },
  unauthorized: { label: "Wrong sign-in", tone: "danger", reason: "The phone sent no credential or a wrong one. Check its provisioning server address and credential." },
  unknown_device: { label: "Unknown phone", tone: "warn", reason: "No device has this MAC address. Add the phone under Devices." },
  disabled: { label: "Disabled", tone: "warn", reason: "The device is disabled in Veyra." },
  not_found: { label: "No such file", tone: "neutral", reason: "Veyra has no such file for this phone. Phones often ask for optional files, so this alone is usually harmless." },
  render_error: { label: "Template error", tone: "danger", reason: "The phone's template could not be rendered. Check its template and profile." },
  bootstrap_network: { label: "Wrong network", tone: "danger", reason: "First contact is only allowed from the networks set for it, and this address is outside them." },
  bootstrap_only: { label: "Not offered", tone: "neutral", reason: "Over plain HTTP, only a phone's first-contact file is offered." },
  bootstrap_refused: { label: "Bootstrap refused", tone: "warn", reason: "This phone already provisioned over HTTPS. Use Allow bootstrap again on the device if it was reset." },
  no_ca: { label: "No certificate", tone: "danger", reason: "Veyra has no certificate authority to give the phone yet." },
};

const RESULT_OPTIONS = [{ value: "", label: "All" }, ...Object.entries(RESULTS).map(([value, r]) => ({ value, label: r.label }))];

/** Every configuration request from phones, refused ones too (issue #347). */
export default function ProvisioningRequestsPage() {
  const { organizations } = useOrganizationOptions();
  const [offset, setOffset] = useState(0);
  const [org, setOrg] = useState("");
  const [result, setResult] = useState("");
  const [problems, setProblems] = useState(false);
  const [q, setQ] = useState("");
  const list = useApiData<Page<ProvisioningRequestItem>>("/devices/requests", {
    limit: LIMIT, offset, organization_id: org || undefined, result: result || undefined, problems_only: problems || undefined, q: q.trim() || undefined,
  });
  const columns: Column<ProvisioningRequestItem>[] = [
    { key: "at", header: "Time", render: (r) => <span className="nowrap">{formatDateTime(r.at)}</span> },
    { key: "phone", header: "Phone", render: (r) => <><span className="table__primary mono">{r.mac_display ?? "—"}</span><span className="table__secondary mono" style={{ display: "block" }}>{r.ip_address ?? ""}</span></> },
    { key: "file", header: "File", render: (r) => <span className="mono" style={{ overflowWrap: "anywhere" }}>{r.method !== "GET" ? `${r.method} ` : ""}{r.filename}</span> },
    { key: "result", header: "Result", render: (r) => {
      const known = RESULTS[r.result];
      return <><Badge tone={known?.tone ?? "neutral"}>{known?.label ?? r.result}</Badge> <span className="subtle mono">{r.status}</span>{known ? <span className="table__secondary" style={{ display: "block" }}>{known.reason}</span> : null}</>;
    } },
    { key: "ua", header: "Phone software", render: (r) => <span className="subtle" style={{ overflowWrap: "anywhere" }}>{r.user_agent ?? "—"}</span> },
  ];
  return (
    <>
      <PageHeader title="Provisioning requests" description="What phones asked for and what they got. Start here when a new phone does not pick up its configuration." />
      <Card flush>
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end", padding: "var(--space-3) var(--space-4)" }}>
          {organizations.length > 1 ? <SelectField label="Organization" value={org} options={[{ value: "", label: "All" }, ...organizations.map((o) => ({ value: o.id, label: o.name }))]} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
          <TextField label="MAC, address or file" value={q} maxLength={100} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
          <SelectField label="Result" value={result} options={RESULT_OPTIONS} onChange={(e) => { setResult(e.target.value); setOffset(0); }} />
          <Checkbox label="Problems only" checked={problems} onChange={(e) => { setProblems(e.target.checked); setOffset(0); }} />
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(r) => r.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Provisioning requests"
          empty={<EmptyState icon="device" title="No requests" compact>Nothing matches, or no phone has asked for its configuration. If a phone should have, it is not reaching this server: check its provisioning server address.</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
    </>
  );
}
