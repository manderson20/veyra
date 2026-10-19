// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, Checkbox, ErrorState, LoadingState, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { MfaPolicy, MfaPolicyOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

/** Platform-wide two-factor policy (Settings page, platform administrators). */
export function MfaPolicyCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<MfaPolicyOut>("/auth/mfa/policy");
  const [form, setForm] = useState<MfaPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  useOnChange(data.data, (d) => { if (d) setForm(d.policy); });
  if (data.error) return <Card title="Two-factor policy"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!form || !data.data) return <Card title="Two-factor policy"><LoadingState /></Card>;
  const f = form;
  const dirty = JSON.stringify(f) !== JSON.stringify(data.data.policy);
  const toggle = (key: string, on: boolean) => setForm({ ...f, required_for: on ? [...f.required_for, key] : f.required_for.filter((k) => k !== key) });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const saved = await api.put<MfaPolicyOut>("/auth/mfa/policy", f);
      data.setData(saved);
      toast.success("Two-factor policy saved", "Affected users are told at their next sign-in.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Two-factor policy" subtitle="Which roles must use an authenticator app, and how long they have to set it up." id="mfa-policy">
      <form className="stack stack--sm" onSubmit={submit}>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label" style={{ marginBottom: 8 }}>Required for</legend>
          <div className="stack stack--sm">
            {data.data.roles.map((r) => (
              <Checkbox key={r.key} label={r.name} disabled={!editable} checked={f.required_for.includes(r.key)} onChange={(e) => toggle(r.key, e.target.checked)} />
            ))}
          </div>
        </fieldset>
        <TextField label="Days to set it up" type="number" min={0} max={365} disabled={!editable} value={f.grace_days} error={errors.fields.grace_days}
          help="After the first sign-in with a role that requires it, users can still sign in without a second factor for this many days. 0 means they must set it up at once."
          onChange={(e) => setForm({ ...f, grace_days: e.target.value === "" ? 0 : Number(e.target.value) })} />
        <TextField label="Trust a browser for (days)" type="number" min={0} max={90} disabled={!editable} value={f.trusted_browser_days ?? 0} error={errors.fields.trusted_browser_days}
          help="After the code, users may tick “Trust this browser” and sign in there with the password only for this many days. 0 turns the choice off. Changing a password or resetting the second factor forgets every trusted browser."
          onChange={(e) => setForm({ ...f, trusted_browser_days: e.target.value === "" ? 0 : Number(e.target.value) })} />
        <p className="subtle">The recovery administrator is not exempt; the server console command <span className="mono">veyra users mfa-reset</span> is the escape hatch. Users who sign in through an external identity provider rely on that provider&apos;s second factor.</p>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save policy</Button></div> : null}
      </form>
    </Card>
  );
}
