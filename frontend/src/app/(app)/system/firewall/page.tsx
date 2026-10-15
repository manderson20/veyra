// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { MetricCard } from "@/components/common/Metric";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  IconButton,
  PageHeader,
  Pagination,
  SelectField,
  Switch,
  TabPanel,
  Tabs,
  TextArea,
  TextField,
  useToast,
  type Column,
  type Tone,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type {
  FirewallBan,
  FirewallEvent,
  FirewallFeed,
  FirewallPolicy,
  FirewallRule,
  FirewallService,
  FirewallSettings,
  FirewallStatus,
  Page,
} from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

const LIMIT = 50;
const SERVICES: { id: FirewallService; label: string; help: string }[] = [
  { id: "sip", label: "SIP signaling", help: "Phones and trunks registering and placing calls." },
  { id: "rtp", label: "Call audio (RTP)", help: "The media ports of every call." },
  { id: "web", label: "Web interface and provisioning", help: "HTTPS (and HTTP) for browsers and phones." },
  { id: "ssh", label: "SSH", help: "Remote administration of the server itself." },
];
const ORIGIN: Record<FirewallRule["origin"], { label: string; tone: Tone }> = {
  manual: { label: "Manual", tone: "neutral" },
  server: { label: "This server", tone: "info" },
  sip_local_net: { label: "Local network", tone: "info" },
  trunk: { label: "Trunk", tone: "info" },
};
const SOURCE: Record<string, string> = {
  asterisk: "Phone system",
  auth: "Sign-in",
  provisioning: "Provisioning",
  nginx: "Web server",
};
const KIND: Record<string, string> = {
  sip_unknown_account: "Unknown SIP account",
  sip_bad_password: "Wrong SIP password",
  sip_acl: "SIP address not permitted",
  sip_bad_request: "Malformed SIP request",
  login_failed: "Failed sign-in",
  mfa_failed: "Wrong second factor",
  reset_invalid: "Invalid reset link",
  prov_unauthorized: "Provisioning refused",
  rate_limited: "Too many requests",
};
const EXPIRY = [
  { value: "", label: "Never" },
  { value: "60", label: "1 hour" },
  { value: "1440", label: "1 day" },
  { value: "10080", label: "7 days" },
  { value: "43200", label: "30 days" },
];

const kindLabel = (k: string) => KIND[k] ?? k;

function useCountdown(deadline: string | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!deadline) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [deadline]);
  if (!deadline) return null;
  return Math.max(0, Math.round((new Date(deadline).getTime() - now) / 1000));
}

// ------------------------------------------------------------------ overview

function Overview({ status, onAddress }: { status: FirewallStatus; onAddress: (a: string) => void }) {
  const sourceProblems = Object.entries(status.sources).filter(([, e]) => e);
  return (
    <div className="stack">
      <div className="grid grid--4">
        <MetricCard icon="shield" label="Firewall" value={status.enabled ? (status.applied ? "On" : "Starting") : "Off"}
          hint={status.enabled ? "Drops banned and blocked addresses" : "Nothing is blocked"} />
        <MetricCard icon="lock" label="Active bans" value={status.active_bans} />
        <MetricCard icon="alert" label="Suspicious events (24 h)" value={status.events_24h} />
        <MetricCard icon="history" label="Bans (24 h)" value={status.bans_24h} />
      </div>
      {sourceProblems.length ? (
        <Callout tone="warn" title="Some event sources cannot be read">
          {sourceProblems.map(([name, err]) => <div key={name}>{SOURCE[name === "nginx" ? "nginx" : "asterisk"]}: {err}</div>)}
        </Callout>
      ) : null}
      <Card title="Most active addresses (24 h)" subtitle="Click an address to see its events." flush>
        <DataTable
          columns={[
            { key: "address", header: "Address", render: (r) => <span className="mono">{r.address}</span> },
            { key: "events", header: "Events", render: (r) => r.events },
          ]}
          rows={status.top_addresses} rowKey={(r) => r.address} onRowClick={(r) => onAddress(r.address)}
          rowLabel={(r) => `Events from ${r.address}`} caption="Most active addresses"
          empty={<EmptyState icon="shield" title="Quiet" compact>No suspicious events in the last 24 hours.</EmptyState>} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------- bans

function Bans({ onChanged }: { onChanged: () => void }) {
  const toast = useToast();
  const [active, setActive] = useState("true");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const list = useApiData<Page<FirewallBan>>("/firewall/bans", { active: active || undefined, limit: LIMIT, offset });

  const act = async (ban: FirewallBan, what: "lift" | "block") => {
    setBusy(ban.id);
    try {
      await api.post(`/firewall/bans/${ban.id}/${what}`);
      toast.success(what === "lift" ? `Ban on ${ban.address} lifted` : `${ban.address} blocked permanently`);
      list.reload();
      onChanged();
    } catch (err) {
      toast.error("Not changed", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const [now] = useState(() => Date.now());
  const columns: Column<FirewallBan>[] = [
    { key: "address", header: "Address", render: (b) => <span className="mono">{b.address}</span> },
    { key: "reason", header: "Reason", render: (b) => <><span>{b.reason}</span><span className="subtle" style={{ display: "block" }}>{SOURCE[b.source] ?? b.source}{b.offence > 1 ? ` · offence ${b.offence}` : ""}</span></> },
    { key: "when", header: "Banned", render: (b) => <span className="nowrap">{formatDateTime(b.banned_at)}</span> },
    {
      key: "until", header: "Until", render: (b) => b.lifted_at
        ? <Badge tone="neutral">Lifted{b.lifted_by ? ` by ${b.lifted_by}` : ""}</Badge>
        : new Date(b.expires_at).getTime() < now ? <Badge tone="neutral">Expired</Badge>
          : <span className="nowrap">{formatDateTime(b.expires_at)}</span>,
    },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (b) => !b.lifted_at && new Date(b.expires_at).getTime() > now ? (
        <span className="row" style={{ gap: 4 }}>
          <Button size="sm" loading={busy === b.id} onClick={() => act(b, "lift")}>Lift</Button>
          <Button size="sm" variant={b.offence >= 3 ? "danger" : "secondary"} disabled={busy === b.id} onClick={() => act(b, "block")}>Block permanently</Button>
        </span>
      ) : null,
    },
  ];
  return (
    <Card flush>
      <div className="table-toolbar">
        <div style={{ minWidth: 200 }}>
          <SelectField label={<span className="sr-only">Show</span>} value={active}
            options={[{ value: "true", label: "Active bans" }, { value: "false", label: "Past bans" }, { value: "", label: "All bans" }]}
            onChange={(e) => { setActive(e.target.value); setOffset(0); }} />
        </div>
      </div>
      <DataTable columns={columns} rows={list.data?.items} rowKey={(b) => b.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Bans" empty={<EmptyState icon="lock" title={active === "true" ? "No active bans" : "No bans"} compact />}
        pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
    </Card>
  );
}

// --------------------------------------------------------------------- rules

function RuleDialog({ open, onClose, onSaved, action }: { open: boolean; onClose: () => void; onSaved: () => void; action: "allow" | "block" }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [cidr, setCidr] = useState("");
  const [comment, setComment] = useState("");
  const [services, setServices] = useState<FirewallService[]>([]);
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setCidr(""); setComment(""); setServices([]); setExpiry(""); errors.clear();
    }
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.post("/firewall/rules", {
        action,
        cidr: cidr.trim(),
        comment: comment.trim() || null,
        services: action === "block" ? services : [],
        expires_at: expiry ? new Date(Date.now() + Number(expiry) * 60_000).toISOString() : null,
      });
      toast.success(action === "allow" ? "Added to the allow list" : "Blocked");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={action === "allow" ? "Allow an address or network" : "Block an address or network"}
      description={action === "allow"
        ? "Allowed addresses are never banned or blocked by Veyra, whatever their events say."
        : "Blocked addresses cannot reach this server (or only the chosen services). Allowed addresses are not affected."}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant={action === "block" ? "danger" : "primary"} type="submit" form="fw-rule-form" loading={busy} disabled={!cidr.trim()}>{action === "allow" ? "Allow" : "Block"}</Button></>}>
      <form id="fw-rule-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Address or network" required autoFocus value={cidr} error={errors.fields.cidr} placeholder="e.g. 203.0.113.7 or 10.20.0.0/16" onChange={(e) => setCidr(e.target.value)} />
        <TextField label="Comment" value={comment} error={errors.fields.comment} placeholder="Why, for whom" onChange={(e) => setComment(e.target.value)} />
        {action === "block" ? (
          <div className="field">
            <span className="field__label">Services</span>
            <p className="subtle">None ticked: every service.</p>
            {SERVICES.map((s) => (
              <Checkbox key={s.id} label={s.label} checked={services.includes(s.id)}
                onChange={(e) => setServices(e.target.checked ? [...services, s.id] : services.filter((x) => x !== s.id))} />
            ))}
          </div>
        ) : null}
        <SelectField label="Expires" value={expiry} options={EXPIRY} onChange={(e) => setExpiry(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function Rules({ onChanged }: { onChanged: () => void }) {
  const toast = useToast();
  const list = useApiData<FirewallRule[]>("/firewall/rules");
  const [adding, setAdding] = useState<"allow" | "block" | null>(null);
  const [removing, setRemoving] = useState<FirewallRule | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/firewall/rules/${removing.id}`);
      toast.success(`${removing.cidr} removed`);
      setRemoving(null);
      list.reload();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const columns: Column<FirewallRule>[] = [
    { key: "cidr", header: "Address or network", render: (r) => <span className="mono">{r.cidr}</span> },
    { key: "origin", header: "Source", render: (r) => <Badge tone={ORIGIN[r.origin].tone}>{ORIGIN[r.origin].label}</Badge> },
    { key: "services", header: "Services", render: (r) => r.services.length ? r.services.map((s) => SERVICES.find((x) => x.id === s)?.label ?? s).join(", ") : "All" },
    { key: "comment", header: "Comment", render: (r) => r.comment ?? <span className="subtle">—</span> },
    { key: "expires", header: "Expires", render: (r) => r.expires_at ? <span className="nowrap">{formatDateTime(r.expires_at)}</span> : "Never" },
    {
      key: "actions", header: <span className="sr-only">Actions</span>,
      render: (r) => r.origin === "manual" ? <IconButton size="sm" icon="trash" label={`Remove ${r.cidr}`} onClick={() => setRemoving(r)} /> : null,
    },
  ];
  const rows = list.data ?? [];
  return (
    <div className="stack">
      <Card title="Allow list" subtitle="Never banned or blocked. Entries marked This server, Local network and Trunk follow the configuration and are updated automatically."
        actions={<Button icon="plus" onClick={() => setAdding("allow")}>Allow</Button>} flush>
        <DataTable columns={columns} rows={list.data ? rows.filter((r) => r.action === "allow") : undefined} rowKey={(r) => r.id}
          loading={list.loading} error={list.error} onRetry={list.reload} caption="Allow list"
          empty={<EmptyState icon="shield" title="Nothing allowed yet" compact>Local networks from the SIP settings and trunk addresses appear here once the firewall service runs.</EmptyState>} />
      </Card>
      <Card title="Block list" subtitle="Dropped before anything else, unless allowed."
        actions={<Button icon="plus" variant="danger" onClick={() => setAdding("block")}>Block</Button>} flush>
        <DataTable columns={columns} rows={list.data ? rows.filter((r) => r.action === "block") : undefined} rowKey={(r) => r.id}
          loading={list.loading} error={list.error} onRetry={list.reload} caption="Block list"
          empty={<EmptyState icon="lock" title="Nothing blocked" compact />} />
      </Card>
      <RuleDialog open={adding !== null} action={adding ?? "allow"} onClose={() => setAdding(null)} onSaved={() => { list.reload(); onChanged(); }} />
      <ConfirmDialog open={removing !== null} title={`Remove ${removing?.cidr ?? ""}?`} confirmLabel="Remove" tone="danger" busy={busy} error={error}
        onConfirm={remove} onCancel={() => { setRemoving(null); setError(null); }}>
        <p>{removing?.action === "allow" ? "The address can be banned again if it misbehaves." : "The address can reach this server again."}</p>
      </ConfirmDialog>
    </div>
  );
}

// -------------------------------------------------------------------- events

function Events({ address, setAddress }: { address: string; setAddress: (a: string) => void }) {
  const [source, setSource] = useState("");
  const [wouldBan, setWouldBan] = useState(false);
  const [offset, setOffset] = useState(0);
  const list = useApiData<Page<FirewallEvent>>("/firewall/events", {
    address: address || undefined, source: source || undefined, would_ban: wouldBan ? true : undefined, limit: LIMIT, offset,
  });
  const columns: Column<FirewallEvent>[] = [
    { key: "at", header: "Time", render: (e) => <span className="nowrap">{formatDateTime(e.at)}</span> },
    { key: "address", header: "Address", render: (e) => <button type="button" className="link mono" onClick={() => { setAddress(e.address); setOffset(0); }}>{e.address}</button> },
    { key: "what", header: "Event", render: (e) => <><span>{kindLabel(e.kind)}{e.count > 1 ? ` ×${e.count}` : ""}</span><span className="subtle" style={{ display: "block" }}>{SOURCE[e.source] ?? e.source}{e.detail ? ` · ${e.detail}` : ""}</span></> },
    { key: "flag", header: <span className="sr-only">Note</span>, render: (e) => e.would_ban ? <Badge tone="warn">Allowed; would have been banned</Badge> : null },
  ];
  return (
    <Card flush>
      <div className="table-toolbar">
        <TextField label={<span className="sr-only">Address</span>} value={address} placeholder="Filter by address" onChange={(e) => { setAddress(e.target.value.trim()); setOffset(0); }} />
        <div style={{ minWidth: 180 }}>
          <SelectField label={<span className="sr-only">Source</span>} value={source} placeholder="All sources"
            options={Object.entries(SOURCE).map(([value, label]) => ({ value, label }))} onChange={(e) => { setSource(e.target.value); setOffset(0); }} />
        </div>
        <Checkbox label="Only allowed addresses that would have been banned" checked={wouldBan} onChange={(e) => { setWouldBan(e.target.checked); setOffset(0); }} />
      </div>
      <DataTable columns={columns} rows={list.data?.items} rowKey={(e) => e.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Suspicious events" empty={<EmptyState icon="shield" title="No matching events" compact />}
        pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
    </Card>
  );
}

// ------------------------------------------------------------------ settings

function FeedDialog({ open, onClose, onSaved, feed }: { open: boolean; onClose: () => void; onSaved: () => void; feed?: FirewallFeed }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"crowdsec" | "list">("list");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setName(feed?.name ?? ""); setKind(feed?.kind ?? "list"); setUrl(feed?.url ?? ""); setKey(""); setEnabled(feed?.is_enabled ?? true); errors.clear();
    }
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: Record<string, unknown> = { name: name.trim(), kind, url: url.trim(), is_enabled: enabled };
      if (kind === "crowdsec" && key) body.key = key;
      if (feed) await api.put(`/firewall/feeds/${feed.id}`, body);
      else await api.post("/firewall/feeds", body);
      toast.success(feed ? "Feed saved" : "Feed added", "The firewall service fetches it within a few seconds.");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={feed ? `Edit "${feed.name}"` : "Add a blocklist feed"}
      description="Addresses from a feed are dropped like bans; the allow list still wins."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="fw-feed-form" loading={busy} disabled={!name.trim() || !url.trim()}>{feed ? "Save" : "Add feed"}</Button></>}>
      <form id="fw-feed-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} onChange={(e) => setName(e.target.value)} />
        <SelectField label="Kind" value={kind} options={[{ value: "list", label: "Address list (one per line, HTTPS)" }, { value: "crowdsec", label: "CrowdSec local API (bouncer)" }]}
          onChange={(e) => setKind(e.target.value as "crowdsec" | "list")} />
        <TextField label="URL" required value={url} error={errors.fields.url} placeholder={kind === "crowdsec" ? "http://127.0.0.1:8080" : "https://www.spamhaus.org/drop/drop.txt"} onChange={(e) => setUrl(e.target.value)} />
        {kind === "crowdsec" ? (
          <TextField label="Bouncer key" type="password" value={key} error={errors.fields.key}
            help={feed?.has_key ? "Leave empty to keep the stored key." : "Create one with: sudo cscli bouncers add veyra"} onChange={(e) => setKey(e.target.value)} />
        ) : null}
        <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function Feeds() {
  const toast = useToast();
  const list = useApiData<FirewallFeed[]>("/firewall/feeds");
  const [editing, setEditing] = useState<FirewallFeed | "new" | null>(null);
  const [removing, setRemoving] = useState<FirewallFeed | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = async (f: FirewallFeed) => {
    try {
      await api.post(`/firewall/feeds/${f.id}/refresh`);
      toast.success(`${f.name} will be fetched within a few seconds`);
      list.reload();
    } catch (err) {
      toast.error("Not fetched", errorMessage(err));
    }
  };
  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await api.del(`/firewall/feeds/${removing.id}`);
      setRemoving(null);
      list.reload();
    } catch (err) {
      toast.error("Not removed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const columns: Column<FirewallFeed>[] = [
    { key: "name", header: "Feed", render: (f) => <><span>{f.name}</span><span className="subtle mono" style={{ display: "block" }}>{f.url}</span></> },
    { key: "kind", header: "Kind", render: (f) => (f.kind === "crowdsec" ? "CrowdSec" : "List") },
    {
      key: "state", header: "State", render: (f) => !f.is_enabled ? <Badge tone="neutral">Off</Badge>
        : f.last_status === "failed" ? <Badge tone="danger">{f.last_error ?? "Failed"}</Badge>
          : f.last_status === "pending" ? <Badge tone="info">Fetching</Badge>
            : <span>{f.entry_count} entries <span className="subtle">· {formatRelative(f.last_fetched_at)}</span></span>,
    },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (f) => (
        <span className="row" style={{ gap: 4 }}>
          <IconButton size="sm" icon="refresh" label={`Fetch ${f.name} now`} onClick={() => refresh(f)} />
          <IconButton size="sm" icon="settings" label={`Edit ${f.name}`} onClick={() => setEditing(f)} />
          <IconButton size="sm" icon="trash" label={`Remove ${f.name}`} onClick={() => setRemoving(f)} />
        </span>
      ),
    },
  ];
  return (
    <Card title="Blocklist feeds" subtitle="Optional: CrowdSec decisions or public lists such as Spamhaus DROP, refreshed every 10 minutes."
      actions={<Button icon="plus" onClick={() => setEditing("new")}>Add feed</Button>} flush>
      <DataTable columns={columns} rows={list.data} rowKey={(f) => f.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Blocklist feeds" empty={<EmptyState icon="download" title="No feeds" compact>Veyra&apos;s own bans work without any feed.</EmptyState>} />
      <FeedDialog open={editing !== null} feed={editing && editing !== "new" ? editing : undefined} onClose={() => setEditing(null)} onSaved={list.reload} />
      <ConfirmDialog open={removing !== null} title={`Remove ${removing?.name ?? ""}?`} confirmLabel="Remove" tone="danger" busy={busy}
        onConfirm={remove} onCancel={() => setRemoving(null)}>
        <p>Its addresses are no longer blocked.</p>
      </ConfirmDialog>
    </Card>
  );
}

function SettingsForm({ settings, status, onSaved }: { settings: FirewallSettings; status: FirewallStatus; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [form, setForm] = useState(settings);
  const [ssh, setSsh] = useState(settings.ssh_ports.join(", "));
  const [nets, setNets] = useState(settings.bootstrap_networks.join("\n"));
  const [busy, setBusy] = useState(false);
  const [confirmOn, setConfirmOn] = useState(false);
  useOnChange(settings, () => {
    setForm(settings);
    setSsh(settings.ssh_ports.join(", "));
    setNets(settings.bootstrap_networks.join("\n"));
  });
  const set = <K extends keyof FirewallSettings>(k: K, v: FirewallSettings[K]) => setForm({ ...form, [k]: v });

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      const saved = await api.put<FirewallSettings>("/firewall/settings", {
        enabled: form.enabled,
        policy: form.policy,
        ban_score: Number(form.ban_score),
        window_minutes: Number(form.window_minutes),
        ban_minutes: Number(form.ban_minutes),
        max_ban_days: Number(form.max_ban_days),
        weights: form.weights,
        ssh_ports: ssh.split(/[\s,]+/).filter(Boolean).map(Number),
        bootstrap_networks: nets.split(/[\s,]+/).filter(Boolean),
      });
      toast.success("Firewall settings saved", saved.pending_confirm ? "Confirm the new restrictions within 60 seconds or they are undone." : "Applied within a few seconds.");
      setConfirmOn(false);
      onSaved();
    } catch (err) {
      errors.set(err);
      setConfirmOn(false);
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form.enabled && !settings.enabled) setConfirmOn(true);
    else void save();
  };
  return (
    <form className="stack" onSubmit={submit}>
      <Card title="Firewall">
        <div className="stack stack--sm">
          <Switch label="Firewall on" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)}
            description="Bans attackers automatically and enforces the block list. Everything else keeps working as before." />
          {!status.your_address_allowed && status.your_address ? (
            <Callout tone="warn" title="Your address is not on the allow list">
              You are connected from <span className="mono">{status.your_address}</span>. Add it (or its network) to the allow list before limiting the web interface.
            </Callout>
          ) : null}
        </div>
      </Card>
      <Card title="Who may reach each service" subtitle="Limiting a service to the allow list must be confirmed within 60 seconds, or it is undone automatically.">
        <div className="stack stack--sm">
          {SERVICES.map((s) => (
            <SelectField key={s.id} label={s.label} help={s.id === "ssh" ? `${s.help} Make sure your own network is allowed before limiting it.` : s.help}
              value={form.policy[s.id]}
              options={[{ value: "anywhere", label: "Anyone not banned or blocked" }, { value: "allow_list_only", label: "Only the allow list" }]}
              onChange={(e) => set("policy", { ...form.policy, [s.id]: e.target.value as FirewallPolicy })} />
          ))}
          <TextField label="SSH ports" value={ssh} error={errors.fields.ssh_ports} help="Comma-separated; 22 unless sshd listens elsewhere." onChange={(e) => setSsh(e.target.value)} />
        </div>
      </Card>
      <Card title="Automatic bans" subtitle="Each suspicious event scores points against its address; reaching the score within the window bans it. Repeat offences double the ban.">
        <div className="grid grid--2">
          <TextField label="Score that bans" type="number" min={2} value={form.ban_score} error={errors.fields.ban_score} onChange={(e) => set("ban_score", Number(e.target.value))} />
          <TextField label="Window (minutes)" type="number" min={1} value={form.window_minutes} error={errors.fields.window_minutes} onChange={(e) => set("window_minutes", Number(e.target.value))} />
          <TextField label="First ban (minutes)" type="number" min={1} value={form.ban_minutes} error={errors.fields.ban_minutes} onChange={(e) => set("ban_minutes", Number(e.target.value))} />
          <TextField label="Longest ban (days)" type="number" min={1} value={form.max_ban_days} error={errors.fields.max_ban_days} onChange={(e) => set("max_ban_days", Number(e.target.value))} />
        </div>
        <details className="stack stack--sm" style={{ marginTop: 12 }}>
          <summary>Points per event</summary>
          <div className="grid grid--2">
            {Object.keys(KIND).map((k) => (
              <TextField key={k} label={kindLabel(k)} type="number" min={0} max={100} value={form.weights[k] ?? 1}
                onChange={(e) => set("weights", { ...form.weights, [k]: Number(e.target.value) })} />
            ))}
          </div>
        </details>
      </Card>
      <Card title="Phone bootstrap networks" subtitle="New phones fetch the Veyra certificate over plain HTTP only from these networks. Empty: the local networks of the SIP settings.">
        <TextArea label="Networks" rows={3} value={nets} error={errors.fields.bootstrap_networks} placeholder="e.g. 10.20.30.0/24 (the staging or voice VLAN)" onChange={(e) => setNets(e.target.value)} />
      </Card>
      {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="row"><Button variant="primary" type="submit" loading={busy}>Save settings</Button></div>
      <ConfirmDialog open={confirmOn} title="Turn the firewall on?" confirmLabel="Turn on" busy={busy} onConfirm={save} onCancel={() => setConfirmOn(false)}>
        <p>Addresses that keep failing to sign in or register will be banned for a while. Check that the allow list holds your phones&apos; networks, your trunks and the networks you administer from; allowed addresses are never banned.</p>
      </ConfirmDialog>
    </form>
  );
}

// ---------------------------------------------------------------------- page

export default function FirewallPage() {
  const toast = useToast();
  const [tab, setTab] = useState("overview");
  const [address, setAddress] = useState("");
  const status = useApiData<FirewallStatus>("/firewall/status");
  const settings = useApiData<FirewallSettings>("/firewall/settings");
  const remaining = useCountdown(status.data?.pending_confirm?.deadline);
  const reload = () => { status.reload(); settings.reload(); };

  // Keep the overview and the confirm countdown current.
  useEffect(() => {
    const t = window.setInterval(() => status.reload(), 15_000);
    return () => window.clearInterval(t);
  }, [status]);

  const confirm = async () => {
    try {
      await api.post("/firewall/confirm");
      toast.success("Restrictions kept");
      reload();
    } catch (err) {
      toast.error("Not confirmed", errorMessage(err));
    }
  };

  const s = status.data;
  return (
    <div className="stack">
      <PageHeader title="Firewall" description="Bans attackers automatically, blocks and allows addresses, and never locks out the allow list." />
      {s?.pending_confirm ? (
        <Callout tone="warn" title="Keep the new restrictions?">
          <div className="row" style={{ alignItems: "center" }}>
            <span>They are undone in {remaining ?? 0} seconds unless you confirm. If this page stopped responding, they would have locked you out.</span>
            <Button variant="primary" onClick={confirm}>Keep these settings</Button>
          </div>
        </Callout>
      ) : null}
      {s && s.enabled && !s.service_running ? (
        <Callout tone="danger" title="The firewall service is not running">
          Rules already applied stay in place, but nothing new is banned. Check <span className="mono">journalctl -u veyra-firewall</span>.
        </Callout>
      ) : null}
      {s?.error ? <Callout tone="danger" title="The rules could not be applied">{s.error}</Callout> : null}
      <Tabs idBase="fw" active={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" },
        { id: "bans", label: "Bans" },
        { id: "rules", label: "Allow and block" },
        { id: "events", label: "Events" },
        { id: "settings", label: "Settings" },
      ]} />
      <TabPanel idBase="fw" id="overview" active={tab}>
        {s ? <Overview status={s} onAddress={(a) => { setAddress(a); setTab("events"); }} /> : <Card><p className="subtle">Loading…</p></Card>}
      </TabPanel>
      <TabPanel idBase="fw" id="bans" active={tab}><Bans onChanged={status.reload} /></TabPanel>
      <TabPanel idBase="fw" id="rules" active={tab}><Rules onChanged={status.reload} /></TabPanel>
      <TabPanel idBase="fw" id="events" active={tab}><Events address={address} setAddress={setAddress} /></TabPanel>
      <TabPanel idBase="fw" id="settings" active={tab}>
        {settings.data && s ? (
          <div className="stack">
            <SettingsForm settings={settings.data} status={s} onSaved={reload} />
            <Feeds />
          </div>
        ) : <Card><p className="subtle">Loading…</p></Card>}
      </TabPanel>
    </div>
  );
}
