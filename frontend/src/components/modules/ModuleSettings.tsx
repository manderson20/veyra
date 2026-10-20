// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Checkbox, Dialog, SelectField, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { ModuleConfigField } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";

interface ConfigResponse {
  fields: ModuleConfigField[];
  values: Record<string, unknown>;
}

/** Settings of a module, generated from its [[config]] fields
    (docs/MODULE_CATALOG.md §5): installation-wide ones, or the
    organization-scoped ones of a chosen organization. Secrets are write-only. */
export function ModuleSettings({ moduleId, name, onClose }: { moduleId: string | null; name: string; onClose: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(moduleId !== null);
  const [org, setOrg] = useState("");
  useOnChange(moduleId, () => setOrg(""));
  const config = useApiData<ConfigResponse>(moduleId ? `/modules/${encodeURIComponent(moduleId)}/config` : null, org ? { organization_id: org } : undefined);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  useOnChange(config.data, () => {
    if (!config.data) return;
    const v: Record<string, unknown> = {};
    for (const f of config.data.fields) v[f.key] = f.type === "secret" ? null : config.data.values[f.key] ?? f.default ?? (f.type === "boolean" ? false : "");
    setValues(v);
    errors.clear();
  });
  const fields = config.data?.fields ?? [];
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!moduleId) return;
    setBusy(true);
    errors.clear();
    try {
      const body: Record<string, unknown> = {};
      for (const f of fields) {
        const v = values[f.key];
        if (f.type === "secret" && (v === null || v === undefined)) continue;
        body[f.key] = f.type === "integer" && v !== "" && v !== null ? Number(v) : v;
      }
      await api.put(`/modules/${encodeURIComponent(moduleId)}/config`, { values: body, organization_id: org || null });
      toast.success("Settings saved");
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={moduleId !== null} onClose={onClose} busy={busy} title={`Settings: ${name}`}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="module-settings-form" loading={busy} disabled={!fields.length}>Save</Button></>}>
      <form id="module-settings-form" className="stack stack--sm" onSubmit={submit}>
        {organizations.length ? (
          <SelectField label="Settings for" value={org} onChange={(e) => setOrg(e.target.value)}
            help="Some modules have settings that each organization can have its own value for."
            options={[{ value: "", label: "The whole installation" }, ...organizations.map((o) => ({ value: o.id, label: o.name }))]} />
        ) : null}
        {config.data && fields.length === 0 ? <p className="subtle">{org ? "This module has no settings per organization." : "This module has no installation-wide settings."}</p> : null}
        {fields.map((f) => {
          const common = { label: f.label, help: f.help ?? undefined, error: errors.fields[f.key], required: f.required ?? false };
          if (f.type === "boolean") {
            return <Checkbox key={f.key} label={f.label} description={f.help ?? undefined} checked={Boolean(values[f.key])} onChange={(e) => setValues({ ...values, [f.key]: e.target.checked })} />;
          }
          if (f.type === "choice") {
            return <SelectField key={f.key} {...common} value={String(values[f.key] ?? "")} options={(f.choices ?? []).map((c) => ({ value: c, label: c }))} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />;
          }
          if (f.type === "secret") {
            const has = (config.data?.values[f.key] as { has_value?: boolean } | undefined)?.has_value;
            return <TextField key={f.key} {...common} type="password" autoComplete="new-password" value={String(values[f.key] ?? "")}
              placeholder={has ? "Stored; leave empty to keep it" : "Not set"} onChange={(e) => setValues({ ...values, [f.key]: e.target.value || null })} />;
          }
          return <TextField key={f.key} {...common} type={f.type === "integer" ? "number" : "text"} min={f.min ?? undefined} max={f.max ?? undefined} maxLength={f.max_length ?? undefined}
            value={String(values[f.key] ?? "")} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />;
        })}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

/** "Restart Veyra's services" when new module code waits (docs/MODULE_CATALOG.md §4). */
export function RestartBanner({ needed }: { needed: string[] }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!needed.length) return null;
  const restart = async () => {
    setBusy(true);
    try {
      await api.post("/modules/restart-services");
      toast.success("Veyra's services are restarting", "This page reloads in about 20 seconds. Calls are not affected.");
      window.setTimeout(() => window.location.reload(), 20_000);
    } catch (err) {
      setBusy(false);
      toast.error("Not restarted", String(err));
    }
  };
  return (
    <Callout tone="warn" title="New module code is waiting">
      <div className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <span>{needed.join(", ")} {needed.length === 1 ? "was" : "were"} updated. The new code runs after Veyra&apos;s services restart (about 10 seconds; Asterisk and calls are not affected).</span>
        <Button variant="primary" icon="refresh" loading={busy} onClick={restart}>Restart Veyra services</Button>
      </div>
    </Callout>
  );
}
