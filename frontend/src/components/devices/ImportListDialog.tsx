// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Dialog, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useOnChange } from "@/hooks/useOnChange";

interface ImportRow { row: number; key: string; action: "create" | "update" | "unchanged" | "error"; message: string | null }
interface ImportResult { dry_run: boolean; counts: Record<string, number>; rows: ImportRow[] }

const ACTION: Record<ImportRow["action"], { tone: "ok" | "info" | "neutral" | "danger"; label: string }> = {
  create: { tone: "ok", label: "New phone" },
  update: { tone: "info", label: "Update" },
  unchanged: { tone: "neutral", label: "No change" },
  error: { tone: "danger", label: "Error" },
};

/** Import List of Extension Mapping: check the file, then import it. */
export function ImportListDialog({ open, organizationId, onClose, onImported }: { open: boolean; organizationId: string; onClose: () => void; onImported: () => void }) {
  const toast = useToast();
  const [text, setText] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useOnChange(open, () => { setText(null); setResult(null); setError(null); });

  const run = async (dryRun: boolean) => {
    if (text === null) return;
    setBusy(dryRun ? "check" : "import");
    setError(null);
    try {
      const r = await api.post<ImportResult>(`/bulk/phones/import?organization_id=${encodeURIComponent(organizationId)}&dry_run=${dryRun}`, { csv: text });
      setResult(r);
      if (!dryRun) {
        const done = (r.counts.create ?? 0) + (r.counts.update ?? 0);
        onImported();
        if (r.counts.error) {
          toast.error(`${done} row${done === 1 ? "" : "s"} imported, ${r.counts.error} with errors`, "The rows with errors were not changed.");
        } else {
          toast.success(`${done} row${done === 1 ? "" : "s"} imported`);
          onClose();
        }
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const changes = (result?.counts.create ?? 0) + (result?.counts.update ?? 0);
  const shown = result?.rows.filter((r) => r.action !== "unchanged") ?? [];

  return (
    <Dialog open={open} onClose={onClose} busy={!!busy} title="Import List"
      description="A CSV with the columns of Export List: mac, extension, brand, model, template, label. Rows match on the MAC address. An empty cell keeps the value; a dash (-) clears it."
      footer={<>
        <Button onClick={onClose} disabled={!!busy}>Close</Button>
        <Button onClick={() => void run(true)} loading={busy === "check"} disabled={text === null || !!busy}>Check</Button>
        <Button variant="primary" onClick={() => void run(false)} loading={busy === "import"} disabled={!result?.dry_run || changes === 0 || !!busy}>Import{changes ? ` ${changes} row${changes === 1 ? "" : "s"}` : ""}</Button>
      </>}>
      <div className="stack stack--sm">
        <label className="field">
          <span className="field__label">CSV file</span>
          <input type="file" accept=".csv,text/csv" disabled={!!busy} onChange={async (e) => { const f = e.target.files?.[0]; setResult(null); setError(null); setText(f ? await f.text() : null); }} />
        </label>
        {error ? <Callout tone="danger">{error}</Callout> : null}
        {result && !shown.length ? <p className="muted">Nothing to change.</p> : null}
        {shown.map((r) => (
          <div key={r.row} className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className="mono subtle">Line {r.row}</span>
            <span className="mono">{r.key || "—"}</span>
            <Badge tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Badge>
            {r.message ? <span>{r.message}</span> : null}
          </div>
        ))}
      </div>
    </Dialog>
  );
}
