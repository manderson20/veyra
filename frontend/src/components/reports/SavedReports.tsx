// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, IconButton, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ReportSchedule, SavedReport } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"];

export function scheduleText(s: ReportSchedule | null): string {
  if (!s) return "Not emailed";
  const at = `${String(s.hour).padStart(2, "0")}:00`;
  const when = s.frequency === "daily" ? `Daily at ${at}` : s.frequency === "weekly" ? `${WEEKDAYS[s.weekday]} at ${at}` : `Monthly on day ${s.day} at ${at}`;
  return `${when} to ${s.recipients.length === 1 ? s.recipients[0] : `${s.recipients.length} people`}`;
}

/** Saved reports (docs/REPORT_BUILDER.md §2-3): open in the builder, email now, delete. */
export function SavedReports({ onOpen, version }: { onOpen: (r: SavedReport) => void; version: number }) {
  const toast = useToast();
  const list = useApiData<SavedReport[]>("/saved-reports", { v: version });
  const [removing, setRemoving] = useState<SavedReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const send = async (r: SavedReport) => {
    setBusy(r.id);
    try {
      await api.post(`/saved-reports/${r.id}/send`);
      toast.success("Report sent", r.schedule ? `Queued for ${r.schedule.recipients.join(", ")}.` : undefined);
      list.reload();
    } catch (err) {
      toast.error("Not sent", errorMessage(err));
      list.reload();
    } finally {
      setBusy(null);
    }
  };
  const remove = async () => {
    if (!removing) return;
    try {
      await api.del(`/saved-reports/${removing.id}`);
      setRemoving(null);
      list.reload();
    } catch (err) {
      toast.error("Not deleted", errorMessage(err));
    }
  };
  const columns: Column<SavedReport>[] = [
    { key: "name", header: "Report", render: (r) => <><span className="table__primary">{r.name}</span>{r.description ? <span className="table__secondary" style={{ display: "block" }}>{r.description}</span> : null}</> },
    { key: "share", header: "Visible to", render: (r) => (r.shared ? "Organization" : <Badge tone="neutral">Only you and editors</Badge>) },
    { key: "schedule", header: "Email", render: (r) => <><span>{scheduleText(r.schedule)}</span>{r.next_run_at ? <span className="table__secondary" style={{ display: "block" }}>Next {formatDateTime(r.next_run_at)}</span> : null}</> },
    { key: "last", header: "Last sent", render: (r) => r.last_error ? <Badge tone="warn">{r.last_error}</Badge> : r.last_sent_at ? <span className="nowrap">{formatDateTime(r.last_sent_at)}</span> : "—" },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (r) => (
        <span className="row" style={{ gap: 4 }}>
          <Button size="sm" icon="play" onClick={() => onOpen(r)}>Open</Button>
          {r.can_edit && r.schedule ? <Button size="sm" icon="mail" loading={busy === r.id} onClick={() => send(r)}>Send now</Button> : null}
          {r.can_edit ? <IconButton size="sm" icon="trash" label={`Delete ${r.name}`} onClick={() => setRemoving(r)} /> : null}
        </span>
      ),
    },
  ];
  return (
    <Card flush>
      <DataTable columns={columns} rows={list.data} rowKey={(r) => r.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Saved reports" onRowClick={onOpen} rowLabel={(r) => `Open ${r.name}`}
        empty={<EmptyState icon="activity" title="No saved reports" compact>Build a report and save it to find it here, or to have it emailed on a schedule.</EmptyState>} />
      <ConfirmDialog open={removing !== null} title={`Delete "${removing?.name ?? ""}"?`} confirmLabel="Delete" tone="danger" onConfirm={remove} onCancel={() => setRemoving(null)}>
        <p>{removing?.schedule ? "Its scheduled email stops too." : "The report definition is removed; no call data is deleted."}</p>
      </ConfirmDialog>
    </Card>
  );
}
