// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SelectField,
  StatusBadge,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { EmergencyCallRow, EmergencySiteDetail, EmergencySiteRow, Extension, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function SiteDialog({ siteId, onClose, onChanged }: { siteId: string | null; onClose: () => void; onChanged: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const manage = can("emergency.manage");
  const detail = useApiData<EmergencySiteDetail>(siteId ? `/emergency/sites/${siteId}` : null);
  const extensions = useApiData<Page<Extension>>(siteId ? "/extensions" : null, { limit: 500 });
  const [attested, setAttested] = useState(false);
  const [responder, setResponder] = useState("");
  const [minutes, setMinutes] = useState("30");
  const [emails, setEmails] = useState("");
  const [phones, setPhones] = useState("");
  const [webhook, setWebhook] = useState(true);
  const [testResult, setTestResult] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(detail.data, (d) => {
    if (!d) return;
    setAttested(d.settings.attested);
    setResponder(d.settings.responder_extension_id ?? "");
    setMinutes(String(d.settings.callback_minutes));
    setEmails((d.settings.recipients.emails ?? []).join("\n"));
    setPhones((d.settings.recipients.extensions ?? []).join(", "));
    setWebhook(d.settings.recipients.webhook ?? true);
  });

  const save = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      await api.put(`/emergency/sites/${siteId}`, {
        attested,
        responder_extension_id: responder || null,
        clear_responder: !responder,
        callback_minutes: Number(minutes),
        recipients: {
          emails: emails.split(/[\n,;]/).map((e) => e.trim()).filter(Boolean),
          extensions: phones.split(/[\n,;]/).map((e) => e.trim()).filter(Boolean),
          webhook,
        },
      });
      toast.success("Emergency settings saved");
      detail.reload();
      onChanged();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const testNotification = async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; results: Record<string, { state?: string; error?: string }> }>(`/emergency/sites/${siteId}/test-notification`);
      const parts = Object.entries(r.results).map(([k, v]) => `${k}: ${typeof v === "object" && v && "state" in v ? v.state : JSON.stringify(v)}`).join(", ");
      (r.ok ? toast.success : toast.error)("Notification test", parts || "No recipient is configured.");
      detail.reload();
      onChanged();
    } catch (err) {
      toast.error("Notification test failed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const recordTest = async (succeeded: boolean) => {
    if (!siteId || !testResult.trim()) return;
    setBusy(true);
    try {
      await api.post(`/emergency/sites/${siteId}/test-call`, { result: testResult.trim(), succeeded });
      toast.success(succeeded ? "Test call recorded" : "Failed test recorded");
      setTestResult("");
      detail.reload();
      onChanged();
    } catch (err) {
      toast.error("Could not record the test call", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const d = detail.data;
  const siteExts = extensions.data?.items ?? [];
  return (
    <Dialog open={!!siteId} onClose={onClose} title={d ? `Emergency calling: ${d.name}` : "Emergency calling"} size="lg" busy={busy}
      footer={<><Button onClick={onClose} disabled={busy}>Close</Button>{manage ? <Button variant="primary" onClick={save} loading={busy}>Save</Button> : null}</>}>
      {detail.error ? <ErrorState compact error={detail.error} onRetry={detail.reload} /> : !d ? <LoadingState /> : (
        <div className="stack stack--sm">
          <StatusBadge status={d.readiness.ready ? "ok" : "degraded"} label={d.readiness.ready ? "Ready (per Veyra's checks)" : "Not ready"} />
          <ul className="stack stack--xs" style={{ margin: 0, paddingLeft: "1.2em" }}>
            {d.readiness.checks.map((c) => (
              <li key={c.key}><StatusBadge status={c.ok ? "ok" : c.advisory ? "degraded" : "failed"} label={c.advisory && !c.ok ? `${c.label} (advice)` : c.label} />{c.detail ? <span className="subtle"> · {c.detail}</span> : null}</li>
            ))}
          </ul>
          <Callout tone="neutral">{d.disclaimer}</Callout>
          <dl className="dl">
            <dt>Emergency caller ID (ELIN)</dt><dd>{d.settings.emergency_caller_id_number ?? <span className="subtle">set on the site</span>}</dd>
            <dt>Civic address</dt><dd>{d.settings.address ?? <span className="subtle">set on the site</span>}</dd>
          </dl>
          <Checkbox label="This address is registered with the carrier's E911 service for the ELIN above" checked={attested} disabled={!manage}
            onChange={(e) => setAttested(e.target.checked)} description={d.settings.attested_at ? `Attested by ${d.settings.attested_by} on ${formatDateTime(d.settings.attested_at)}` : "Your name and the date are recorded."} />
          <div className="grid grid--2">
            <SelectField label="Responder extension" value={responder} disabled={!manage} placeholder="None"
              help="Rings on a PSAP callback when the caller cannot be found or the window has passed."
              options={siteExts.map((e) => ({ value: e.id, label: `${e.number} — ${e.display_name}` }))} onChange={(e) => setResponder(e.target.value)} />
            <TextField label="Callback window (minutes)" type="number" min={1} max={1440} value={minutes} disabled={!manage} onChange={(e) => setMinutes(e.target.value)} />
          </div>
          <TextArea label="Notify by email" rows={2} value={emails} disabled={!manage} onChange={(e) => setEmails(e.target.value)} placeholder="office@district.org" help="One address per line; needs Settings → Email." />
          <TextField label="Ring these extensions" value={phones} disabled={!manage} onChange={(e) => setPhones(e.target.value)} placeholder="1000, 1001" help="Responder phones ring with the caller's extension as the name and hear it read out." />
          <Checkbox label="Send the emergency.call webhook" checked={webhook} disabled={!manage} onChange={(e) => setWebhook(e.target.checked)} />
          {manage ? <Button onClick={testNotification} loading={busy}>Test the notification now</Button> : null}
          <Card title="Carrier test call">
            <div className="stack stack--sm">
              <p className="subtle">{d.settings.last_test_at ? `Last successful test ${formatDateTime(d.settings.last_test_at)}: ${d.settings.last_test_result}` : d.settings.last_test_result ?? "No test call recorded. Coordinate a 933 or 911 test with the carrier and record what the PSAP read back."}</p>
              {manage ? (
                <>
                  <TextField label="Result" value={testResult} onChange={(e) => setTestResult(e.target.value)} placeholder="933 read back 1 Example St, Exampleville" />
                  <span className="row" style={{ gap: 6 }}>
                    <Button onClick={() => recordTest(true)} disabled={!testResult.trim()} loading={busy}>Record as passed</Button>
                    <Button variant="danger" onClick={() => recordTest(false)} disabled={!testResult.trim()} loading={busy}>Record as failed</Button>
                  </span>
                </>
              ) : null}
            </div>
          </Card>
          {d.calls.length ? (
            <Card title="Recent emergency calls" flush>
              <DataTable columns={callColumns} rows={d.calls} rowKey={(c) => c.id} caption="Emergency calls" />
            </Card>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

const callColumns: Column<EmergencyCallRow>[] = [
  { key: "when", header: "When", render: (c) => <span>{formatDateTime(c.occurred_at)}{c.kind === "test" ? <Badge tone="neutral">test</Badge> : <Badge tone="danger">live</Badge>}</span> },
  { key: "from", header: "From", render: (c) => <span className="mono">{c.extension_number}</span> },
  { key: "to", header: "Dialled", render: (c) => <span className="mono">{c.number}</span> },
  { key: "loc", header: "Location", render: (c) => <span className="subtle">{c.location ?? "—"}</span> },
  { key: "notified", header: "Notified", render: (c) => Object.entries(c.notifications).map(([k, v]) => <Badge key={k} tone={JSON.stringify(v).includes("failed") ? "danger" : "ok"}>{k}</Badge>) },
];

export default function EmergencyPage() {
  const overview = useApiData<{ sites: EmergencySiteRow[]; ready: number; disclaimer: string }>("/emergency/sites");
  const calls = useApiData<EmergencyCallRow[]>("/emergency/calls", { limit: 50 });
  const [open, setOpen] = useState<string | null>(null);
  const columns: Column<EmergencySiteRow>[] = [
    { key: "name", header: "Site", render: (s) => <span><span className="table__primary" style={{ display: "block" }}>{s.name}</span><span className="table__secondary">{s.extensions} extension{s.extensions === 1 ? "" : "s"} · ELIN {s.elin ?? "—"}</span></span> },
    { key: "ready", header: "Readiness", render: (s) => <StatusBadge status={s.ready ? "ok" : "degraded"} label={s.ready ? "ready" : `${s.missing.length} missing`} /> },
    { key: "missing", header: "Missing", render: (s) => <span className="subtle">{s.missing.join("; ") || "—"}</span> },
    { key: "calls", header: "Calls", render: (s) => s.calls },
    { key: "actions", header: "", render: (s) => <Button size="sm" onClick={() => setOpen(s.id)}>Open</Button> },
  ];
  const o = overview.data;
  return (
    <div className="stack">
      <PageHeader title="Emergency calling" description="Readiness per site: an emergency route, a registered ELIN and address, locations on every phone, on-site notification, and a test call with the carrier. Veyra checks the data; the operator validates with the carrier." />
      {o ? <Callout tone={o.ready === o.sites.length && o.sites.length ? "ok" : "warn"} title={`${o.ready} of ${o.sites.length} site${o.sites.length === 1 ? "" : "s"} ready`}>{o.disclaimer}</Callout> : null}
      <Card title="Sites" flush>
        {overview.error ? <ErrorState compact error={overview.error} onRetry={overview.reload} /> : !o ? <LoadingState /> : (
          <DataTable columns={columns} rows={o.sites} rowKey={(s) => s.id} caption="Sites" empty={<EmptyState compact icon="alert" title="No sites">Create sites under Organizations → Sites with their civic address and ELIN.</EmptyState>} />
        )}
      </Card>
      <Card title="Emergency calls" flush actions={<Button size="sm" icon="refresh" onClick={calls.reload} loading={calls.loading && !!calls.data}>Refresh</Button>}>
        {calls.error ? <ErrorState compact error={calls.error} onRetry={calls.reload} /> : (
          <DataTable columns={callColumns} rows={calls.data ?? []} rowKey={(c) => c.id} caption="Emergency calls" empty={<EmptyState compact icon="clock" title="No emergency calls">Live and test calls are listed here with who was notified; {formatRelative(new Date().toISOString())}.</EmptyState>} />
        )}
      </Card>
      <SiteDialog siteId={open} onClose={() => setOpen(null)} onChanged={overview.reload} />
    </div>
  );
}
