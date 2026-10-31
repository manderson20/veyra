// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ImportTemplateDialog } from "@/components/provisioning/ImportTemplateDialog";
import { Button, Callout, Card, DataTable, EmptyState, PageHeader, type Column } from "@/components/ui";
import type { PhoneBrand } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

export default function BrandsPage() {
  const router = useRouter();
  const { can, refresh } = useSession();
  const list = useApiData<PhoneBrand[]>("/device-profiles/brands");
  const [importOpen, setImportOpen] = useState(false);
  const columns: Column<PhoneBrand>[] = [
    { key: "name", header: "Brand", render: (b) => <span className="table__primary">{b.name}</span> },
    { key: "models", header: "Models", render: (b) => b.models.join(", ") || <span className="subtle">None</span> },
    { key: "templates", header: "Templates", render: (b) => <span>{b.templates}</span> },
    { key: "phones", header: "Phones", render: (b) => <span>{b.phones}</span> },
  ];
  return (
    <div className="stack">
      <PageHeader title="Brands" description="Each brand with a base file on this server has its own entry in the Provisioning menu."
        actions={can("provisioning.write") ? <Button variant="primary" icon="upload" onClick={() => setImportOpen(true)}>Add Brand</Button> : null} />
      <Callout tone="neutral">To add a brand, import a base file for it. The file names its brand and models, and the brand appears here and in the menu.</Callout>
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(b) => b.name} loading={list.loading} error={list.error} onRetry={list.reload} caption="Phone brands"
          onRowClick={(b) => router.push(`/provisioning/brands/view/?name=${encodeURIComponent(b.name)}`)} rowLabel={(b) => `Open ${b.name}`}
          empty={<EmptyState icon="device" title="No brands yet" />} />
      </Card>
      <ImportTemplateDialog open={importOpen} onClose={() => setImportOpen(false)} onImported={() => { setImportOpen(false); list.reload(); void refresh(); }} />
    </div>
  );
}
