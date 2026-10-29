// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { InsertPanel } from "@/components/provisioning/InsertPanel";
import { defaultValue, newRow, rowToVariable, VariablesEditor, type VarRow } from "@/components/provisioning/VariablesEditor";
import { Button, Callout, Card, SelectField, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { TemplateCatalog, TemplateDetail, TemplateVariable } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

interface ExportDoc {
  manifest: { template: Record<string, unknown>; files: { name: string; source: string; format: string }[]; variables: TemplateVariable[]; defaults: Record<string, string | number | boolean>; features: string[]; spec_version: number };
  sources: Record<string, string>;
}

const SOURCE_ID = "template-source";

/** Edit a local template's manifest fields, variables and source files in place (docs/DEVICE_PROVISIONING.md §7). */
export function TemplateEditor({ template, onSaved }: { template: TemplateDetail; onSaved: (t: TemplateDetail) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const doc = useApiData<ExportDoc>(`/provisioning/templates/${encodeURIComponent(template.key)}/export`);
  const catalog = useApiData<TemplateCatalog>("/provisioning/template-catalog");
  const [name, setName] = useState(template.name);
  const [version, setVersion] = useState(template.version);
  const [models, setModels] = useState(template.models.join(", "));
  const [status, setStatus] = useState(template.status);
  const [description, setDescription] = useState(template.description);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState("");
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [rows, setRows] = useState<VarRow[]>([]);
  const [defaults, setDefaults] = useState<Record<string, string>>({});

  useOnChange(doc.data, (d) => {
    if (d) {
      setSources(d.sources);
      setCurrent((c) => (c && c in d.sources ? c : Object.keys(d.sources)[0] ?? ""));
      setRows(d.manifest.variables.map((v) => newRow(v)));
      setDefaults(Object.fromEntries(Object.entries(d.manifest.defaults ?? {}).map(([k, v]) => [k, String(v)])));
    }
  });

  const own = new Set((doc.data?.manifest.variables ?? []).map((v) => v.name));
  const core = new Set(catalog.data?.core_variables ?? []);
  const inherited = template.variables.filter((v) => !own.has(v.name) && !core.has(v.name));

  const insert = (text: string) => {
    if (!current) return;
    const el = document.getElementById(SOURCE_ID) as HTMLTextAreaElement | null;
    const value = sources[current] ?? "";
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? start;
    setSources((s) => ({ ...s, [current]: value.slice(0, start) + text + value.slice(end) }));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + text.length, start + text.length);
    });
  };
  useOnChange(template, (t) => { setName(t.name); setVersion(t.version); setModels(t.models.join(", ")); setStatus(t.status); setDescription(t.description); });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!doc.data) return;
    setBusy(true);
    errors.clear();
    setProblems([]);
    try {
      // Defaults for inherited variables: empty keeps the parent's.
      const nextDefaults: Record<string, string | number | boolean> = { ...doc.data.manifest.defaults };
      for (const v of inherited) {
        const value = defaultValue(v.type, defaults[v.name] ?? "");
        if (value === null || v.sensitive) delete nextDefaults[v.name];
        else nextDefaults[v.name] = value;
      }
      const manifest = {
        ...doc.data.manifest,
        variables: rows.map(rowToVariable),
        defaults: nextDefaults,
        template: {
          ...doc.data.manifest.template,
          name: name.trim(),
          version: version.trim(),
          models: models.split(",").map((m) => m.trim()).filter(Boolean),
          status,
          description,
        },
      };
      const saved = await api.put<TemplateDetail>(`/provisioning/templates/${encodeURIComponent(template.key)}`, { manifest, sources });
      toast.success("Template saved", "Phones using it pick up the change at their next provisioning check.");
      onSaved(saved);
      doc.reload();
    } catch (err) {
      const list = (err as { errors?: { message: string }[] }).errors?.map((x) => x.message) ?? [];
      setProblems(list);
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  if (!doc.data) return <Card><p className="muted">Loading the template sources…</p></Card>;
  const files = Object.keys(sources);
  return (
    <form className="stack" onSubmit={save}>
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Template">
          <div className="stack stack--sm">
            <div className="form-grid">
              <TextField label="Name" required value={name} error={errors.fields["manifest.template.name"]} onChange={(e) => setName(e.target.value)} />
              <TextField label="Version" required value={version} error={errors.fields["manifest.template.version"]} help="Semantic version; a new version keeps a copy of the previous one." onChange={(e) => setVersion(e.target.value)} />
            </div>
            <TextField label="Models" value={models} disabled={template.abstract} placeholder={template.abstract ? "Family: models come from the templates under it" : "VVX 411, VVX 450"} help="Comma-separated model names this template serves." onChange={(e) => setModels(e.target.value)} />
            <SelectField label="Status" value={status} options={[{ value: "experimental", label: "Experimental" }, { value: "stable", label: "Stable (verified on hardware)" }, { value: "deprecated", label: "Deprecated" }]} onChange={(e) => setStatus(e.target.value as TemplateDetail["status"])} />
            <TextArea label="Description" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
            <dl className="dl">
              <dt>Parent</dt><dd className="mono">{template.parent ?? "—"}</dd>
              <dt>Key</dt><dd className="mono">{template.key}</dd>
            </dl>
          </div>
        </Card>
        <Card title="Variables" subtitle="Settings a profile or device can adjust; files use them as {{ name }}.">
          <VariablesEditor rows={rows} onRows={setRows} inherited={inherited} defaults={defaults} onDefaults={setDefaults} />
        </Card>
      </div>
      <Card title="Files" subtitle="Jinja2 sources rendered in a sandbox. Use {% extends %} and {% block %} to override parts of the parent.">
        <div className="template-files">
          <div className="stack stack--sm">
            <SelectField label="File" value={current} options={files.map((f) => ({ value: f, label: f }))} onChange={(e) => setCurrent(e.target.value)} />
            {current ? (
              <TextArea id={SOURCE_ID} label={<span className="mono">{current}</span>} rows={26} spellCheck={false} style={{ fontFamily: "var(--font-mono)", fontSize: 13 }} value={sources[current] ?? ""} onChange={(e) => setSources((s) => ({ ...s, [current]: e.target.value }))} />
            ) : <p className="muted">This template has no source files of its own.</p>}
          </div>
          {catalog.data && current ? <InsertPanel catalog={catalog.data} variables={template.variables} onInsert={insert} /> : null}
        </div>
      </Card>
      {problems.length ? <Callout tone="danger" title="The template did not validate"><ul style={{ margin: 0, paddingLeft: 18 }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul></Callout> : errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="form-actions"><Button variant="primary" type="submit" loading={busy} icon="check">Save template</Button></div>
    </form>
  );
}
