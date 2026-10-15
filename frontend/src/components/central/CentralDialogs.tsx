// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Checkbox, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { CopyButton } from "@/components/common/CopyButton";
import { api } from "@/lib/api";
import { COMMAND_LABELS, policyDocument, policyForm, type PolicyForm } from "@/lib/central";
import { formatDateTime } from "@/lib/format";
import { browserTimeZone, timeZones } from "@/lib/timezones";
import type { CentralPolicy, CentralTokenCreated, UpdateMode } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

const MODES: { value: UpdateMode; label: string }[] = [
  { value: "manual", label: "Manual only" },
  { value: "notify", label: "Notify" },
  { value: "download_approve", label: "Download, install on approval" },
  { value: "auto_install_window", label: "Install automatically in a maintenance window" },
];

const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]] as const;

function toggle<T>(list: T[], v: T, on: boolean): T[] {
  return on ? [...new Set([...list, v])] : list.filter((x) => x !== v);
}

const fieldset = { border: 0, padding: 0, margin: 0 } as const;

// ----------------------------------------------------------------- policies

export function PolicyDialog({ open, policy, onClose, onSaved }: { open: boolean; policy?: CentralPolicy; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [f, setF] = useState<PolicyForm>(policyForm(undefined));
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<PolicyForm>) => setF((cur) => ({ ...cur, ...patch }));

  useOnChange(open, () => {
    if (!open) return;
    setName(policy?.name ?? "");
    setDescription(policy?.description ?? "");
    setIsDefault(policy?.is_default ?? false);
    setF(policyForm(policy?.document));
    errors.clear();
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { name: name.trim(), description: description.trim() || null, is_default: isDefault, document: policyDocument(f) };
      if (policy) await api.put(`/central/policies/${policy.id}`, body);
      else await api.post("/central/policies", body);
      toast.success(policy ? "Policy saved" : "Policy created", "Instances pick it up at their next check-in.");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={policy ? `Edit "${policy.name}"` : "New policy"}
      description="What enrolled instances should use. Sections you leave off stay under each instance's own control, and each instance can refuse a section."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="central-policy-form" loading={busy} disabled={!name.trim()}>{policy ? "Save policy" : "Create policy"}</Button></>}>
      <form id="central-policy-form" className="stack" onSubmit={submit}>
        <div className="form-grid">
          <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. School buildings" onChange={(e) => setName(e.target.value)} />
          <TextField label="Description (optional)" value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <Checkbox label="Default policy" description="Given to instances enrolled with a token that names no policy." checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />

        <fieldset className="stack stack--sm" style={fieldset}>
          <legend className="card__title">Software updates</legend>
          <Switch label="Set the update policy" checked={f.updates} onChange={(e) => set({ updates: e.target.checked })} />
          {f.updates ? (
            <>
              <SelectField label="Mode" value={f.mode} options={MODES} onChange={(e) => set({ mode: e.target.value as UpdateMode })} />
              <Switch label="Use a maintenance window" checked={!!f.window}
                onChange={(e) => set({ window: e.target.checked ? { days: ["sat"], start: "02:00", duration_minutes: 120, timezone: browserTimeZone() } : null })} />
              {f.window ? (
                <>
                  <div className="row" role="group" aria-label="Days">
                    {DAYS.map(([v, l]) => (
                      <Checkbox key={v} label={l} checked={f.window!.days.includes(v)} onChange={(e) => set({ window: { ...f.window!, days: toggle(f.window!.days, v, e.target.checked) } })} />
                    ))}
                  </div>
                  <div className="form-grid">
                    <TextField label="Starts at" type="time" value={f.window.start} onChange={(e) => set({ window: { ...f.window!, start: e.target.value } })} />
                    <TextField label="Length (minutes)" type="number" min={30} max={720} value={String(f.window.duration_minutes)}
                      onChange={(e) => set({ window: { ...f.window!, duration_minutes: Number(e.target.value) } })} />
                    <SelectField label="Time zone" value={f.window.timezone} options={timeZones().map((z) => ({ value: z, label: z }))}
                      onChange={(e) => set({ window: { ...f.window!, timezone: e.target.value } })} />
                  </div>
                </>
              ) : null}
              {f.mode === "auto_install_window" ? (
                <div className="row" role="group" aria-label="Install automatically">
                  <span className="muted">Install automatically:</span>
                  {(["security", "bugfix", "feature"] as const).map((c) => (
                    <Checkbox key={c} label={c === "bugfix" ? "Bug fixes" : c === "security" ? "Security" : "Features"} checked={f.categories.includes(c)}
                      onChange={(e) => set({ categories: toggle(f.categories, c, e.target.checked) })} />
                  ))}
                </div>
              ) : null}
              <TextField label="Update source address (optional)" value={f.sourceUrl} placeholder="https://updates.example.org/veyra/" help="Empty keeps each instance's own source." onChange={(e) => set({ sourceUrl: e.target.value })} />
              <TextArea label="Update email recipients (optional)" rows={2} value={f.updateRecipients} help="One address per line. Empty keeps each instance's own list." onChange={(e) => set({ updateRecipients: e.target.value })} />
            </>
          ) : null}
        </fieldset>

        <fieldset className="stack stack--sm" style={fieldset}>
          <legend className="card__title">Firewall</legend>
          <Switch label="Add addresses to the allow list" description="Entries from the console are marked and removed again when the policy drops them; local entries are never touched."
            checked={f.firewall} onChange={(e) => set({ firewall: e.target.checked })} />
          {f.firewall ? <TextArea label="Allowed networks" rows={4} value={f.allow} placeholder={"10.0.0.0/8 District WAN\n192.0.2.10 Monitoring"} help="One address or network per line, optionally followed by a comment." onChange={(e) => set({ allow: e.target.value })} /> : null}
        </fieldset>

        <fieldset className="stack stack--sm" style={fieldset}>
          <legend className="card__title">Alerts</legend>
          <Switch label="Set the alert email recipients" checked={f.alerts} onChange={(e) => set({ alerts: e.target.checked })} />
          {f.alerts ? <TextArea label="Recipients" rows={3} value={f.recipients} help="One address per line." onChange={(e) => set({ recipients: e.target.value })} /> : null}
        </fieldset>

        <fieldset className="stack stack--sm" style={fieldset}>
          <legend className="card__title">Notice</legend>
          <Switch label="Show a notice to administrators" checked={f.noticeOn} description="A banner on every page of the instance; leave the text empty to remove a notice set earlier."
            onChange={(e) => set({ noticeOn: e.target.checked })} />
          {f.noticeOn ? <TextArea label="Text" rows={2} maxLength={500} value={f.notice} placeholder="This server is managed by District IT. Call x4000 before changing trunks." onChange={(e) => set({ notice: e.target.value })} /> : null}
        </fieldset>

        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

// ----------------------------------------------------------------- tokens

export function TokenDialog({ open, policies, onClose, onCreated }: { open: boolean; policies: CentralPolicy[]; onClose: () => void; onCreated: (t: CentralTokenCreated) => void }) {
  const errors = useFormErrors();
  const [label, setLabel] = useState("");
  const [policyId, setPolicyId] = useState("");
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (!open) return;
    setLabel("");
    setPolicyId("");
    errors.clear();
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const t = await api.post<CentralTokenCreated>("/central/tokens", { label: label.trim() || null, policy_id: policyId || null });
      onClose();
      onCreated(t);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New enrollment token"
      description="A one-time token an administrator of another Veyra installation enters to enroll it here. It works once and expires after a day."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="central-token-form" loading={busy}>Create token</Button></>}>
      <form id="central-token-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Label (optional)" autoFocus value={label} error={errors.fields.label} placeholder="e.g. High school" help="Becomes the instance's label here." onChange={(e) => setLabel(e.target.value)} />
        <SelectField label="Policy" value={policyId} placeholder="The default policy" options={policies.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setPolicyId(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export function TokenShownDialog({ token, onClose }: { token: CentralTokenCreated | null; onClose: () => void }) {
  return (
    <Dialog open={!!token} onClose={onClose} title="Enrollment details" description="Copy them now: the token cannot be shown again."
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      {token ? (
        <div className="stack stack--sm">
          <p className="subtle">On the other installation, open System → Central management and enter:</p>
          <dl className="dl">
            <dt>Console address</dt><dd><span className="row" style={{ gap: 8 }}><code className="mono" style={{ wordBreak: "break-all", flex: 1 }}>{token.address}</code><CopyButton text={token.address} /></span></dd>
            <dt>Token</dt><dd><span className="row" style={{ gap: 8 }}><code className="mono" style={{ wordBreak: "break-all", flex: 1 }}>{token.token}</code><CopyButton text={token.token} /></span></dd>
            <dt>Fingerprint</dt><dd><span className="row" style={{ gap: 8 }}><code className="mono" style={{ wordBreak: "break-all", flex: 1 }}>{token.fingerprint}</code><CopyButton text={token.fingerprint} /></span></dd>
            <dt>Expires</dt><dd>{formatDateTime(token.expires_at)}</dd>
          </dl>
        </div>
      ) : null}
    </Dialog>
  );
}

// ----------------------------------------------------------------- commands

export function CommandDialog({ open, instanceIds, title, onClose, onQueued }: { open: boolean; instanceIds: string[]; title: string; onClose: () => void; onQueued: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [kind, setKind] = useState("check_updates");
  const [version, setVersion] = useState("");
  const [when, setWhen] = useState("window");
  const [busy, setBusy] = useState(false);
  const needsVersion = kind === "download_update" || kind === "approve_update";

  useOnChange(open, () => {
    if (!open) return;
    setKind("check_updates");
    setVersion("");
    setWhen("window");
    errors.clear();
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    const args: Record<string, string> = {};
    if (needsVersion) args.version = version.trim();
    if (kind === "approve_update") args.when = when;
    try {
      if (instanceIds.length === 1) await api.post(`/central/instances/${instanceIds[0]}/commands`, { kind, arguments: args });
      else await api.post("/central/commands", { kind, arguments: args, instance_ids: instanceIds });
      toast.success("Command queued", "It is delivered at the next check-in, if the instance accepts commands.");
      onClose();
      onQueued();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={title}
      description="Commands wait for the instance's next check-in and expire after a day. An instance runs them through its own update rules."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="central-command-form" loading={busy} disabled={needsVersion && !version.trim()}>Queue command</Button></>}>
      <form id="central-command-form" className="stack stack--sm" onSubmit={submit}>
        <SelectField label="Command" value={kind} options={Object.entries(COMMAND_LABELS).map(([value, label]) => ({ value, label }))} onChange={(e) => setKind(e.target.value)} />
        {needsVersion ? <TextField label="Version" required value={version} error={errors.fields.version} placeholder="e.g. 0.21.0" onChange={(e) => setVersion(e.target.value)} /> : null}
        {kind === "approve_update" ? (
          <SelectField label="Install" value={when} options={[{ value: "window", label: "In the maintenance window" }, { value: "now", label: "Now, when no call is in progress" }]} onChange={(e) => setWhen(e.target.value)} />
        ) : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
