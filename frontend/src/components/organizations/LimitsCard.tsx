// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { OrganizationLimits } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

const num = (v: string): number | null => (v.trim() ? Number(v) : null);
const text = (v: number | null | undefined) => (v == null ? "" : String(v));

/** What the organization may use (docs/MULTI_TENANCY_MSP.md §8): set by
 * platform administrators, shown to the organization's own. */
export function LimitsCard({ organizationId, editable }: { organizationId: string; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<OrganizationLimits>(`/organizations/${encodeURIComponent(organizationId)}/limits`);
  const [calls, setCalls] = useState("");
  const [exts, setExts] = useState("");
  const [devices, setDevices] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(data.data, (d) => {
    if (d) {
      setCalls(text(d.max_outside_calls));
      setExts(text(d.max_extensions));
      setDevices(text(d.max_devices));
    }
  });
  const d = data.data;
  if (!d) return null;
  const dirty = calls !== text(d.max_outside_calls) || exts !== text(d.max_extensions) || devices !== text(d.max_devices);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const out = await api.put<OrganizationLimits>(`/organizations/${encodeURIComponent(organizationId)}/limits`, {
        max_outside_calls: num(calls),
        max_extensions: num(exts),
        max_devices: num(devices),
      });
      data.setData(out);
      toast.success("Limits saved", calls !== text(d.max_outside_calls) ? "Deploy changes to apply the call limit." : undefined);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Limits" subtitle={editable ? "What this organization may use; empty means no limit. Emergency calls are never counted or refused." : "Set by a platform administrator; empty means no limit."}>
      <form className="stack stack--sm" onSubmit={save}>
        <TextField label="Outside calls at once" type="number" min={1} value={calls} disabled={!editable} error={errors.fields.max_outside_calls}
          help="Calls through any trunk, in and out together. A call over the limit hears that all circuits are busy." onChange={(e) => setCalls(e.target.value)} />
        <TextField label="Extensions" type="number" min={1} value={exts} disabled={!editable} error={errors.fields.max_extensions}
          help={`${d.extensions} now.`} onChange={(e) => setExts(e.target.value)} />
        <TextField label="Phones and devices" type="number" min={1} value={devices} disabled={!editable} error={errors.fields.max_devices}
          help={`${d.devices} now.`} onChange={(e) => setDevices(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save limits</Button></div> : null}
      </form>
    </Card>
  );
}
