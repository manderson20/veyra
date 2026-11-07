// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Card, Checkbox, DataTable, EmptyState, PageHeader, Pagination, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ConfigCheckModeState, ConfigCheckOverrideRow, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { MODE_OPTIONS } from "@/components/provisioning/ConfigCheck";
import { PackCoverage } from "@/components/provisioning/PackCoverage";

const LIMIT = 50;

/** Installation and organization modes (docs/CONFIG_VERIFICATION.md §5). */
function Modes({ org }: { org: string }) {
  const { can } = useSession();
  const toast = useToast();
  const mode = useApiData<ConfigCheckModeState>("/provisioning/check-mode", { organization_id: org || undefined });
  const [busy, setBusy] = useState(false);
  const set = async (scope: "installation" | "organization", value: string) => {
    setBusy(true);
    try {
      mode.setData(await api.put<ConfigCheckModeState>("/provisioning/check-mode", { scope, scope_id: scope === "organization" ? org : null, mode: value || null }));
      toast.success("Check mode saved");
    } catch (err) {
      toast.error("The mode was not changed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const m = mode.data;
  return (
    <Card title="Check mode" subtitle="How configuration checks treat a setting a phone's firmware would refuse. A template can set its own mode on its page.">
      {m ? (
        <div className="form-grid">
          <SelectField label="Whole installation" value={m.installation} options={MODE_OPTIONS} disabled={busy || !can("system.settings.write")}
            onChange={(e) => void set("installation", e.target.value)} />
          {org ? (
            <SelectField label="This organization" value={m.organization ?? ""} options={[{ value: "", label: "Same as the installation" }, ...MODE_OPTIONS]}
              disabled={busy || !can("provisioning.check.mode")} onChange={(e) => void set("organization", e.target.value)} />
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/** Overrides of configuration check findings, and the "checker is wrong" reports (§6, §7.2). */
export default function ConfigChecksPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [offset, setOffset] = useState(0);
  const [org, setOrg] = useState("");
  const [wrong, setWrong] = useState(false);
  const [revoked, setRevoked] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const list = useApiData<Page<ConfigCheckOverrideRow>>("/provisioning/check-overrides", {
    limit: LIMIT, offset, organization_id: org || undefined, checker_wrong: wrong || undefined, include_revoked: revoked || undefined, q: q.trim() || undefined,
  });
  const revoke = async (row: ConfigCheckOverrideRow) => {
    setBusy(row.id);
    try {
      await api.post(`/provisioning/check-overrides/${row.id}/revoke`, {});
      toast.success("Override revoked", "The finding stops the next save of this configuration again.");
      list.reload();
    } catch (err) {
      toast.error("The override was not revoked", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const columns: Column<ConfigCheckOverrideRow>[] = [
    { key: "setting", header: "Setting", render: (r) => (
      <>
        <span className="table__primary mono" style={{ overflowWrap: "anywhere" }}>{r.parameter}</span>
        <span className="table__secondary" style={{ display: "block" }}>{r.message}</span>
      </>
    ) },
    { key: "value", header: "Value", render: (r) => <span className="mono">{r.value === null ? "••••" : r.value === "" ? <span className="subtle">empty</span> : r.value}</span> },
    { key: "phones", header: "Phones", render: (r) => <span className="nowrap">{r.model} · {r.vendor} {r.family} {r.release}</span> },
    { key: "reason", header: "Why", render: (r) => (
      <>
        <span>{r.reason}</span>
        <span className="row" style={{ gap: 4, marginTop: 4 }}>
          {r.checker_wrong ? <Badge tone="warn">Checker is wrong</Badge> : null}
          {r.revoked_at ? <Badge tone="neutral">Revoked</Badge> : null}
          {r.stale_at ? <Badge tone="neutral">No longer occurs</Badge> : null}
        </span>
      </>
    ) },
    { key: "by", header: "By", render: (r) => <><span>{r.created_by_label}</span><span className="table__secondary nowrap" style={{ display: "block" }}>{formatDateTime(r.created_at)}</span></> },
    ...(can("provisioning.check.override") ? [{ key: "actions", header: "", render: (r: ConfigCheckOverrideRow) => (
      r.revoked_at ? null : <Button size="sm" variant="ghost" loading={busy === r.id} onClick={() => void revoke(r)}>Revoke</Button>
    ) }] : []),
  ];
  return (
    <div className="stack">
      <PageHeader title="Configuration checks" description="Settings saved past a check, why, and by whom. A setting someone marked as “checker is wrong” is a correction for the vendor data." />
      <Callout tone="info">An override covers one setting with one value on one model and firmware release. A different value, model or release is checked again.</Callout>
      <Modes org={effectiveOrg} />
      <PackCoverage />
      <Card flush>
        <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end", padding: "var(--space-3) var(--space-4)" }}>
          {organizations.length > 1 ? <SelectField label="Organization" value={org} options={[{ value: "", label: "All" }, ...organizations.map((o) => ({ value: o.id, label: o.name }))]} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
          <TextField label="Setting" value={q} maxLength={100} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
          <Checkbox label="Checker is wrong" checked={wrong} onChange={(e) => { setWrong(e.target.checked); setOffset(0); }} />
          <Checkbox label="Include revoked" checked={revoked} onChange={(e) => { setRevoked(e.target.checked); setOffset(0); }} />
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(r) => r.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Configuration check overrides"
          empty={<EmptyState icon="checkCircle" title="No overrides" compact>No setting has been saved past a configuration check.</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
    </div>
  );
}
