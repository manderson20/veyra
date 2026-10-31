// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { NewTemplateDialog } from "@/components/devices/NewTemplateDialog";
import { RedirectServices } from "@/components/provisioning/RedirectServices";
import { Badge, Button, Card, DataTable, EmptyState, ErrorState, LoadingState, PageHeader, Pagination, SearchInput, SelectField, type Column } from "@/components/ui";
import type { DeviceProfile, Page as ApiPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;
/** Base files that no longer load leave their templates under this name. */
const NO_BRAND = "Other";
const templateHref = (id: string) => `/provisioning/brands/template/?id=${id}`;


function BrandView() {
  const name = useSearchParams().get("name") ?? "";
  const router = useRouter();
  const { can, refresh } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<ApiPage<DeviceProfile>>(name ? "/device-profiles" : null, { manufacturer: name, q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  if (!name) return <ErrorState title="No brand selected" error={{ message: "Open a brand from the Provisioning menu." }} />;
  const manyOrgs = organizations.length > 1;
  const creatable = can("devices.write") && name !== NO_BRAND;
  const columns: Column<DeviceProfile>[] = [
    {
      key: "name",
      header: "Template",
      render: (p) => (
        <span>
          <span className="row" style={{ gap: 6 }}><span className="table__primary">{p.name}</span>{p.is_default ? <Badge tone="info">Default</Badge> : null}{p.problems.length ? <Badge tone="warn" icon="alert">{p.problems[0]}</Badge> : null}</span>
          <span className="table__secondary">{p.site_name ?? p.description ?? ""}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (p: DeviceProfile) => <span>{p.organization_name}</span> }] : []),
    {
      key: "used",
      header: "Used By",
      render: (p) => p.devices ? (
        <span className="row" style={{ gap: 4, flexWrap: "wrap" }} onClick={(e) => e.stopPropagation()}>
          {p.used_by.map((u) => <Link key={u.device_id} className="kv-chip" href={`/devices/view/?id=${u.device_id}`}>{u.label}</Link>)}
          {p.devices > p.used_by.length ? <Link className="kv-chip" href={`/devices/?profile=${p.id}`}>{p.devices - p.used_by.length} more</Link> : null}
        </span>
      ) : <span className="subtle">Not in use</span>,
    },
  ];
  return (
    <div className="stack">
      <PageHeader title={name} description={`Templates for ${name} phones. Each phone uses one, and only this brand's templates are offered for it.`}
        actions={creatable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New Template</Button> : null} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or base file" label="Search templates" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption={`${name} templates`}
          onRowClick={(p) => router.push(templateHref(p.id))} rowLabel={(p) => `Open template ${p.name}`}
          empty={<EmptyState icon="settings" title={debounced || org ? "No matching templates" : "No templates yet"}>{!debounced && !org && creatable ? `Create a template, then choose it for ${name} phones under Devices.` : null}</EmptyState>} />
      </Card>
      {list.data && list.data.total > LIMIT ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
      {name !== NO_BRAND ? <RedirectServices brand={name} /> : null}
      <NewTemplateDialog brand={name} open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(p) => { void refresh(); router.push(templateHref(p.id)); }} />
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><BrandView /></Suspense>;
}
