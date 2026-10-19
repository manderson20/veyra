// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { TEMPLATE_SOURCE } from "@/components/common/labels";
import { ImportTemplateDialog } from "@/components/provisioning/ImportTemplateDialog";
import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  EmptyState,
  PageHeader,
  type Column,
} from "@/components/ui";
import { CopyButton } from "@/components/common/CopyButton";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE } from "@/lib/api";
import type { TemplateSummary } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

export default function ProvisioningPage() {
  const router = useRouter();
  const { can } = useSession();
  const list = useApiData<{ items: TemplateSummary[]; load_errors: Record<string, string[]> }>("/provisioning/templates");
  const [importOpen, setImportOpen] = useState(false);

  const columns: Column<TemplateSummary>[] = [
    {
      key: "name",
      header: "Template",
      render: (t) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{t.name}</span>
          <span className="table__secondary mono">{t.key}</span>
        </span>
      ),
    },
    { key: "models", header: "Models", render: (t) => (t.abstract ? <span className="subtle">Base template</span> : t.models.join(", ")) },
    { key: "version", header: "Version", render: (t) => <span className="mono">{t.version}</span> },
    {
      key: "source",
      header: "Source",
      render: (t) => (
        <span className="row">
          <Badge tone={TEMPLATE_SOURCE[t.source]?.tone ?? "neutral"}>{TEMPLATE_SOURCE[t.source]?.label ?? t.source}</Badge>
          {t.status !== "stable" ? <Badge tone={t.status === "deprecated" ? "danger" : "warn"}>{t.status}</Badge> : null}
          {t.parent_updated ? <Badge tone="info">Parent updated</Badge> : null}
        </span>
      ),
    },
  ];

  const errors = Object.entries(list.data?.load_errors ?? {});
  return (
    <div className="stack">
      <PageHeader
        title="Provisioning templates"
        description="Configuration templates that phones download to configure themselves."
        actions={can("provisioning.write") ? <Button icon="upload" onClick={() => setImportOpen(true)}>Import template</Button> : null}
      />
      <Callout tone="neutral">
        Official templates are never modified. To customise one, export it and import it under a new key with the official template
        as its parent; your local template overrides only what it changes. Device assignment arrives with device management (Milestone 9).
      </Callout>
      {errors.length ? (
        <Callout tone="warn" title="Some templates could not be loaded">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{errors.map(([k, v]) => <li key={k}><span className="mono">{k}</span>: {v.join("; ")}</li>)}</ul>
        </Callout>
      ) : null}
      <RedirectServices />
      <Card flush>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(t) => t.key} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Provisioning templates" onRowClick={(t) => router.push(`/provisioning/view/?key=${encodeURIComponent(t.key)}`)}
          rowLabel={(t) => `Open ${t.name}`} empty={<EmptyState icon="template" title="No templates found" />} />
      </Card>
      <ImportTemplateDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={(key) => router.push(`/provisioning/view/?key=${encodeURIComponent(key)}`)} />
    </div>
  );
}

const REDIRECT_VENDORS: { name: string; manufacturer: string; service: string; how: string }[] = [
  { name: "Yealink", manufacturer: "Yealink", service: "Yealink RPS (Redirection and Provisioning Service)", how: "Add the MACs in the RPS portal with the provisioning URL as the server; the phones then find Veyra at first boot." },
  { name: "Poly", manufacturer: "Poly", service: "Poly ZTP (Zero Touch Provisioning) in Poly Lens", how: "Register the MACs with the provisioning URL; or use DHCP option 160 on the voice VLAN." },
  { name: "Algo", manufacturer: "Algo", service: "DHCP option 66 (Algo has no cloud redirect)", how: "Give the voice VLAN option 66 with the provisioning URL, or set the static server once in the device's web page." },
  { name: "Grandstream", manufacturer: "Grandstream", service: "Grandstream GDMS", how: "Import the MACs in GDMS with the provisioning URL as the config server." },
];

/** Vendor redirect services (docs/PROVISIONING_BREADTH.md §6): how new phones
 * find Veyra, and the MAC export to register them in bulk. */
function RedirectServices() {
  const url = typeof window === "undefined" ? "/provisioning/" : `${window.location.origin}/provisioning/`;
  return (
    <Card title="Redirect services" subtitle="New phones find Veyra through their vendor's redirect service or DHCP; register them in bulk with the device export.">
      <div className="stack stack--sm">
        <p>Provisioning URL: <span className="mono">{url}</span> <CopyButton text={url} /></p>
        <p className="subtle">Phones authenticate with their organization&apos;s enrollment credential (Organizations → organization → Provisioning credential) the first time, then with their own.</p>
        <ul className="stack stack--sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {REDIRECT_VENDORS.map((v) => (
            <li key={v.name} className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
              <span style={{ minWidth: 0 }}>
                <span className="table__primary" style={{ display: "block" }}>{v.name}: {v.service}</span>
                <span className="table__secondary">{v.how}</span>
              </span>
              <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/devices/export.csv?manufacturer=${encodeURIComponent(v.manufacturer)}`} download>Export {v.name} MACs</a>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
