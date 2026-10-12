// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, ErrorState, LoadingState, SelectField, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { NumberingOut, NumberingPlan } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

export const LENGTH_OPTIONS = [3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n} digits` }));

/** Installation-wide numbering plan: read-only for most, editable with system.settings.write. */
export function NumberingPlanCard({ editable, onSaved }: { editable: boolean; onSaved?: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<NumberingOut>("/telephony/numbering");
  const [form, setForm] = useState<NumberingPlan | null>(null);
  const [reserved, setReserved] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(data.data, (d) => {
    if (d) {
      setForm(d.plan);
      setReserved(d.plan.reserved_prefixes.join(", "));
    }
  });
  if (data.error) return <Card title="Numbering plan"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!form || !data.data) return <Card title="Numbering plan"><LoadingState /></Card>;
  const f = form;
  const set = <K extends keyof NumberingPlan>(k: K, v: NumberingPlan[K]) => setForm({ ...f, [k]: v });
  const dirty = JSON.stringify({ ...f, reserved_prefixes: reserved }) !== JSON.stringify({ ...data.data.plan, reserved_prefixes: data.data.plan.reserved_prefixes.join(", ") });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { ...f, reserved_prefixes: reserved.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean) };
      const saved = await api.put<NumberingOut>("/telephony/numbering", body);
      data.setData(saved);
      toast.success("Numbering plan saved", "Existing extensions keep their numbers.");
      onSaved?.();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Numbering plan" subtitle={editable ? "Applies to new and renumbered extensions across the installation." : data.data.description} id="numbering-plan">
      {data.data.problems.length ? <Callout tone="warn" title="The saved plan has problems">{data.data.problems.join(" ")}</Callout> : null}
      {editable ? (
        <form className="stack stack--sm" onSubmit={submit}>
          <div className="form-grid">
            <SelectField label="Extension length" value={String(f.extension_length)} options={LENGTH_OPTIONS} onChange={(e) => set("extension_length", Number(e.target.value))} />
            <div />
            <TextField label="First extension" required inputMode="numeric" value={f.first_extension} error={errors.fields.first_extension} onChange={(e) => set("first_extension", e.target.value.replace(/\D/g, ""))} />
            <TextField label="Last extension" required inputMode="numeric" value={f.last_extension} error={errors.fields.last_extension} onChange={(e) => set("last_extension", e.target.value.replace(/\D/g, ""))} />
          </div>
          <TextField label="Reserved leading digits" value={reserved} error={errors.fields.reserved_prefixes}
            help="Comma-separated. Numbers starting with these are never assigned: keep 0 (operator), 9 (outside line), 911 and 933 (emergency) unless you know why not."
            onChange={(e) => setReserved(e.target.value)} />
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
          <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save plan</Button></div>
        </form>
      ) : (
        <dl className="dl">
          <dt>Length</dt><dd>{f.extension_length} digits</dd>
          <dt>Range</dt><dd className="mono">{f.first_extension} – {f.last_extension}</dd>
          <dt>Reserved</dt><dd className="mono">{f.reserved_prefixes.join(", ") || "none"}</dd>
        </dl>
      )}
    </Card>
  );
}
