// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { REVISION_STATE, TELEPHONY_STATE } from "@/components/common/labels";
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
  StatusBadge,
  Switch,
  TextArea,
  TextField,
  toStatus,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { ConfigRevision, EngineStatus, Page, SipSettings, SipSettingsOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

const ENGINE_REFRESH_MS = 15_000;
const DEPLOY_POLL_MS = 2_000;
const DEPLOY_POLL_LIMIT = 45; // 90 s

function engineStatus(state: string) {
  return { running: "ok", not_configured: "unknown", not_installed: "unknown" }[state] ?? "failed";
}

function Count({ value, unit }: { value: number | null; unit: string }) {
  if (value === null) return <span className="subtle">not available</span>;
  return <span><strong>{value}</strong> {unit}</span>;
}

export default function TelephonyEnginePage() {
  const { can } = useSession();
  const toast = useToast();
  const engine = useApiData<EngineStatus>("/telephony/engine");
  const revisions = useApiData<Page<ConfigRevision>>("/telephony/revisions", { limit: 25 });
  const [open, setOpen] = useState<ConfigRevision | null>(null);
  const [generating, setGenerating] = useState(false);
  const canDeploy = can("config.deploy");
  const reloadEngine = engine.reload;
  const reloadRevisions = revisions.reload;

  useEffect(() => {
    const t = window.setInterval(reloadEngine, ENGINE_REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reloadEngine]);

  const refreshAll = useCallback(() => {
    reloadEngine();
    reloadRevisions();
  }, [reloadEngine, reloadRevisions]);

  const generate = async () => {
    setGenerating(true);
    try {
      const rev = await api.post<ConfigRevision>("/telephony/revisions");
      reloadRevisions();
      setOpen(rev);
      if (rev.state === "failed") toast.error("Configuration could not be generated", rev.validation_errors[0]);
      else if (rev.unchanged) toast.info("No change", "The generated configuration matches what is deployed.");
    } catch (err) {
      toast.error("Could not generate configuration", errorMessage(err));
    } finally {
      setGenerating(false);
    }
  };

  const e = engine.data;
  const columns: Column<ConfigRevision>[] = [
    { key: "seq", header: "#", width: "64px", render: (r) => <span className="mono">{r.sequence}</span> },
    { key: "state", header: "State", render: (r) => <Badge tone={REVISION_STATE[r.state]?.tone ?? "neutral"}>{REVISION_STATE[r.state]?.label ?? r.state}</Badge> },
    { key: "summary", header: "Summary", render: (r) => <span>{r.summary}{r.validation_errors.length && r.state === "failed" ? <span className="table__secondary" style={{ display: "block" }}>{r.validation_errors[0]}</span> : null}</span> },
    { key: "by", header: "Created by", render: (r) => <span className="subtle">{r.created_by}</span> },
    { key: "when", header: "Created", render: (r) => <span className="subtle nowrap" title={formatDateTime(r.created_at)}>{formatRelative(r.created_at)}</span> },
    { key: "deployed", header: "Deployed", render: (r) => <span className="subtle nowrap">{r.deployed_at ? formatRelative(r.deployed_at) : "—"}</span> },
    { key: "actions", header: <span className="sr-only">Actions</span>, width: "120px", render: (r) => <Button size="sm" onClick={() => setOpen(r)}>View</Button> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Telephony engine"
        description="The engine's live state and the configuration Veyra generates for it. Changes take effect when a revision is deployed."
        actions={<Button icon="refresh" onClick={refreshAll} loading={engine.loading && !!e}>Refresh</Button>}
      />
      {engine.error && !e ? <Card><ErrorState title="Could not load the engine status" error={engine.error} onRetry={engine.reload} /></Card> : !e ? <Card><LoadingState /></Card> : (
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <Card title={`Engine: ${e.engine === "asterisk" ? "Asterisk" : e.engine}`} actions={<StatusBadge status={toStatus(engineStatus(e.state))} label={TELEPHONY_STATE[e.state]} />}>
            <p>{e.message}</p>
            <dl className="dl" style={{ marginTop: 12 }}>
              <dt>Version</dt><dd className="mono">{e.version ?? "—"}</dd>
              <dt>Started</dt><dd>{e.started_at ? `${formatRelative(e.started_at)} (${formatDateTime(e.started_at)})` : "—"}</dd>
              <dt>Last reload</dt><dd>{e.last_reload_at ? formatRelative(e.last_reload_at) : "—"}</dd>
              <dt>Registrations</dt><dd>{e.endpoints_total === null ? <span className="subtle">not available</span> : <span><strong>{e.endpoints_registered}</strong> of {e.endpoints_total} endpoints registered</span>}</dd>
              <dt>Active channels</dt><dd><Count value={e.active_channels} unit="channel(s)" /></dd>
              <dt>Configuration directory</dt><dd className="mono">{e.config_dir ?? "—"}</dd>
            </dl>
            {e.modules.length ? (
              <div style={{ marginTop: 16 }}>
                <p className="field__label">Modules</p>
                <ul className="list-plain" style={{ marginTop: 6 }}>
                  {e.modules.map((m) => (
                    <li key={m.name} className="row row--between" style={{ padding: "4px 0" }}>
                      <span className="mono">{m.name}</span>
                      <Badge tone={m.status === "Running" ? "ok" : m.status === "not loaded" ? "neutral" : "warn"}>{m.status}</Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Card>
          <Card
            title="Configuration"
            subtitle="Generated from the database into the engine's Veyra directory by the deployer service."
            actions={canDeploy ? <Button variant="primary" icon="sparkle" loading={generating} disabled={e.state !== "running" && e.engine !== "none"} onClick={generate}>Generate configuration</Button> : null}
          >
            <dl className="dl">
              <dt>Deployed revision</dt><dd>{e.deployed_revision !== null ? <span className="mono">#{e.deployed_revision}</span> : <span className="subtle">nothing deployed yet</span>}</dd>
              <dt>In progress</dt><dd>{e.pending_revision !== null ? <span className="row"><Badge tone="accent">Deploying #{e.pending_revision}</Badge></span> : <span className="subtle">none</span>}</dd>
            </dl>
            <p className="subtle" style={{ marginTop: 12 }}>
              Generate a revision to preview exactly what would change, then deploy it. Deploying an older revision again rolls back.
              {e.state !== "running" ? " Deployment needs the engine to be running." : ""}
            </p>
          </Card>
        </div>
      )}
      <Card title="Revisions" flush subtitle="Every generated configuration, deployed or not. Nothing is written to the engine until a revision is deployed.">
        <DataTable
          columns={columns}
          rows={revisions.data?.items}
          rowKey={(r) => r.id}
          loading={revisions.loading}
          error={revisions.error}
          onRetry={revisions.reload}
          caption="Configuration revisions"
          empty={<EmptyState compact icon="file" title="No revisions yet">Generate the first configuration from the card above.</EmptyState>}
        />
      </Card>
      {can("system.settings.read") ? <SipSettingsCard editable={can("system.settings.write")} /> : null}
      <RevisionDialog revision={open} onClose={() => setOpen(null)} canDeploy={canDeploy} onChanged={refreshAll} />
    </div>
  );
}

function RevisionDialog({ revision, onClose, canDeploy, onChanged }: { revision: ConfigRevision | null; onClose: () => void; canDeploy: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [rev, setRev] = useState<ConfigRevision | null>(revision);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const polls = useRef(0);

  useOnChange(revision, (r) => {
    setRev(r);
    setError(null);
    if (r && r.files.length === 0 && r.state !== "failed") {
      // list rows carry no files: fetch the full revision
      api.get<ConfigRevision>(`/telephony/revisions/${r.id}`).then(setRev).catch((e) => setError(errorMessage(e)));
    }
  });

  useEffect(() => {
    if (!rev || rev.state !== "deploying") return;
    polls.current = 0;
    const t = window.setInterval(async () => {
      polls.current += 1;
      try {
        const r = await api.get<ConfigRevision>(`/telephony/revisions/${rev.id}`);
        if (r.state !== "deploying") {
          setRev(r);
          onChanged();
          if (r.state === "deployed") toast.success(`Revision #${r.sequence} deployed`);
          else toast.error(`Revision #${r.sequence} failed`, r.validation_errors[0]);
        }
      } catch {
        /* keep polling */
      }
      if (polls.current >= DEPLOY_POLL_LIMIT) {
        window.clearInterval(t);
        setError("The deployer has not reported a result yet. Check 'journalctl -u veyra-deployer' on the server.");
      }
    }, DEPLOY_POLL_MS);
    return () => window.clearInterval(t);
  }, [rev, onChanged, toast]);

  const act = async (action: "deploy" | "discard") => {
    if (!rev) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "deploy") {
        setRev(await api.post<ConfigRevision>(`/telephony/revisions/${rev.id}/deploy`));
      } else {
        await api.post(`/telephony/revisions/${rev.id}/discard`);
        toast.success(`Revision #${rev.sequence} discarded`);
        onChanged();
        onClose();
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const r = rev;
  const state = r ? REVISION_STATE[r.state] : undefined;
  const changed = r?.diff ? Object.entries(r.diff) : [];
  return (
    <Dialog
      open={revision !== null}
      onClose={onClose}
      busy={busy}
      size="lg"
      title={r ? `Revision #${r.sequence}` : "Revision"}
      description={r ? `${r.summary} · created by ${r.created_by} ${formatRelative(r.created_at)}` : undefined}
      footer={r ? (
        <>
          <Button onClick={onClose} disabled={busy}>Close</Button>
          {canDeploy && r.state === "validated" ? <Button onClick={() => act("discard")} disabled={busy}>Discard</Button> : null}
          {canDeploy && (r.can_deploy || r.can_rollback) ? (
            <Button variant={r.can_rollback ? "danger" : "primary"} icon={r.can_rollback ? "history" : "upload"} loading={busy} onClick={() => act("deploy")}>
              {r.can_rollback ? "Roll back to this revision" : "Deploy"}
            </Button>
          ) : null}
        </>
      ) : null}
    >
      {!r ? <LoadingState /> : (
        <div className="stack stack--sm">
          <div className="row">
            <Badge tone={state?.tone ?? "neutral"}>{state?.label ?? r.state}</Badge>
            {r.deployed_at ? <span className="subtle">deployed {formatDateTime(r.deployed_at)}</span> : null}
            {r.parent_sequence !== null ? <span className="subtle">based on #{r.parent_sequence}</span> : null}
          </div>
          {r.state === "deploying" ? <Callout tone="info" title="Deploying">The deployer is writing the files and reloading the engine. This page updates when it finishes.</Callout> : null}
          {r.state === "failed" && r.validation_errors.length ? (
            <Callout tone="danger" title={r.deployed_at ? "Deployment failed" : "Problems"}>
              <ul className="list-plain">{r.validation_errors.map((v, i) => <li key={i} className="mono" style={{ padding: "2px 0" }}>{v}</li>)}</ul>
            </Callout>
          ) : null}
          {r.state === "deployed" && r.validation_errors.length ? (
            <details><summary className="subtle">Deployment log</summary><pre className="code" style={{ marginTop: 8 }}>{r.validation_errors.join("\n")}</pre></details>
          ) : null}
          {error ? <Callout tone="danger">{error}</Callout> : null}
          {r.files.length === 0 && r.state !== "failed" ? <p className="muted">File contents are shown to platform administrators only.</p> : null}
          {r.diff && changed.length === 0 && r.files.length ? <Callout tone="neutral">Identical to the deployed configuration.</Callout> : null}
          {changed.map(([path, d]) => (
            <div key={path}>
              <p className="field__label row" style={{ gap: 8 }}><span className="mono">{path}</span>{d.sensitive ? <Badge tone="warn" icon="lock">contains credentials; diff hidden</Badge> : null}</p>
              {d.diff ? <pre className="code" style={{ marginTop: 6 }}>{d.diff}</pre> : null}
            </div>
          ))}
          {r.files.length ? (
            <details>
              <summary className="subtle">All files in this revision ({r.files.length})</summary>
              <div className="stack stack--sm" style={{ marginTop: 8 }}>
                {r.files.map((f) => (
                  <div key={f.path}>
                    <p className="field__label row" style={{ gap: 8 }}><span className="mono">{f.path}</span><span className="subtle">{f.lines} lines</span>{f.sensitive ? <Badge tone="warn" icon="lock">credentials not shown</Badge> : null}</p>
                    {f.content !== null ? <pre className="code" style={{ marginTop: 6 }}>{f.content}</pre> : null}
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

function SipSettingsCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<SipSettingsOut>("/telephony/settings");
  const [form, setForm] = useState<SipSettings | null>(null);
  const [nets, setNets] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(data.data, (d) => {
    if (d) {
      setForm(d.settings);
      setNets(d.settings.local_nets.join("\n"));
    }
  });
  if (data.error) return <Card title="SIP and media settings"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!form || !data.data) return <Card title="SIP and media settings"><LoadingState /></Card>;
  const f = form;
  const set = <K extends keyof SipSettings>(k: K, v: SipSettings[K]) => setForm({ ...f, [k]: v });
  const num = (v: string) => (v === "" ? 0 : Number(v));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { ...f, local_nets: nets.split(/\n|,/).map((s) => s.trim()).filter(Boolean) };
      const saved = await api.put<SipSettingsOut>("/telephony/settings", body);
      data.setData(saved);
      toast.success("SIP settings saved", "Generate and deploy a revision to apply them.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="SIP and media settings" subtitle="Inputs to the generated transports, endpoints and RTP configuration. Saved settings apply at the next deployment." id="sip-settings">
      <form className="stack" onSubmit={submit}>
        {data.data.problems.length ? <Callout tone="warn" title="The saved settings have problems">{data.data.problems.join(" ")}</Callout> : null}
        <div className="grid grid--2">
          <TextField label="Bind address" required disabled={!editable} value={f.bind_address} help="0.0.0.0 listens on every address." onChange={(e) => set("bind_address", e.target.value)} />
          <TextField label="UDP port" type="number" min={1} max={65535} required disabled={!editable} value={f.udp_port} onChange={(e) => set("udp_port", num(e.target.value))} />
          <Switch label="TCP transport" description="Most desk phones can use TCP; keep it on." checked={f.tcp_enabled} disabled={!editable} onChange={(e) => set("tcp_enabled", e.target.checked)} />
          <TextField label="TCP port" type="number" min={1} max={65535} disabled={!editable || !f.tcp_enabled} value={f.tcp_port} onChange={(e) => set("tcp_port", num(e.target.value))} />
          <Switch label="TLS transport" description="Uses the server certificate in /etc/veyra/tls." checked={f.tls_enabled} disabled={!editable} onChange={(e) => set("tls_enabled", e.target.checked)} />
          <TextField label="TLS port" type="number" min={1} max={65535} disabled={!editable || !f.tls_enabled} value={f.tls_port} onChange={(e) => set("tls_port", num(e.target.value))} />
          <TextField label="RTP port range start" type="number" min={1024} max={65535} required disabled={!editable} value={f.rtp_start} onChange={(e) => set("rtp_start", num(e.target.value))} />
          <TextField label="RTP port range end" type="number" min={1024} max={65535} required disabled={!editable} value={f.rtp_end} onChange={(e) => set("rtp_end", num(e.target.value))} />
          <TextField label="External signaling address" disabled={!editable} value={f.external_signaling_address ?? ""} help="Only when this server is behind NAT. Public IP or host name." onChange={(e) => set("external_signaling_address", e.target.value || null)} />
          <TextField label="External media address" disabled={!editable} value={f.external_media_address ?? ""} help="Usually the same as the signaling address." onChange={(e) => set("external_media_address", e.target.value || null)} />
          <TextArea label="Local networks" disabled={!editable} value={nets} rows={3} help="One CIDR per line, for example 172.16.0.0/16. Required when an external address is set." onChange={(e) => setNets(e.target.value)} />
          <TextField label="Default language" disabled={!editable} value={f.default_language} help="Prompt language code, for example en." onChange={(e) => set("default_language", e.target.value)} />
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label" style={{ marginBottom: 8 }}>Codecs (in order of preference)</legend>
          <div className="row">
            {data.data.codecs_available.map((c) => (
              <Checkbox key={c} label={c} disabled={!editable} checked={f.codecs.includes(c)}
                onChange={(e) => set("codecs", e.target.checked ? [...f.codecs, c] : f.codecs.filter((x) => x !== c))} />
            ))}
          </div>
        </fieldset>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy}>Save settings</Button></div> : <p className="subtle">Only platform administrators can change these settings.</p>}
      </form>
    </Card>
  );
}
