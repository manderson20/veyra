// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SelectField, Switch, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { AlertItem, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

interface AlertRule {
  key: string;
  title: string;
  is_enabled: boolean;
  delay_minutes: number;
  threshold: number | null;
  unit: string;
  recipients: string[];
}

const LIMIT = 50;

function RuleDialog({ rule, onClose, onSaved }: { rule: AlertRule | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [enabled, setEnabled] = useState(true);
  const [delay, setDelay] = useState("0");
  const [threshold, setThreshold] = useState("");
  const [recipients, setRecipients] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(rule, () => {
    if (!rule) return;
    setEnabled(rule.is_enabled);
    setDelay(String(rule.delay_minutes));
    setThreshold(rule.threshold === null ? "" : String(rule.threshold));
    setRecipients(rule.recipients.join("\n"));
    errors.clear();
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!rule) return;
    setBusy(true);
    errors.clear();
    try {
      await api.patch(`/alert-rules/${rule.key}`, {
        is_enabled: enabled,
        delay_minutes: Number(delay),
        ...(rule.threshold !== null ? { threshold: Number(threshold) } : {}),
        recipients: recipients.split(/[\s,;]+/).filter(Boolean),
      });
      toast.success("Alert rule saved");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={rule !== null} onClose={onClose} busy={busy} title={rule?.title ?? ""}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="alert-rule-form" loading={busy}>Save</Button></>}>
      <form id="alert-rule-form" className="stack stack--sm" onSubmit={submit}>
        <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <TextField label="Raise after (minutes)" type="number" min={0} max={1440} value={delay} error={errors.fields.delay_minutes}
          help="How long the problem must last before anyone is told; short blips are ignored." onChange={(e) => setDelay(e.target.value)} />
        {rule?.threshold !== null ? (
          <TextField label={`Limit (${rule?.unit})`} type="number" min={1} value={threshold} error={errors.fields.threshold} onChange={(e) => setThreshold(e.target.value)} />
        ) : null}
        <TextArea label="Email to" rows={3} value={recipients} error={errors.fields.recipients} placeholder="it@district.example"
          help="One address per line. Sent when raised, every 24 hours while it lasts, and when cleared. Uses the email settings under System → Settings."
          onChange={(e) => setRecipients(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function AlertsPage() {
  const { can } = useSession();
  const [state, setState] = useState("open");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const list = useApiData<Page<AlertItem>>("/alerts", { state, limit: LIMIT, offset });
  const rules = useApiData<AlertRule[]>("/alert-rules");
  const editable = can("alerts.write");

  const columns: Column<AlertItem>[] = [
    { key: "title", header: "Alert", render: (a) => <><span className="table__primary">{a.title}{a.subject ? ` · ${a.subject}` : ""}</span><span className="table__secondary" style={{ display: "block" }}>{a.message}</span></> },
    { key: "state", header: "State", render: (a) => a.state === "raised" ? <Badge tone="danger" icon="alert">Raised</Badge> : a.state === "cleared" ? <Badge tone="ok" icon="check">Cleared</Badge> : <Badge tone="neutral">Pending</Badge> },
    { key: "when", header: "Since", render: (a) => <span className="nowrap" title={formatDateTime(a.raised_at ?? a.first_seen_at)}>{formatRelative(a.raised_at ?? a.first_seen_at)}</span> },
    { key: "cleared", header: "Cleared", render: (a) => (a.cleared_at ? <span className="nowrap">{formatDateTime(a.cleared_at)}</span> : "—") },
    { key: "mail", header: "Email", render: (a) => (a.notify_error ? <Badge tone="warn">{a.notify_error}</Badge> : <span className="subtle">—</span>) },
  ];
  const ruleColumns: Column<AlertRule>[] = [
    { key: "title", header: "Rule", render: (r) => r.title },
    { key: "on", header: "State", render: (r) => (r.is_enabled ? <Badge tone="ok">On</Badge> : <Badge tone="neutral">Off</Badge>) },
    { key: "delay", header: "Raise after", render: (r) => `${r.delay_minutes} min` },
    { key: "limit", header: "Limit", render: (r) => (r.threshold !== null ? `${r.threshold} ${r.unit}` : "—") },
    { key: "to", header: "Email to", render: (r) => r.recipients.join(", ") || <span className="subtle">nobody (shown here only)</span> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Alerts" description="Problems Veyra watches for: the phone system, trunks, services, disk space, the certificate, attacks and phones dropping off." />
      <Card flush>
        <div className="table-toolbar">
          <div style={{ minWidth: 180 }}>
            <SelectField label={<span className="sr-only">Show</span>} value={state}
              options={[{ value: "open", label: "Raised now" }, { value: "cleared", label: "Cleared" }, { value: "all", label: "All" }]}
              onChange={(e) => { setState(e.target.value); setOffset(0); }} />
          </div>
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(a) => a.id} loading={list.loading} error={list.error} onRetry={list.reload}
          caption="Alerts" empty={<EmptyState icon="checkCircle" title={state === "open" ? "Nothing is wrong" : "No alerts"} compact />}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <Card title="Rules" subtitle={editable ? "Click a rule to switch it, tune it or choose who gets the emails." : undefined} flush>
        <DataTable columns={ruleColumns} rows={rules.data} rowKey={(r) => r.key} loading={rules.loading} error={rules.error} onRetry={rules.reload}
          caption="Alert rules" onRowClick={editable ? setEditing : undefined} rowLabel={(r) => `Edit ${r.title}`} />
      </Card>
      <RuleDialog rule={editing} onClose={() => setEditing(null)} onSaved={rules.reload} />
    </div>
  );
}
