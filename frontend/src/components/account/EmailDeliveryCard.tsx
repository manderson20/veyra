// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, ErrorState, LoadingState, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { SmtpSecurity, SmtpSettings, SmtpSettingsInput, SmtpTestResult } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

interface Draft {
  enabled: boolean;
  host: string;
  port: string;
  security: SmtpSecurity;
  username: string;
  /** Empty: unchanged. */
  password: string;
  clearPassword: boolean;
  from_address: string;
  from_name: string;
}

const SECURITY: { value: SmtpSecurity; label: string }[] = [
  { value: "starttls", label: "STARTTLS (usually port 587)" },
  { value: "tls", label: "TLS from the start (usually port 465)" },
  { value: "none", label: "None (loopback relay only)" },
];

function fromSettings(s: SmtpSettings): Draft {
  return { enabled: s.enabled, host: s.host, port: String(s.port), security: s.security, username: s.username ?? "", password: "", clearPassword: false, from_address: s.from_address ?? "", from_name: s.from_name ?? "" };
}

function body(d: Draft): SmtpSettingsInput {
  const b: SmtpSettingsInput = {
    enabled: d.enabled,
    host: d.host.trim(),
    port: Number(d.port),
    security: d.security,
    username: d.username.trim() || null,
    from_address: d.from_address.trim() || null,
    from_name: d.from_name.trim() || null,
  };
  if (d.clearPassword) b.password = null;
  else if (d.password) b.password = d.password;
  return b;
}

/** SMTP server Veyra sends through (Settings page, platform administrators). docs/VOICEMAIL_IVR.md §2 */
export function EmailDeliveryCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<SmtpSettings>("/system/smtp");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<SmtpTestResult | null>(null);
  useOnChange(data.data, (s) => { if (s) setDraft(fromSettings(s)); });
  if (data.error) return <Card title="Email delivery"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!draft || !data.data) return <Card title="Email delivery"><LoadingState /></Card>;
  const s = data.data;
  const d = draft;
  const dirty = JSON.stringify(body(d)) !== JSON.stringify(body(fromSettings(s)));
  const port = Number(d.port);
  const valid = Number.isInteger(port) && port >= 1 && port <= 65535 && (!d.enabled || d.host.trim());

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const saved = await api.put<SmtpSettings>("/system/smtp", body(d));
      data.setData(saved);
      setTest(null);
      toast.success("Email delivery settings saved", saved.enabled ? "Voicemail notifications use them from now on. Deploy changes if the top bar asks." : "Delivery is off; queued messages wait.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await api.post<SmtpTestResult>("/system/smtp/test"));
    } catch (err) {
      setTest({ ok: false, message: errorMessage(err), recipient: "" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card title="Email delivery" subtitle="The SMTP server Veyra sends through: voicemail notifications now, other messages later. The password is stored encrypted and never shown." id="email-delivery"
      actions={<Badge tone={s.enabled ? (s.problems.length ? "warn" : "ok") : "neutral"}>{s.enabled ? (s.problems.length ? "Needs attention" : "Enabled") : "Off"}</Badge>}>
      <form className="stack stack--sm" onSubmit={submit}>
        <Switch label="Send email" description="Off: voicemail stays in the boxes and nothing is sent." checked={d.enabled} disabled={!editable} onChange={(e) => setDraft({ ...d, enabled: e.target.checked })} />
        <div className="form-grid">
          <TextField label="SMTP server" required={d.enabled} disabled={!editable} value={d.host} error={errors.fields.host} placeholder="smtp.example.org" autoComplete="off" spellCheck={false} onChange={(e) => setDraft({ ...d, host: e.target.value })} />
          <TextField label="Port" type="number" min={1} max={65535} required disabled={!editable} value={d.port} error={errors.fields.port} onChange={(e) => setDraft({ ...d, port: e.target.value })} />
        </div>
        <SelectField label="Connection security" disabled={!editable} value={d.security} error={errors.fields.security} options={SECURITY}
          onChange={(e) => setDraft({ ...d, security: e.target.value as SmtpSecurity, port: d.port === "587" && e.target.value === "tls" ? "465" : d.port === "465" && e.target.value === "starttls" ? "587" : d.port })} />
        <div className="form-grid">
          <TextField label="User name" disabled={!editable} value={d.username} error={errors.fields.username} placeholder="Empty: no authentication" autoComplete="off" onChange={(e) => setDraft({ ...d, username: e.target.value })} />
          <TextField label="Password" type="password" disabled={!editable || d.clearPassword} value={d.password} error={errors.fields.password} autoComplete="new-password"
            placeholder={s.has_password ? "Set; leave empty to keep it" : "Not set"} help={s.has_password && editable ? <label className="check" style={{ display: "inline-flex" }}><input type="checkbox" checked={d.clearPassword} onChange={(e) => setDraft({ ...d, clearPassword: e.target.checked, password: "" })} /> <span>Remove the stored password</span></label> : undefined}
            onChange={(e) => setDraft({ ...d, password: e.target.value })} />
        </div>
        <div className="form-grid">
          <TextField label="From address" type="email" disabled={!editable} value={d.from_address} error={errors.fields.from_address} placeholder={s.effective_from_address} help="Many servers only accept their own domain here." autoComplete="off" onChange={(e) => setDraft({ ...d, from_address: e.target.value })} />
          <TextField label="From name" disabled={!editable} value={d.from_name} error={errors.fields.from_name} placeholder={s.effective_from_name} onChange={(e) => setDraft({ ...d, from_name: e.target.value })} />
        </div>
        {s.problems.length ? <Callout tone="warn">{s.problems.join(" ")}</Callout> : null}
        <p className="subtle">
          Queue: {s.queue.waiting} waiting, {s.queue.failed} given up (after a day of retries, see the audit log for <span className="mono">mail.failed</span>).
          {s.updated_at ? <> Settings changed {formatRelative(s.updated_at)}.</> : null}
        </p>
        {test ? <Callout tone={test.ok ? "ok" : "danger"}>{test.message}</Callout> : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? (
          <div className="form-actions">
            <Button icon="mail" loading={testing} disabled={dirty || !s.enabled} onClick={runTest} title={dirty ? "Save first" : undefined}>Send me a test message</Button>
            <Button variant="primary" type="submit" loading={busy} disabled={!dirty || !valid}>Save settings</Button>
          </div>
        ) : null}
      </form>
    </Card>
  );
}
