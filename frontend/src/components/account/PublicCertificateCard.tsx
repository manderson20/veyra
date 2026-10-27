// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, SelectField, TextArea, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

type Challenge = "http" | "dns";
type Authority = "letsencrypt" | "letsencrypt_staging" | "custom";

interface ProviderField { key: string; label: string; secret: boolean; multiline: boolean; optional: boolean; default: string | null }
interface Provider { key: string; label: string; fields: ProviderField[] }
interface Run { mode: string | null; started_at: string; finished_at: string | null; running: boolean; ok: boolean; error: string | null; output: string }
interface Info {
  settings: {
    names: string[]; email: string; challenge: Challenge; provider: string | null; authority: Authority;
    directory_url: string | null; eab_kid: string | null; has_eab_hmac_key: boolean; propagation_seconds: number;
    credentials_set: string[]; credentials_public: Record<string, string>;
  };
  problems: string[];
  providers: Provider[];
  certificate: { names: string[]; issuer?: string; not_after?: string; not_before?: string; fingerprint_sha256?: string; days_left: number } | null;
  run: Run | null;
  challenge_window_open: boolean;
  web_allow_list_only: boolean;
}

interface Draft {
  names: string; email: string; challenge: Challenge; provider: string; authority: Authority;
  directory_url: string; eab_kid: string; eab_hmac_key: string; propagation_seconds: string;
  /** Typed values only; an untouched secret field keeps its stored value. */
  credentials: Record<string, string>;
}

const AUTHORITIES: { value: Authority; label: string }[] = [
  { value: "letsencrypt", label: "Let's Encrypt" },
  { value: "letsencrypt_staging", label: "Let's Encrypt staging (test the setup; browsers do not trust it)" },
  { value: "custom", label: "Another ACME authority" },
];

function fromInfo(i: Info): Draft {
  const s = i.settings;
  return {
    names: s.names.join(", "), email: s.email, challenge: s.challenge, provider: s.provider ?? "", authority: s.authority,
    directory_url: s.directory_url ?? "", eab_kid: s.eab_kid ?? "", eab_hmac_key: "", propagation_seconds: String(s.propagation_seconds),
    credentials: { ...s.credentials_public },
  };
}

function body(d: Draft, i: Info) {
  const provider = i.providers.find((p) => p.key === d.provider);
  const credentials: Record<string, string> = {};
  for (const f of provider?.fields ?? []) {
    const v = d.credentials[f.key];
    // Secret fields are sent only when typed; shown fields always.
    if (v !== undefined && (v !== "" || !f.secret)) credentials[f.key] = v;
  }
  return {
    names: d.names.split(/[\s,]+/).map((n) => n.trim()).filter(Boolean),
    email: d.email.trim(),
    challenge: d.challenge,
    provider: d.challenge === "dns" ? d.provider || null : null,
    credentials: d.challenge === "dns" ? credentials : {},
    authority: d.authority,
    directory_url: d.authority === "custom" ? d.directory_url.trim() || null : null,
    eab_kid: d.authority === "custom" ? d.eab_kid.trim() || null : null,
    ...(d.eab_hmac_key ? { eab_hmac_key: d.eab_hmac_key } : {}),
    propagation_seconds: Number(d.propagation_seconds) || 60,
  };
}

const MODE_LABEL: Record<string, string> = { issue: "Request", renew: "Renewal", remove: "Removal" };

/** A certificate browsers trust from Let's Encrypt or another ACME authority
 * (issue #43, docs/PUBLIC_CERTIFICATES.md). The Veyra CA keeps serving
 * phones and every other name. Platform administrators only. */
export function PublicCertificateCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<Info>("/system/certificate");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"issue" | "remove" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  useOnChange(data.data, (i) => { if (i) setDraft(fromInfo(i)); });
  const running = !!data.data?.run?.running;
  const reload = data.reload;
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(reload, 3000);
    return () => window.clearInterval(t);
  }, [running, reload]);

  const title = "HTTPS certificate";
  if (data.error) return <Card title={title}><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!draft || !data.data) return <Card title={title}><LoadingState /></Card>;
  const i = data.data;
  const d = draft;
  const dirty = JSON.stringify(body(d, i)) !== JSON.stringify(body(fromInfo(i), i));
  const provider = i.providers.find((p) => p.key === d.provider);
  const c = i.certificate;
  const run = i.run;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    errors.clear();
    try {
      const saved = await api.put<Info>("/system/certificate/settings", body(d, i));
      data.setData(saved);
      toast.success("Certificate settings saved", saved.problems.length ? saved.problems.join(" ") : "Press Get the certificate when you are ready.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };

  const start = async (mode: "request" | "renew" | "remove") => {
    setBusy(mode);
    setActionError(null);
    try {
      data.setData(await api.post<Info>(`/system/certificate/${mode}`));
      setConfirm(null);
      setShowLog(true);
      toast.success(mode === "remove" ? "Going back to the Veyra certificate" : "Certificate run started", "Progress shows on this card.");
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const setCred = (key: string, value: string) => setDraft({ ...d, credentials: { ...d.credentials, [key]: value } });
  const badge = c
    ? <Badge tone={c.days_left > 21 ? "ok" : c.days_left > 7 ? "warn" : "danger"}>{`Public, ${Math.floor(c.days_left)} days left`}</Badge>
    : <Badge tone="neutral">Veyra CA only</Badge>;

  return (
    <Card title={title} id="https-certificate" actions={badge}
      subtitle="Browsers trust a certificate from Let's Encrypt without installing veyra-ca.crt; passkeys and the Companion need one. Phones keep the Veyra CA certificate, which also answers every other name and the server's IP addresses.">
      <div className="stack stack--sm">
        <dl className="dl">
          <dt>In use</dt>
          <dd>
            {c ? <>{c.names.join(", ")} <span className="subtle">— {c.issuer ?? "public authority"}, valid until {c.not_after ? formatDateTime(c.not_after) : "?"}</span></> : "The Veyra CA certificate for every name."}
          </dd>
          {run ? (
            <>
              <dt>Last run</dt>
              <dd>
                {run.running ? <Badge tone="info">{`${MODE_LABEL[run.mode ?? ""] ?? "Run"} running…`}</Badge>
                  : <Badge tone={run.ok ? "ok" : "danger"}>{`${MODE_LABEL[run.mode ?? ""] ?? "Run"} ${run.ok ? "done" : "failed"}`}</Badge>}{" "}
                <span className="subtle">{formatDateTime(run.finished_at ?? run.started_at)}</span>{" "}
                <Button variant="ghost" size="sm" onClick={() => setShowLog(!showLog)}>{showLog ? "Hide output" : "Show output"}</Button>
              </dd>
            </>
          ) : null}
        </dl>
        {run && !run.running && !run.ok && run.error ? <Callout tone="danger">{run.error}</Callout> : null}
        {showLog && run ? <pre className="mono" style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto", margin: 0 }}>{run.output || "No output yet."}</pre> : null}

        <form className="stack stack--sm" onSubmit={save}>
          <div className="form-grid">
            <TextField label="Host names" required disabled={!editable} value={d.names} error={errors.fields.names} placeholder="pbx.example.org"
              help="The names users type in the browser, separated by commas. Not an IP address. A wildcard (*.example.org) needs the DNS check."
              autoComplete="off" spellCheck={false} onChange={(e) => setDraft({ ...d, names: e.target.value })} />
            <TextField label="Email for expiry notices" type="email" required disabled={!editable} value={d.email} error={errors.fields.email}
              help="The authority writes here if renewal keeps failing." autoComplete="off" onChange={(e) => setDraft({ ...d, email: e.target.value })} />
          </div>
          <SelectField label="How the authority checks you own the name" disabled={!editable} value={d.challenge} error={errors.fields.challenge}
            options={[
              { value: "dns", label: "DNS record (works when the server is not reachable from the internet)" },
              { value: "http", label: "Web request on port 80 (the name must reach this server from the internet)" },
            ]}
            onChange={(e) => setDraft({ ...d, challenge: e.target.value as Challenge })} />
          {d.challenge === "http" ? (
            <Callout tone="info">
              The name must resolve publicly to an address whose port 80 is forwarded to this server.
              {i.web_allow_list_only ? " The firewall limits the web interface to the allow list; port 80 is opened to everyone for ten minutes while the authority checks." : null}
            </Callout>
          ) : (
            <>
              <SelectField label="DNS provider" disabled={!editable} value={d.provider} error={errors.fields.provider}
                options={[{ value: "", label: "Choose the provider that hosts the name…" }, ...i.providers.map((p) => ({ value: p.key, label: p.label }))]}
                onChange={(e) => setDraft({ ...d, provider: e.target.value, credentials: e.target.value === i.settings.provider ? { ...i.settings.credentials_public } : {} })} />
              {provider ? (
                <div className="form-grid">
                  {provider.fields.map((f) => {
                    const stored = i.settings.provider === provider.key && i.settings.credentials_set.includes(f.key);
                    const common = {
                      label: f.label, disabled: !editable, value: d.credentials[f.key] ?? "",
                      placeholder: f.secret ? (stored ? "Set; leave empty to keep it" : "Not set") : (f.default ?? ""),
                      autoComplete: "off", spellCheck: false,
                    };
                    return f.multiline
                      ? <TextArea key={f.key} {...common} rows={4} onChange={(e) => setCred(f.key, e.target.value)} />
                      : <TextField key={f.key} {...common} type={f.secret ? "password" : "text"} onChange={(e) => setCred(f.key, e.target.value)} />;
                  })}
                  <TextField label="Wait for the DNS record (seconds)" type="number" min={10} max={900} disabled={!editable} value={d.propagation_seconds}
                    help="How long the authority waits before it looks up the record." onChange={(e) => setDraft({ ...d, propagation_seconds: e.target.value })} />
                </div>
              ) : null}
              <p className="subtle">The credentials are stored encrypted and never shown again. Give them the narrowest rights the provider offers (edit DNS of this zone only).</p>
            </>
          )}
          <SelectField label="Certificate authority" disabled={!editable} value={d.authority} options={AUTHORITIES}
            help="Try the staging authority first: it has generous limits, and its certificate is replaced by a real one when you switch back."
            onChange={(e) => setDraft({ ...d, authority: e.target.value as Authority })} />
          {d.authority === "custom" ? (
            <div className="form-grid">
              <TextField label="ACME directory address" required disabled={!editable} value={d.directory_url} error={errors.fields.directory_url}
                placeholder="https://acme.example.com/directory" onChange={(e) => setDraft({ ...d, directory_url: e.target.value })} />
              <TextField label="External account key ID" disabled={!editable} value={d.eab_kid} help="Only if the authority asks for one (ZeroSSL, Sectigo)."
                onChange={(e) => setDraft({ ...d, eab_kid: e.target.value })} />
              <TextField label="External account HMAC key" type="password" disabled={!editable} value={d.eab_hmac_key}
                placeholder={i.settings.has_eab_hmac_key ? "Set; leave empty to keep it" : "Not set"} onChange={(e) => setDraft({ ...d, eab_hmac_key: e.target.value })} />
            </div>
          ) : null}
          {i.problems.length && !dirty ? <Callout tone="warn">{i.problems.join(" ")}</Callout> : null}
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
          {actionError && !confirm ? <Callout tone="danger">{actionError}</Callout> : null}
          {editable ? (
            <div className="form-actions">
              {c ? <Button variant="ghost" disabled={running || !!busy} onClick={() => setConfirm("remove")}>Stop using it…</Button> : null}
              {c ? <Button loading={busy === "renew"} disabled={running || dirty || !!busy} onClick={() => void start("renew")} title="Renews only when 30 days or fewer are left">Renew now</Button> : null}
              <Button loading={busy === "request"} disabled={running || dirty || i.problems.length > 0 || !!busy} title={dirty ? "Save first" : undefined}
                onClick={() => setConfirm("issue")}>{c ? "Get a new certificate…" : "Get the certificate…"}</Button>
              <Button variant="primary" type="submit" loading={busy === "save"} disabled={!dirty}>Save settings</Button>
            </div>
          ) : null}
        </form>
      </div>
      <ConfirmDialog open={confirm === "issue"} title={`Get a certificate for ${i.settings.names.join(", ")}?`} confirmLabel="Get it now" busy={busy === "request"} error={actionError}
        onConfirm={() => void start("request")} onCancel={() => setConfirm(null)}>
        <p>Veyra asks {AUTHORITIES.find((a) => a.value === i.settings.authority)?.label ?? "the authority"} for a certificate, proves the name with {i.settings.challenge === "dns" ? "a DNS record" : "a web request on port 80"}, and serves it to browsers that open those names. It takes up to a few minutes; it renews by itself.</p>
        <p className="subtle">Phones and the server&apos;s IP addresses keep the Veyra certificate. Calls are not affected.</p>
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "remove"} title="Stop using the public certificate?" confirmLabel="Stop using it" tone="danger" busy={busy === "remove"} error={actionError}
        onConfirm={() => void start("remove")} onCancel={() => setConfirm(null)}>
        <p>Every name gets the Veyra CA certificate again; browsers without veyra-ca.crt installed will warn, and passkeys stop working until they trust it. The stored DNS credentials are deleted from the server&apos;s certificate folder.</p>
      </ConfirmDialog>
    </Card>
  );
}
