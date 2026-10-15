// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useMemo, useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Badge, Button, Callout, Checkbox, Dialog, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { IntegrationOut, IntegrationScope, IntegrationTokenOut, WebhookDeliveryOut, WebhookEventDef, WebhookOut, WebhookSecretOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** "10.0.0.0/8, 192.168.1.20" or one per line. */
export function parseList(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean))];
}

/** Group the event catalog for the checkbox list, in catalog order. */
export function groupEvents(events: WebhookEventDef[]): { group: string; events: WebhookEventDef[] }[] {
  const out: { group: string; events: WebhookEventDef[] }[] = [];
  for (const e of events) {
    let g = out.find((x) => x.group === e.group);
    if (!g) out.push((g = { group: e.group, events: [] }));
    g.events.push(e);
  }
  return out;
}

function OrgPicker({ open, value, onChange, error }: { open: boolean; value: string; onChange: (v: string) => void; error?: string }) {
  const { organizations } = useOrganizationOptions(open);
  if (organizations.length <= 1) return null;
  return <SelectField label="Organization" required value={value} error={error} placeholder="Choose an organization" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => onChange(e.target.value)} />;
}

function useEffectiveOrg(open: boolean, chosen: string): string {
  const { organizations } = useOrganizationOptions(open);
  return chosen || (organizations.length === 1 ? organizations[0]!.id : "");
}

/** Shown once after creating or rotating: the token or signing secret. */
export function SecretDialog({ value, title, onClose, children }: { value: string | null; title: string; onClose: () => void; children?: React.ReactNode }) {
  return (
    <Dialog open={!!value} onClose={onClose} title={title} description="Copy it now: Veyra stores only a fingerprint and cannot show it again."
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <div className="stack stack--sm">
        <div className="row" style={{ gap: 8 }}>
          <code className="mono" style={{ wordBreak: "break-all", flex: 1 }}>{value}</code>
          {value ? <CopyButton text={value} /> : null}
        </div>
        {children}
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- tokens

export function IntegrationDialog({ open, onClose, integration, onSaved }: { open: boolean; onClose: () => void; integration?: IntegrationOut; onSaved: (i: IntegrationOut | IntegrationTokenOut) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const scopes = useApiData<IntegrationScope[]>(open ? "/integrations/scopes" : null);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [networks, setNetworks] = useState("");
  const [expires, setExpires] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = useEffectiveOrg(open && !integration, integration?.organization_id ?? org);

  useOnChange(open, () => {
    if (!open) return;
    setOrg(integration?.organization_id ?? session?.user.home_organization_id ?? "");
    setName(integration?.name ?? "");
    setChosen(integration?.scopes ?? []);
    setNetworks((integration?.allowed_networks ?? []).join(", "));
    setExpires(integration?.expires_at ? integration.expires_at.slice(0, 10) : "");
    errors.clear();
  });

  const toggle = (key: string, on: boolean) => setChosen((c) => (on ? [...new Set([...c, key])] : c.filter((k) => k !== key)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { name: name.trim(), scopes: chosen, allowed_networks: parseList(networks), expires_at: expires ? `${expires}T23:59:59Z` : null };
      const saved = integration
        ? await api.put<IntegrationOut>(`/integrations/${integration.id}`, body)
        : await api.post<IntegrationTokenOut>("/integrations", { organization_id: effectiveOrg, ...body });
      if (integration) toast.success("Integration saved", "The token keeps working with the new permissions.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={integration ? `Edit "${integration.name}"` : "New integration token"}
      description="A token for another system, such as a door controller that starts a page. It belongs to the organization, not to a person, and can do only what you tick here."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="integration-form" loading={busy} disabled={!name.trim() || chosen.length === 0 || !effectiveOrg}>{integration ? "Save changes" : "Create token"}</Button></>}>
      <form id="integration-form" className="stack stack--sm" onSubmit={submit}>
        {!integration ? <OrgPicker open={open} value={effectiveOrg} onChange={setOrg} error={errors.fields.organization_id} /> : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Door controller, main entrance" onChange={(e) => setName(e.target.value)} />
        <fieldset className="stack stack--sm" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label">Allowed to</legend>
          {(scopes.data ?? []).map((s) => (
            <Checkbox key={s.key} label={s.description} description={<span className="mono">{s.key}</span>} checked={chosen.includes(s.key)} onChange={(e) => toggle(s.key, e.target.checked)} />
          ))}
          {errors.fields.scopes ? <span className="field__error">{errors.fields.scopes}</span> : null}
        </fieldset>
        <TextField label="Only from these addresses (optional)" value={networks} error={errors.fields.allowed_networks} placeholder="192.168.10.25, 10.20.0.0/16" help="Addresses or networks; empty allows any address." onChange={(e) => setNetworks(e.target.value)} />
        <TextField label="Expires (optional)" type="date" value={expires} error={errors.fields.expires_at} help="Empty: until revoked." onChange={(e) => setExpires(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export function curlExample(origin: string, token: string): string {
  return `curl -X POST ${origin}/api/v1/pages/<page id>/send \\\n     -H "Authorization: Bearer ${token}"`;
}

// ----------------------------------------------------------------- webhooks

export function WebhookDialog({ open, onClose, webhook, onSaved }: { open: boolean; onClose: () => void; webhook?: WebhookOut; onSaved: (w: WebhookOut | WebhookSecretOut) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const catalog = useApiData<WebhookEventDef[]>(open ? "/webhooks/events" : null);
  const groups = useMemo(() => groupEvents(catalog.data ?? []), [catalog.data]);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [allowHttp, setAllowHttp] = useState(false);
  const [events, setEvents] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = useEffectiveOrg(open && !webhook, webhook?.organization_id ?? org);

  useOnChange(open, () => {
    if (!open) return;
    setOrg(webhook?.organization_id ?? session?.user.home_organization_id ?? "");
    setName(webhook?.name ?? "");
    setUrl(webhook?.url ?? "");
    setAllowHttp(webhook?.allow_http ?? false);
    setEvents(webhook?.events ?? []);
    setEnabled(webhook?.enabled ?? true);
    errors.clear();
  });

  const toggle = (key: string, on: boolean) => setEvents((c) => (on ? [...new Set([...c, key])] : c.filter((k) => k !== key)));
  const isHttp = url.trim().toLowerCase().startsWith("http://");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { name: name.trim(), url: url.trim(), allow_http: allowHttp, events, enabled };
      const saved = webhook
        ? await api.put<WebhookOut>(`/webhooks/${webhook.id}`, body)
        : await api.post<WebhookSecretOut>("/webhooks", { organization_id: effectiveOrg, ...body });
      if (webhook) toast.success("Webhook saved");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={webhook ? `Edit "${webhook.name}"` : "New webhook"}
      description="Veyra posts a signed JSON message to this address when the chosen events happen."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="webhook-form" loading={busy} disabled={!name.trim() || !url.trim() || events.length === 0 || !effectiveOrg}>{webhook ? "Save changes" : "Create webhook"}</Button></>}>
      <form id="webhook-form" className="stack stack--sm" onSubmit={submit}>
        {!webhook ? <OrgPicker open={open} value={effectiveOrg} onChange={setOrg} error={errors.fields.organization_id} /> : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front office screen" onChange={(e) => setName(e.target.value)} />
        <TextField label="Address" required type="url" value={url} error={errors.fields.url} placeholder="https://hooks.example.org/veyra" help="Addresses on this server itself are refused; addresses on your network are fine." onChange={(e) => setUrl(e.target.value)} />
        {isHttp || allowHttp ? <Checkbox label="Allow unencrypted HTTP" description="For a device on your network that has no HTTPS. The message is signed but readable on the way." checked={allowHttp} onChange={(e) => setAllowHttp(e.target.checked)} /> : null}
        <fieldset className="stack stack--sm" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label">Events</legend>
          {groups.map((g) => {
            const wildcard = `${g.events[0]?.name.split(".")[0] ?? ""}.*`;
            const sameStem = g.events.every((e) => e.name.startsWith(wildcard.slice(0, -1)));
            return (
              <div key={g.group} className="stack stack--sm">
                <strong>{g.group}</strong>
                {sameStem && g.events.length > 1 ? <Checkbox label={`Every ${g.group.toLowerCase()} event`} description={<span className="mono">{wildcard}</span>} checked={events.includes(wildcard)} onChange={(e) => toggle(wildcard, e.target.checked)} /> : null}
                {g.events.map((ev) => (
                  <Checkbox key={ev.name} label={<>{ev.description}{ev.live ? <> <Badge tone="neutral">live</Badge></> : null}</>} description={<span className="mono">{ev.name}</span>}
                    disabled={sameStem && events.includes(wildcard)} checked={events.includes(ev.name) || (sameStem && events.includes(wildcard))} onChange={(e) => toggle(ev.name, e.target.checked)} />
                ))}
              </div>
            );
          })}
          {errors.fields.events ? <span className="field__error">{errors.fields.events}</span> : null}
        </fieldset>
        <p className="subtle">Live events (a phone ringing, a call answered) are sent once and not retried; the others are retried for about nine hours.</p>
        {webhook ? <Switch label="Enabled" description={webhook.disabled_reason ?? "A disabled webhook queues nothing."} checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export function DeliveriesDialog({ webhook, onClose }: { webhook: WebhookOut | null; onClose: () => void }) {
  const toast = useToast();
  const list = useApiData<WebhookDeliveryOut[]>(webhook ? `/webhooks/${webhook.id}/deliveries` : null);
  const [open, setOpen] = useState<string | null>(null);
  const redeliver = async (d: WebhookDeliveryOut) => {
    if (!webhook) return;
    try {
      await api.post(`/webhooks/${webhook.id}/deliveries/${d.id}/redeliver`);
      toast.success("Queued again", "The worker sends it within a few seconds.");
      list.reload();
    } catch (err) {
      toast.error("Could not queue", errorMessage(err));
    }
  };
  return (
    <Dialog open={!!webhook} onClose={onClose} size="lg" title={webhook ? `Deliveries of "${webhook.name}"` : ""} description="The last 100 messages, kept for 7 days."
      footer={<><Button icon="refresh" onClick={list.reload}>Refresh</Button><Button variant="primary" onClick={onClose}>Close</Button></>}>
      {!list.data ? <p className="muted">Loading…</p> : list.data.length === 0 ? <p className="muted">Nothing sent yet.</p> : (
        <ul className="list-plain">
          {list.data.map((d) => (
            <li key={d.id} className="stack stack--sm" style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div className="row row--between" style={{ gap: 8 }}>
                <span className="row" style={{ gap: 8 }}>
                  <Badge tone={d.status === "delivered" ? "ok" : d.status === "failed" ? "danger" : "warn"}>{d.status}</Badge>
                  <span className="mono">{d.event}</span>
                  <span className="subtle">{formatDateTime(d.created_at)}</span>
                </span>
                <span className="row" style={{ gap: 4 }}>
                  <span className="subtle">{d.response_code ? `HTTP ${d.response_code}` : d.error ?? ""}{d.duration_ms != null ? ` · ${d.duration_ms} ms` : ""}{d.attempts > 1 ? ` · ${d.attempts} attempts` : ""}</span>
                  <Button size="sm" variant="ghost" onClick={() => setOpen(open === d.id ? null : d.id)}>{open === d.id ? "Hide" : "Details"}</Button>
                  {d.status !== "pending" ? <Button size="sm" onClick={() => void redeliver(d)}>Redeliver</Button> : null}
                </span>
              </div>
              {d.status === "pending" && d.attempts > 0 ? <span className="subtle">Next attempt {formatDateTime(d.next_attempt_at)}{d.error ? ` (last: ${d.error})` : ""}</span> : null}
              {open === d.id ? <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(d.payload, null, 2)}{d.response_excerpt ? `\n\nResponse:\n${d.response_excerpt}` : ""}</pre> : null}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
