// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button, Callout, Card, ConfirmDialog, DataTable, ErrorState, LoadingState, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";
import type { RetentionInventoryRow, RetentionRule, RetentionState } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

/** Settings → Retention (docs/PRODUCTION_HARDENING.md §4). */
export function RetentionCard() {
  const { session, can } = useSession();
  const toast = useToast();
  const editable = !!session?.is_platform_admin && can("system.settings.write");
  const state = useApiData<RetentionState>("/retention");
  const inventory = useApiData<RetentionInventoryRow[]>("/retention/inventory");
  const [days, setDays] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirmShort, setConfirmShort] = useState(false);
  useOnChange(state.data, (s) => { if (s) setDays(Object.fromEntries(s.rules.map((r) => [r.key, String(r.days)]))); });

  const changed = (): Record<string, number> => {
    const out: Record<string, number> = {};
    for (const r of state.data?.rules ?? []) {
      const v = Number(days[r.key]);
      if (Number.isFinite(v) && v !== r.days) out[r.key] = v;
    }
    return out;
  };
  const save = async (confirm = false) => {
    const body = changed();
    if (!Object.keys(body).length) return;
    if (!confirm && Object.values(body).some((v) => v < 30)) { setConfirmShort(true); return; }
    setBusy(true);
    try {
      const s = await api.put<RetentionState>("/retention", { days: body, confirm_short: confirm });
      state.setData(s);
      toast.success("Retention saved");
      setConfirmShort(false);
    } catch (err) {
      toast.error("Could not save retention", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const runNow = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ removed: Record<string, number> }>("/retention/run");
      const gone = Object.entries(r.removed).filter(([, n]) => n > 0).map(([k, n]) => `${k}: ${n}`).join(", ");
      toast.success("Retention applied", gone || "Nothing was past its retention.");
      state.reload();
      inventory.reload();
    } catch (err) {
      toast.error("Could not run retention", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const byKey: Record<string, RetentionInventoryRow | undefined> = Object.fromEntries((inventory.data ?? []).map((r) => [r.key, r]));
  const columns: Column<RetentionRule>[] = [
    { key: "label", header: "Data", render: (r) => <span><span className="table__primary" style={{ display: "block" }}>{r.label}</span><span className="table__secondary">{r.description}</span></span> },
    { key: "days", header: "Keep (days)", render: (r) => editable ? (
      <TextField label="" aria-label={`${r.label}, days`} type="number" min={r.minimum_days} value={days[r.key] ?? String(r.days)} onChange={(e) => setDays({ ...days, [r.key]: e.target.value })} style={{ width: 110 }} />
    ) : <span>{r.days}</span> },
    { key: "rows", header: "Rows", render: (r) => { const i = byKey[r.key]; return i ? i.rows.toLocaleString() : "—"; } },
    { key: "bytes", header: "Size", render: (r) => { const i = byKey[r.key]; return i ? formatBytes(i.bytes) : "—"; } },
    { key: "oldest", header: "Oldest", render: (r) => { const i = byKey[r.key]; return <span className="subtle">{i?.oldest ? formatRelative(i.oldest) : "—"}</span>; } },
  ];
  const extra = (inventory.data ?? []).filter((r) => !(state.data?.rules ?? []).some((x) => x.key === r.key));

  return (
    <Card title="Retention" subtitle={state.data?.last_run ? `Last applied ${formatDateTime(state.data.last_run.at)}` : "Applied once a day by the worker."}
      actions={editable ? <span className="row" style={{ gap: 6 }}><Button onClick={runNow} loading={busy}>Apply now</Button><Button variant="primary" onClick={() => save(false)} loading={busy} disabled={!Object.keys(changed()).length}>Save</Button></span> : null}>
      {state.error ? <ErrorState compact error={state.error} onRetry={state.reload} /> : !state.data ? <LoadingState /> : (
        <div className="stack stack--sm">
          <DataTable columns={columns} rows={state.data.rules} rowKey={(r) => r.key} caption="Retention per data class" />
          {extra.length ? (
            <p className="subtle">
              Also on disk: {extra.map((r) => `${r.label} ${formatBytes(r.bytes)}${r.rows ? ` (${r.rows.toLocaleString()})` : ""}${r.note ? ` — ${r.note}` : ""}`).join("; ")}.
            </p>
          ) : null}
          <Callout tone="neutral">The audit log never goes below a year. Shortening any class below 30 days asks for confirmation. Every run writes one audit entry per class that lost rows.</Callout>
        </div>
      )}
      <ConfirmDialog open={confirmShort} title="Keep data for less than 30 days" confirmLabel="Save" tone="danger" typeToConfirm="SHORTEN" busy={busy}
        onCancel={() => setConfirmShort(false)} onConfirm={() => save(true)}>
        <p>Rows older than the new retention are removed at the next run and cannot be recovered except from a backup.</p>
      </ConfirmDialog>
    </Card>
  );
}
