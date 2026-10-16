// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, PageHeader, SearchInput, SelectField, type Column } from "@/components/ui";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { Organization, Page, RegistrationRow, Registrations } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const REFRESH_MS = 10_000;

const STATUS_TONE: Record<string, "ok" | "warn" | "neutral" | "danger"> = {
  Avail: "ok",
  NonQual: "neutral",
  Unknown: "neutral",
  Unavail: "danger",
};

function address(host: string | null, port: number | null) {
  if (!host) return null;
  const h = host.includes(":") ? `[${host}]` : host;
  return port ? `${h}:${port}` : h;
}

export default function RegistrationsPage() {
  const { session } = useSession();
  const [q, setQ] = useState("");
  const [org, setOrg] = useState("");
  const query = { ...(q ? { q } : {}), ...(org ? { organization_id: org } : {}) };
  const data = useApiData<Registrations>("/telephony/registrations", query);
  const orgs = useApiData<Page<Organization>>(session?.is_platform_admin ? "/organizations" : null, { limit: 200 });
  const organizations = orgs.data?.items ?? [];
  const manyOrgs = organizations.length > 1;
  const reload = data.reload;
  useEffect(() => {
    const t = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reload]);

  const columns: Column<RegistrationRow>[] = [
    {
      key: "ext",
      header: "Extension",
      render: (r) => r.extension_number
        ? <span><span className="table__primary mono" style={{ display: "block" }}>{r.extension_number}</span><span className="table__secondary">{r.extension_name}</span></span>
        : <span className="subtle mono">{r.endpoint}</span>,
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (r: RegistrationRow) => <span>{r.organization_name ?? "—"}</span> }] : []),
    {
      key: "source",
      header: "Registers from",
      render: (r) => (
        <span>
          <span className="mono" style={{ display: "block" }}>{address(r.source_host, r.source_port) ?? address(r.contact_host, r.contact_port) ?? "—"}</span>
          {r.nat ? <Badge tone="warn">Behind NAT</Badge> : null}
        </span>
      ),
    },
    {
      key: "contact",
      header: "Phone's own address",
      render: (r) => <span className="mono">{address(r.contact_host, r.contact_port) ?? "—"}{r.transport ? <span className="table__secondary"> {r.transport.toUpperCase()}</span> : null}</span>,
    },
    { key: "ua", header: "Phone reports", render: (r) => <span className="subtle">{r.user_agent ?? "—"}</span> },
    {
      key: "status",
      header: "Reachability",
      render: (r) => (
        <span className="row">
          {r.status ? <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status === "NonQual" ? "Not checked" : r.status === "Avail" ? "Reachable" : r.status === "Unavail" ? "Unreachable" : r.status}</Badge> : <span className="subtle">—</span>}
          {r.rtt_ms !== null ? <span className="table__secondary nowrap">{r.rtt_ms.toFixed(1)} ms</span> : null}
        </span>
      ),
    },
    {
      key: "expires",
      header: "Expires",
      render: (r) => r.expires_at ? <span className="nowrap" title={formatDateTime(r.expires_at)}>{formatRelative(r.expires_at)}</span> : <span className="subtle">—</span>,
    },
  ];
  const d = data.data;
  return (
    <div className="stack">
      <PageHeader
        title="Registrations"
        description="Every phone that is registered right now and where it registers from: the address the registration arrived from and the address the phone itself reports. They differ when the phone is behind NAT."
        actions={<Button icon="refresh" onClick={reload} loading={data.loading && !!d}>Refresh</Button>}
      />
      {d && !d.available ? <Callout tone="warn" title="Registration details are not available">{d.message}</Callout> : null}
      {d && d.available && d.unregistered > 0 ? <Callout tone="info" title={`${d.unregistered} enabled extension${d.unregistered === 1 ? " has" : "s have"} no registered phone`}>They are listed on the Extensions page as “Not registered”.</Callout> : null}
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by extension, address or phone model" label="Search registrations" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={d?.registrations}
          rowKey={(r) => `${r.endpoint}|${r.uri}`}
          loading={data.loading && !d}
          error={data.error}
          onRetry={reload}
          caption="Registered phones"
          empty={<EmptyState icon="device" title="No phone is registered">Registered phones appear here with the address they register from.</EmptyState>}
        />
      </Card>
    </div>
  );
}
