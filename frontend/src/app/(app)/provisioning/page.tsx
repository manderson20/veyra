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
      <Card flush>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(t) => t.key} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Provisioning templates" onRowClick={(t) => router.push(`/provisioning/view/?key=${encodeURIComponent(t.key)}`)}
          rowLabel={(t) => `Open ${t.name}`} empty={<EmptyState icon="template" title="No templates found" />} />
      </Card>
      <ImportTemplateDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={(key) => router.push(`/provisioning/view/?key=${encodeURIComponent(key)}`)} />
    </div>
  );
}
