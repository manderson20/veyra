// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
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
import { groupByBrand } from "@/lib/brands";
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
      header: "Base file",
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
  const groups = groupByBrand([...(list.data?.items ?? [])].sort((a, b) => Number(b.abstract) - Number(a.abstract)), (t) => t.manufacturer);
  return (
    <div className="stack">
      <PageHeader
        title="Base files"
        description="The system defaults that phone configuration is built from. Each brand's templates choose from these."
        actions={can("provisioning.write") ? <Button icon="upload" onClick={() => setImportOpen(true)}>Import base file</Button> : null}
      />
      <Callout tone="neutral">
        Official base files are never modified. To change one, open it and choose <strong>Customize</strong>: Veyra makes a local copy
        under it that overrides only what you change, for your organization (or the whole server for a platform-wide copy).
        Phones get a base file through their template.
      </Callout>
      {errors.length ? (
        <Callout tone="warn" title="Some base files could not be loaded">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{errors.map(([k, v]) => <li key={k}>{k.startsWith("db:") && can("provisioning.write") ? <Link className="mono" href={`/provisioning/view/?key=${encodeURIComponent(k.slice(3))}`}>{k.slice(3)}</Link> : <span className="mono">{k}</span>}: {v.join("; ")}</li>)}</ul>
        </Callout>
      ) : null}
      {groups.length ? groups.map((g) => (
        <Card key={g.brand} title={g.brand} flush>
          <DataTable columns={columns} rows={g.rows} rowKey={(t) => t.key} caption={`${g.brand} base files`}
            onRowClick={(t) => router.push(`/provisioning/view/?key=${encodeURIComponent(t.key)}`)} rowLabel={(t) => `Open ${t.name}`} />
        </Card>
      )) : (
        <Card flush>
          <DataTable columns={columns} rows={list.data?.items} rowKey={(t) => t.key} loading={list.loading} error={list.error} onRetry={list.reload}
            caption="Base files" empty={<EmptyState icon="template" title="No base files found" />} />
        </Card>
      )}
      <ImportTemplateDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={(key) => router.push(`/provisioning/view/?key=${encodeURIComponent(key)}`)} />
    </div>
  );
}
