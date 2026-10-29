// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button, Callout, Card, DataTable, PageHeader, SelectField, Switch, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { FeatureCode, FeatureCodePreset, FeatureCodes } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

type Draft = Record<string, { code: string; enabled: boolean }>;

function toDraft(codes: FeatureCode[]): Draft {
  return Object.fromEntries(codes.map((c) => [c.key, { code: c.code, enabled: c.enabled }]));
}

export default function FeatureCodesPage() {
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const editable = can("routing.write");
  const data = useApiData<FeatureCodes>("/telephony/feature-codes");
  const [draft, setDraft] = useState<Draft>({});
  const [busy, setBusy] = useState(false);
  const presets = useApiData<FeatureCodePreset[]>("/telephony/feature-codes/presets");
  const [loaded, setLoaded] = useState<FeatureCodePreset | null>(null);
  useOnChange(data.data, (d) => { if (d) { setDraft(toDraft(d.codes)); setLoaded(null); } });
  const codes = data.data?.codes ?? [];
  const dirty = codes.some((c) => draft[c.key] && (draft[c.key]!.code !== c.code || draft[c.key]!.enabled !== c.enabled));

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      const changed = Object.fromEntries(codes.filter((c) => draft[c.key] && (draft[c.key]!.code !== c.code || draft[c.key]!.enabled !== c.enabled)).map((c) => [c.key, { code: draft[c.key]!.code.trim(), enabled: draft[c.key]!.enabled }]));
      data.setData(await api.put<FeatureCodes>("/telephony/feature-codes", { codes: changed }));
      toast.success("Feature codes saved", "Deploy changes to put them on the phone system.");
    } catch (err) {
      errors.set(err);
      toast.error("Could not save the feature codes", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  // Load a code set into the draft (issue #164): nothing is saved until Save.
  const load = (key: string) => {
    const preset = (presets.data ?? []).find((p) => p.key === key);
    if (!preset) return;
    errors.clear();
    setDraft((d) => Object.fromEntries(codes.map((c) => [c.key, { code: preset.codes[c.key] ?? c.default_code, enabled: d[c.key]?.enabled ?? c.enabled }])));
    setLoaded(preset);
  };
  const pending = codes.filter((c) => draft[c.key] && draft[c.key]!.code !== c.code);

  const columns: Column<FeatureCode>[] = [
    { key: "what", header: "Feature", render: (c) => <span><span className="table__primary" style={{ display: "block" }}>{c.label}</span><span className="table__secondary">{c.description}{c.takes_number ? " Dialled with a number after the code." : ""}</span></span> },
    {
      key: "code", header: "Code", width: "160px", render: (c) => (
        <TextField label={<span className="sr-only">Code for {c.label}</span>} value={draft[c.key]?.code ?? c.code} disabled={!editable || !(draft[c.key]?.enabled ?? c.enabled)} error={errors.fields[c.key]} spellCheck={false}
          onChange={(e) => setDraft((d) => ({ ...d, [c.key]: { code: e.target.value, enabled: d[c.key]?.enabled ?? c.enabled } }))} />
      ),
    },
    { key: "default", header: "Default", render: (c) => <span className="mono subtle">{c.default_code}</span> },
    {
      key: "enabled", header: "Enabled", render: (c) => (
        <Switch label={<span className="sr-only">{c.label} enabled</span>} checked={draft[c.key]?.enabled ?? c.enabled} disabled={!editable}
          onChange={(e) => setDraft((d) => ({ ...d, [c.key]: { code: d[c.key]?.code ?? c.code, enabled: e.target.checked } }))} />
      ),
    },
  ];
  const fixed = Object.entries(data.data?.fixed ?? {});
  return (
    <div className="stack">
      <PageHeader title="Feature Codes" description="What a phone dials to change its own settings. The defaults follow FreePBX so a migrating site keeps its habits. Codes start with * or #, so they never collide with extension numbers; a change takes effect at the next deployment."
        actions={editable ? <Button variant="primary" onClick={save} loading={busy} disabled={!dirty}>Save</Button> : null} />
      {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      {editable && (presets.data ?? []).length ? (
        <Card title="Code sets" subtitle="Load the codes staff know from their old phone system into the table below, check them, then Save.">
          <div className="form-grid">
            <SelectField label="Load a code set" value="" placeholder="Choose…" options={(presets.data ?? []).map((p) => ({ value: p.key, label: p.name }))} onChange={(e) => load(e.target.value)} />
          </div>
          {loaded ? (
            <Callout tone="neutral" title={`${loaded.name} loaded, not saved yet`}>
              <p style={{ marginTop: 0 }}>{loaded.description}</p>
              {pending.length ? <p>Changes: {pending.map((c, i) => <span key={c.key}>{i ? "; " : ""}{c.label} <span className="mono">{c.code}</span> → <span className="mono">{draft[c.key]!.code}</span></span>)}.</p> : <p>The codes already match this set.</p>}
              {loaded.notes.length ? <ul style={{ margin: 0, paddingLeft: "1.2em" }}>{loaded.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
            </Callout>
          ) : null}
        </Card>
      ) : null}
      <Card flush>
        <DataTable columns={columns} rows={codes} rowKey={(c) => c.key} loading={data.loading && !data.data} error={data.error} onRetry={data.reload} caption="Feature codes" />
      </Card>
      <Card title="Always available">
        <p className="subtle">These codes are part of every installation and cannot be changed: {fixed.map(([code, what], i) => <span key={code}>{i ? ", " : ""}<span className="mono">{code}</span> {what}</span>)}, and <span className="mono">**</span> followed by an extension picks up its ringing call.</p>
      </Card>
    </div>
  );
}
