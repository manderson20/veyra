// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DeviceDialog } from "@/components/devices/DeviceDialog";
import { Badge, Button, Card, DataTable, EmptyState, LoadingState, PageHeader, Pagination, SearchInput, SelectField, type Column } from "@/components/ui";
import { formatRelative } from "@/lib/format";
import type { Device, DeviceProfile, DeviceStatus, Page, UnregisteredDevice } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;
export const DEVICE_STATUS: Record<DeviceStatus, { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  never: { label: "Never provisioned", tone: "neutral" },
  provisioned: { label: "Provisioned", tone: "ok" },
  stale: { label: "Not seen lately", tone: "warn" },
  error: { label: "Error", tone: "danger" },
};

function DevicesList() {
  const router = useRouter();
  const params = useSearchParams();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [profile, setProfile] = useState(params.get("profile") ?? "");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [seen, setSeen] = useState<UnregisteredDevice | undefined>();

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Device>>("/devices", { q: debounced, organization_id: org || undefined, profile_id: profile || undefined, limit: LIMIT, offset });
  const unregistered = useApiData<UnregisteredDevice[]>("/devices/unregistered");
  const profiles = useApiData<Page<DeviceProfile>>("/device-profiles", { organization_id: org || undefined, limit: 200 });
  const editable = can("devices.write");
  const manyOrgs = organizations.length > 1;
  const reload = () => { list.reload(); unregistered.reload(); };
  const columns: Column<Device>[] = [
    { key: "phone", header: "Phone", render: (d) => <span><span className="table__primary" style={{ display: "block" }}>{d.label ?? d.mac_display}</span><span className="table__secondary mono">{d.mac_display}</span></span> },
    { key: "model", header: "Model", render: (d) => <span>{d.manufacturer} {d.model}</span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (d: Device) => <span>{d.organization_name}</span> }] : []),
    { key: "ext", header: "Extension", render: (d) => d.extension ? <span><span className="mono">{d.extension.number}</span> {d.extension.display_name}{d.lines.length ? <span className="subtle"> +{d.lines.length}</span> : null}</span> : <span className="subtle">None</span> },
    { key: "profile", header: "Profile", render: (d) => d.profile_name ?? <span className="subtle">None</span> },
    { key: "status", header: "Status", render: (d) => <span><Badge tone={DEVICE_STATUS[d.status].tone}>{DEVICE_STATUS[d.status].label}</Badge>{d.last_seen_at ? <span className="table__secondary" style={{ display: "block" }}>{formatRelative(d.last_seen_at)}</span> : null}</span> },
    { key: "problems", header: "", render: (d) => d.problems.length ? <Badge tone="warn" icon="alert">{d.problems[0]}</Badge> : null },
  ];
  const seenColumns: Column<UnregisteredDevice>[] = [
    { key: "mac", header: "MAC address", render: (u) => <span className="mono">{u.mac_display}</span> },
    { key: "model", header: "Model", render: (u) => <span>{[u.manufacturer, u.model].filter(Boolean).join(" ") || <span className="subtle">{u.user_agent ?? "unknown"}</span>}</span> },
    { key: "org", header: "Credential of", render: (u) => u.organization_name ?? "—" },
    { key: "ip", header: "Address", render: (u) => <span className="mono">{u.ip_address ?? "—"}</span> },
    { key: "seen", header: "Last seen", render: (u) => <span>{formatRelative(u.last_seen_at)} · {u.requests} request{u.requests === 1 ? "" : "s"}</span> },
    ...(editable ? [{ key: "actions", header: "", render: (u: UnregisteredDevice) => <Button size="sm" variant="primary" onClick={() => { setSeen(u); setCreateOpen(true); }}>Register</Button> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Devices" description="Phones registered by MAC address. Each phone fetches its configuration from this server with its profile's template."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => { setSeen(undefined); setCreateOpen(true); }}>Register a phone</Button> : null} />
      {unregistered.data?.length ? (
        <Card title="Phones seen but not registered" subtitle="These phones asked for configuration with a valid enrollment credential in the last 7 days but have no device record yet." flush>
          <DataTable columns={seenColumns} rows={unregistered.data} rowKey={(u) => u.mac_address} caption="Unregistered phones" />
        </Card>
      ) : null}
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by label, MAC, model or extension" label="Search devices" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
          <SelectField label={<span className="sr-only">Profile</span>} value={profile} placeholder="All profiles" options={(profiles.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => { setProfile(e.target.value); setOffset(0); }} />
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(d) => d.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Devices"
          onRowClick={(d) => router.push(`/devices/view/?id=${d.id}`)} rowLabel={(d) => `Open device ${d.label ?? d.mac_display}`}
          empty={<EmptyState icon="device" title={debounced || org || profile ? "No matching devices" : "No devices yet"}>{!debounced && !org && !profile && editable ? "Register a phone by its MAC address, or point a phone at this server and it appears above." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <DeviceDialog open={createOpen} seen={seen} onClose={() => setCreateOpen(false)} onCreated={(d) => { reload(); router.push(`/devices/view/?id=${d.id}`); }} />
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><DevicesList /></Suspense>;
}
