// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

/** The vendor data behind configuration checks (docs/CONFIG_VERIFICATION.md §2.0): every
 * pack with where it came from, the phones and firmware it covers and how much of it is
 * cited from the vendor, the phones in use that no pack covers, and import for platform
 * administrators. */

import { useState } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, EmptyState, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { CapabilityCoverage, CapabilityPackInfo } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

function origin(o: string) {
  if (o === "built-in") return <Badge tone="info">Built in</Badge>;
  if (o === "local") return <Badge tone="accent">Imported</Badge>;
  return <Badge tone="neutral">{`Module ${o.replace(/^module:/, "")}`}</Badge>;
}

export function PackCoverage() {
  const { session } = useSession();
  const toast = useToast();
  const data = useApiData<CapabilityCoverage>("/provisioning/capability-packs");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<CapabilityPackInfo | null>(null);
  const platform = Boolean(session?.is_platform_admin);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const pack = await api.upload<CapabilityPackInfo>("/provisioning/capability-packs", form);
      toast.success(`Pack ${pack.name} imported`, "Saves are now checked against it.");
      setFile(null);
      data.reload();
    } catch (err) {
      toast.error("The pack was not imported", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!removing) return;
    try {
      await api.del(`/provisioning/capability-packs/${encodeURIComponent(removing.id)}`);
      toast.success(`Pack ${removing.name} removed`);
      data.reload();
    } catch (err) {
      toast.error("The pack was not removed", errorMessage(err));
    } finally {
      setRemoving(null);
    }
  };

  const columns: Column<CapabilityPackInfo>[] = [
    { key: "pack", header: "Pack", render: (p) => <><span className="table__primary">{p.name}</span><span className="table__secondary mono" style={{ display: "block" }}>{p.id} {p.version}</span></> },
    { key: "origin", header: "From", render: (p) => origin(p.origin) },
    { key: "phones", header: "Phones covered", render: (p) => (
      <span className="stack--sm">
        {p.supports.map((s) => (
          <span key={s.family} style={{ display: "block" }}>
            <span>{s.models.join(", ")}</span>
            <span className="table__secondary" style={{ display: "block" }}>
              {s.firmware ? `Firmware ${s.firmware}. ` : ""}
              {s.provenance === "seeded-from-template" ? "Model list taken from Veyra's templates, not yet the vendor's." : `Source: ${s.source}`}
            </span>
          </span>
        ))}
      </span>
    ) },
    { key: "releases", header: "Firmware releases", render: (p) => (
      <span className="stack--sm">
        {p.families.flatMap((f) => f.releases.map((r) => (
          <span key={`${f.family}-${r.version}`} style={{ display: "block" }}>
            <span className="mono">{f.family} {r.version}</span>{" "}
            <span className="subtle">{`${r.settings} settings, ${r.cited} cited from the vendor`}</span>
          </span>
        )))}
      </span>
    ) },
    ...(platform ? [{ key: "actions", header: "", render: (p: CapabilityPackInfo) => (
      p.origin === "local" ? <Button size="sm" variant="ghost" onClick={() => setRemoving(p)}>Remove</Button> : null
    ) }] : []),
  ];
  const errors = Object.entries(data.data?.load_errors ?? {});
  return (
    <Card title="Vendor data" subtitle="The packs configuration checks compare against. A phone no pack covers is not checked." flush>
      <DataTable columns={columns} rows={data.data?.packs} rowKey={(p) => p.id} loading={data.loading} error={data.error} onRetry={data.reload} caption="Capability packs"
        empty={<EmptyState icon="device" title="No vendor data" compact>No pack is loaded, so nothing is checked.</EmptyState>} />
      <div className="stack--sm" style={{ padding: "var(--space-3) var(--space-4)" }}>
        {data.data?.uncovered.length ? (
          <Callout tone="warn" title="Phones no pack covers">
            {data.data.uncovered.map((u) => `${u.manufacturer} ${u.model} (${u.phones})`).join(", ")}. Saves for these phones are not checked.
          </Callout>
        ) : null}
        {errors.length ? (
          <Callout tone="danger" title="Packs that did not load">
            {errors.map(([where, list]) => <span key={where} style={{ display: "block" }}><span className="mono">{where}</span>: {list.slice(0, 3).join("; ")}{list.length > 3 ? ` (+${list.length - 3} more)` : ""}</span>)}
          </Callout>
        ) : null}
        {platform ? (
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <input type="file" accept=".zip,application/zip" aria-label="Pack archive" disabled={busy} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <Button loading={busy} disabled={!file} onClick={() => void upload()}>Import pack</Button>
            <span className="subtle">A ZIP with pack.toml at its top. See the pack author&apos;s guide.</span>
          </div>
        ) : null}
      </div>
      <ConfirmDialog open={!!removing} title={`Remove ${removing?.name ?? ""}?`} confirmLabel="Remove" tone="danger"
        onCancel={() => setRemoving(null)} onConfirm={() => void remove()}>
        Saves for the phones it covers are no longer checked against it.
      </ConfirmDialog>
    </Card>
  );
}
