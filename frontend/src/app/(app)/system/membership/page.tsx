// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfirmDialog,
  ErrorState,
  LoadingState,
  PageHeader,
  Switch,
  TextArea,
  TextField,
  useToast,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { resultTone, SECTION_LABELS } from "@/lib/central";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CentralMembership } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";

const ACCEPT_HELP: Record<string, string> = {
  updates: "The console sets the update mode, maintenance window and email recipients. Updates always come from the official signed feed.",
  firewall_allow: "The console adds networks to the firewall allow list. Local entries are never removed.",
  alert_recipients: "The console sets who receives alert emails.",
  notice: "The console can show a banner to administrators of this installation.",
  commands: "The console can ask this installation to check, download or approve updates and refresh catalogs.",
};

function EnrollForm({ onDone }: { onDone: (m: CentralMembership) => void }) {
  const errors = useFormErrors();
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [ca, setCa] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const m = await api.post<CentralMembership>("/central/membership/enroll", { url: url.trim(), token: token.trim(), fingerprint: fingerprint.trim(), ca_pem: ca.trim() || null });
      toast.success("Enrolled", `This installation now reports to ${m.console_name ?? m.console_url}.`);
      onDone(m);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Enroll with a central console" footer={<Button variant="primary" type="submit" form="enroll-form" loading={busy} disabled={!url.trim() || !token.trim() || !fingerprint.trim()}>Enroll</Button>}>
      <form id="enroll-form" className="stack stack--sm" onSubmit={submit}>
        <p className="subtle" style={{ margin: 0 }}>An administrator of the console creates an enrollment token under System → Central console and gives you these three values.</p>
        <TextField label="Console address" required value={url} error={errors.fields.url} placeholder="https://veyra-central.example.org" onChange={(e) => setUrl(e.target.value)} />
        <TextField label="Enrollment token" required value={token} error={errors.fields.token} autoComplete="off" onChange={(e) => setToken(e.target.value)} />
        <TextField label="Console fingerprint" required value={fingerprint} error={errors.fields.fingerprint} help="Checked against the console's key, so this installation cannot be enrolled with an impostor." onChange={(e) => setFingerprint(e.target.value)} />
        <TextArea label="Certificate authority (optional)" rows={3} value={ca} error={errors.fields.ca_pem} placeholder="-----BEGIN CERTIFICATE-----"
          help="Only when the console uses a certificate this server does not trust, such as a self-signed one. Paste the PEM text." onChange={(e) => setCa(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Card>
  );
}

function Enrolled({ m, reload }: { m: CentralMembership; reload: () => void }) {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("system.settings.write");
  const [busy, setBusy] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = async (key: string, on: boolean) => {
    setBusy(key);
    try {
      await api.put("/central/membership/accepted", { [key]: on });
      reload();
    } catch (err) {
      toast.error("Could not change it", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const checkIn = async () => {
    setBusy("check-in");
    try {
      const r = await api.post<CentralMembership>("/central/membership/check-in");
      if (r.last_error) toast.error("Check-in failed", r.last_error);
      else toast.success("Checked in");
      reload();
    } catch (err) {
      toast.error("Check-in failed", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const leave = async () => {
    setBusy("leave");
    setError(null);
    try {
      await api.post("/central/membership/leave");
      toast.success("Left the central console", "Settings it applied stay as they are.");
      setLeaving(false);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const results = m.policy?.results ?? {};
  return (
    <>
      {m.revoked ? <Callout tone="danger" title="The console revoked this installation">It no longer accepts check-ins from here. Leave the console, then enroll again with a new token if needed.</Callout>
        : m.last_error ? <Callout tone="warn" title="The last check-in failed">{m.last_error}</Callout> : null}
      <Card title="Console" actions={editable ? <><Button size="sm" icon="refresh" loading={busy === "check-in"} disabled={m.revoked} onClick={() => void checkIn()}>Check in now</Button><Button size="sm" variant="danger" onClick={() => setLeaving(true)}>Leave</Button></> : undefined}>
        <dl className="dl">
          <dt>Console</dt><dd>{m.console_name ?? "—"} <span className="mono subtle">{m.console_url}</span></dd>
          <dt>Console fingerprint</dt><dd className="mono">{m.console_fingerprint ?? "—"}</dd>
          <dt>This installation</dt><dd className="mono">{m.fingerprint ?? "—"}</dd>
          <dt>Enrolled</dt><dd>{formatDateTime(m.enrolled_at)}</dd>
          <dt>Last contact</dt><dd>{m.last_contact ? formatRelative(m.last_contact) : "Never"}{m.last_attempt && m.last_attempt !== m.last_contact ? <span className="subtle"> · last attempt {formatRelative(m.last_attempt)}</span> : null}</dd>
        </dl>
      </Card>
      <Card title="What this installation accepts" subtitle="Switch a section off to keep it under local control. The console sees what you refuse.">
        <div className="stack stack--sm">
          {Object.entries(m.accepted ?? {}).map(([key, on]) => (
            <Switch key={key} label={SECTION_LABELS[key] ?? key} description={ACCEPT_HELP[key]} checked={on} disabled={!editable || busy === key} onChange={(e) => void accept(key, e.target.checked)} />
          ))}
        </div>
      </Card>
      <Card title="Policy from the console">
        {!m.policy ? <p className="subtle">The console has not assigned a policy.</p> : (
          <div className="stack stack--sm">
            <p style={{ margin: 0 }}><strong>{m.policy.name ?? "Unnamed policy"}</strong> <span className="subtle">version {m.policy.version}{m.policy.applied_at ? `, applied ${formatRelative(m.policy.applied_at)}` : ""}</span></p>
            <dl className="dl">
              {Object.entries(results).map(([section, result]) => (
                <span key={section} style={{ display: "contents" }}><dt>{SECTION_LABELS[section] ?? section}</dt><dd><Badge tone={resultTone(result)}>{result}</Badge></dd></span>
              ))}
            </dl>
          </div>
        )}
      </Card>
      <Card title="Recent activity">
        {(m.log ?? []).length === 0 ? <p className="subtle">Nothing yet.</p> : (
          <ul className="stack stack--sm" style={{ margin: 0, paddingLeft: 18 }}>
            {[...(m.log ?? [])].reverse().map((l, i) => (
              <li key={i}><span className="subtle">{formatDateTime(l.at)}</span> {l.what}{l.detail ? <span className="subtle"> — {typeof l.detail === "string" ? l.detail : JSON.stringify(l.detail)}</span> : null}</li>
            ))}
          </ul>
        )}
      </Card>
      <ConfirmDialog open={leaving} title="Leave the central console?" confirmLabel="Leave" tone="danger" busy={busy === "leave"} error={error} onConfirm={() => void leave()} onCancel={() => { setLeaving(false); setError(null); }}>
        <p>This installation stops checking in and forgets the console&apos;s key. Settings the policy applied stay as they are; firewall entries from the console are removed.</p>
      </ConfirmDialog>
    </>
  );
}

export default function MembershipPage() {
  const { can } = useSession();
  const data = useApiData<CentralMembership>("/central/membership");
  const m = data.data;
  return (
    <div className="stack">
      <PageHeader title="Central management" description="Report this installation's health to a central console and take policies and update commands from it. Optional; this installation keeps working on its own if the console is unreachable." />
      {data.error ? <Card><ErrorState error={data.error} onRetry={data.reload} /></Card> : !m ? <Card><LoadingState /></Card>
        : m.enrolled ? <Enrolled m={m} reload={data.reload} />
        : can("system.settings.write") ? <EnrollForm onDone={() => data.reload()} />
        : <Card><p className="subtle">This installation is not managed by a central console.</p></Card>}
    </div>
  );
}
