// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import {
  curlExample,
  DeliveriesDialog,
  IntegrationDialog,
  SecretDialog,
  WebhookDialog,
} from "@/components/integrations/IntegrationDialogs";
import { Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, TabPanel, Tabs, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { IntegrationOut, IntegrationTokenOut, WebhookDeliveryOut, WebhookOut, WebhookSecretOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function TokensTab() {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("integrations.write");
  const list = useApiData<IntegrationOut[]>("/integrations");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<IntegrationOut | undefined>();
  const [shown, setShown] = useState<IntegrationTokenOut | null>(null);
  const [rotating, setRotating] = useState<IntegrationOut | undefined>();
  const [deleting, setDeleting] = useState<IntegrationOut | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const origin = typeof window !== "undefined" ? window.location.origin : "https://…";

  const rotate = async () => {
    if (!rotating) return;
    setBusy(true);
    setError(null);
    try {
      setShown(await api.post<IntegrationTokenOut>(`/integrations/${rotating.id}/rotate`));
      setRotating(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/integrations/${deleting.id}`);
      toast.success(`"${deleting.name}" revoked`, "Its token stopped working.");
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<IntegrationOut>[] = [
    { key: "name", header: "Integration", render: (i) => <span><span className="table__primary" style={{ display: "block" }}>{i.name}</span><span className="table__secondary">by {i.created_by}</span></span> },
    { key: "scopes", header: "Allowed to", render: (i) => <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{i.scopes.map((s) => <Badge key={s} tone="neutral">{s}</Badge>)}</span> },
    { key: "from", header: "From", render: (i) => i.allowed_networks.length ? <span className="mono">{i.allowed_networks.join(", ")}</span> : <span className="subtle">Any address</span> },
    { key: "used", header: "Last used", render: (i) => i.last_used_at ? <span>{formatRelative(i.last_used_at)}<span className="table__secondary mono" style={{ display: "block" }}>{i.last_used_ip}</span></span> : <span className="subtle">Never</span> },
    { key: "expires", header: "Expires", render: (i) => i.expired ? <Badge tone="danger">Expired</Badge> : i.expires_at ? formatDateTime(i.expires_at) : <span className="subtle">Never</span> },
    ...(editable ? [{ key: "actions", header: "", render: (i: IntegrationOut) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" icon="refresh" onClick={(e) => { e.stopPropagation(); setRotating(i); }}>New token</Button><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(i); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" aria-label={`Revoke ${i.name}`} onClick={(e) => { e.stopPropagation(); setDeleting(i); }} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted" style={{ margin: 0 }}>Tokens for other systems: a door controller that sends a page, a script that reads the call history. Each can do only what it is allowed to.</p>
        {editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New token</Button> : null}
      </div>
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(i) => i.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Integration tokens"
          onRowClick={editable ? (i) => setEditing(i) : undefined} rowLabel={(i) => `Edit ${i.name}`}
          empty={<EmptyState icon="key" title="No integration tokens">{editable ? "Create one for each system that calls Veyra, so each can be revoked on its own." : null}</EmptyState>} />
      </Card>
      <IntegrationDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={(i) => { if ("token" in i) setShown(i); list.reload(); }} />
      <IntegrationDialog open={!!editing} integration={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <SecretDialog value={shown?.token ?? null} title={shown ? `Token for "${shown.name}"` : ""} onClose={() => setShown(null)}>
        <p className="subtle">Send it as a bearer token. For example, to start a recorded page:</p>
        <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>{shown ? curlExample(origin, shown.token) : ""}</pre>
      </SecretDialog>
      <ConfirmDialog open={!!rotating} title={`New token for "${rotating?.name ?? ""}"?`} confirmLabel="Create new token" busy={busy} error={error} onConfirm={rotate} onCancel={() => { setRotating(undefined); setError(null); }}>
        <p>The current token stops working at once. Update the other system with the new one.</p>
      </ConfirmDialog>
      <ConfirmDialog open={!!deleting} title={`Revoke "${deleting?.name ?? ""}"?`} confirmLabel="Revoke" tone="danger" busy={busy} error={error} onConfirm={remove} onCancel={() => { setDeleting(undefined); setError(null); }}>
        <p>Its token stops working at once.</p>
      </ConfirmDialog>
    </div>
  );
}

function WebhooksTab() {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("webhooks.write");
  const list = useApiData<WebhookOut[]>("/webhooks");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<WebhookOut | undefined>();
  const [viewing, setViewing] = useState<WebhookOut | null>(null);
  const [shown, setShown] = useState<WebhookSecretOut | null>(null);
  const [deleting, setDeleting] = useState<WebhookOut | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const test = async (w: WebhookOut) => {
    setTesting(w.id);
    try {
      const d = await api.post<WebhookDeliveryOut>(`/webhooks/${w.id}/test`);
      if (d.status === "delivered") toast.success(`${w.name} answered`, `HTTP ${d.response_code} in ${d.duration_ms} ms.`);
      else toast.error(`${w.name} did not accept the test`, d.error ?? "");
      list.reload();
    } catch (err) {
      toast.error("Test failed", errorMessage(err));
    } finally {
      setTesting(null);
    }
  };
  const rotate = async (w: WebhookOut) => {
    try {
      setShown(await api.post<WebhookSecretOut>(`/webhooks/${w.id}/rotate-secret`));
    } catch (err) {
      toast.error("Could not create a new secret", errorMessage(err));
    }
  };
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/webhooks/${deleting.id}`);
      toast.success(`"${deleting.name}" removed`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<WebhookOut>[] = [
    { key: "name", header: "Webhook", render: (w) => <span><span className="table__primary" style={{ display: "block" }}>{w.name}</span><span className="table__secondary mono">{hostOf(w.url)}</span></span> },
    { key: "events", header: "Events", render: (w) => <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{w.events.map((e) => <Badge key={e} tone="neutral">{e}</Badge>)}</span> },
    { key: "last", header: "Last delivery", render: (w) => w.last_delivery_at ? <span>{formatRelative(w.last_delivery_at)}{w.pending ? <span className="table__secondary" style={{ display: "block" }}>{w.pending} waiting</span> : null}</span> : <span className="subtle">None yet</span> },
    { key: "status", header: "Status", render: (w) => !w.enabled ? <Badge tone="neutral">{w.disabled_reason ? "Turned off" : "Disabled"}</Badge> : w.last_status === "failed" ? <Badge tone="danger" icon="alert">Failing{w.failing_since ? ` since ${formatRelative(w.failing_since)}` : ""}</Badge> : w.last_status === "delivered" ? <Badge tone="ok">OK</Badge> : <Badge tone="neutral">Waiting</Badge> },
    { key: "actions", header: "", render: (w: WebhookOut) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
      <Button size="sm" onClick={(e) => { e.stopPropagation(); setViewing(w); }}>Deliveries</Button>
      {editable ? <><Button size="sm" loading={testing === w.id} onClick={(e) => { e.stopPropagation(); void test(w); }}>Send test</Button><Button size="sm" onClick={(e) => { e.stopPropagation(); void rotate(w); }}>New secret</Button><Button size="sm" variant="ghost" icon="trash" aria-label={`Remove ${w.name}`} onClick={(e) => { e.stopPropagation(); setDeleting(w); }} /></> : null}
    </span> },
  ];

  return (
    <div className="stack">
      <div className="row row--between">
        <p className="muted" style={{ margin: 0 }}>Signed messages to other systems when calls ring or end, voicemail arrives, pages and bells go out, alerts change or phones register.</p>
        {editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New webhook</Button> : null}
      </div>
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(w) => w.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Webhooks"
          onRowClick={editable ? (w) => setEditing(w) : undefined} rowLabel={(w) => `Edit ${w.name}`}
          empty={<EmptyState icon="external" title="No webhooks">{editable ? "Add the address of the system that should hear about events." : null}</EmptyState>} />
      </Card>
      <Card title="Checking the signature">
        <p className="subtle">Each message carries <span className="mono">Veyra-Signature: t=&lt;time&gt;,v1=&lt;HMAC-SHA256&gt;</span> computed with the webhook&apos;s secret over <span className="mono">&lt;time&gt;.&lt;body&gt;</span>. Reject messages older than five minutes, and ignore repeated <span className="mono">Veyra-Delivery</span> ids. After a new secret, messages carry both signatures for a day.</p>
        <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>{`import hashlib, hmac, time

def valid(secret: str, header: str, body: bytes) -> bool:
    f = [p.split("=", 1) for p in header.split(",")]
    t = next(v for k, v in f if k == "t")
    if abs(time.time() - int(t)) > 300:
        return False
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return any(k == "v1" and hmac.compare_digest(v, mac) for k, v in f)`}</pre>
      </Card>
      <WebhookDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={(w) => { if ("secret" in w) setShown(w); list.reload(); }} />
      <WebhookDialog open={!!editing} webhook={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <DeliveriesDialog webhook={viewing} onClose={() => setViewing(null)} />
      <SecretDialog value={shown?.secret ?? null} title={shown ? `Signing secret of "${shown.name}"` : ""} onClose={() => setShown(null)}>
        <p className="subtle">Give it to the receiving system so it can check that messages really come from Veyra.</p>
      </SecretDialog>
      <ConfirmDialog open={!!deleting} title={`Remove "${deleting?.name ?? ""}"?`} confirmLabel="Remove" tone="danger" busy={busy} error={error} onConfirm={remove} onCancel={() => { setDeleting(undefined); setError(null); }}>
        <p>Messages waiting for it are dropped.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function IntegrationsPage() {
  const { can } = useSession();
  const tabs = [
    ...(can("integrations.read") ? [{ id: "tokens", label: "Tokens" }] : []),
    ...(can("webhooks.read") ? [{ id: "webhooks", label: "Webhooks" }] : []),
  ];
  const [chosen, setActive] = useState("");
  const active = tabs.some((t) => t.id === chosen) ? chosen : (tabs[0]?.id ?? "");
  return (
    <div className="stack">
      <PageHeader title="Integrations" description="Connect Veyra to the systems around it: tokens for systems that call Veyra, webhooks for systems Veyra tells about events." />
      {tabs.length > 1 ? <Tabs tabs={tabs} active={active} onChange={setActive} idBase="integrations" /> : null}
      <TabPanel idBase="integrations" id="tokens" active={active}><TokensTab /></TabPanel>
      <TabPanel idBase="integrations" id="webhooks" active={active}><WebhooksTab /></TabPanel>
    </div>
  );
}
