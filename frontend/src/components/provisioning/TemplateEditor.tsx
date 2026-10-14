// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, SelectField, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { TemplateDetail } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

interface ExportDoc {
  manifest: { template: Record<string, unknown>; files: { name: string; source: string; format: string }[]; variables: unknown[]; defaults: Record<string, unknown>; features: string[]; spec_version: number };
  sources: Record<string, string>;
}

/** Edit a local template's manifest fields and source files in place (docs/DEVICE_PROVISIONING.md §7). */
export function TemplateEditor({ template, onSaved }: { template: TemplateDetail; onSaved: (t: TemplateDetail) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const doc = useApiData<ExportDoc>(`/provisioning/templates/${encodeURIComponent(template.key)}/export`);
  const [name, setName] = useState(template.name);
  const [version, setVersion] = useState(template.version);
  const [models, setModels] = useState(template.models.join(", "));
  const [status, setStatus] = useState(template.status);
  const [description, setDescription] = useState(template.description);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState("");
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);

  useOnChange(doc.data, (d) => {
    if (d) {
      setSources(d.sources);
      setCurrent(Object.keys(d.sources)[0] ?? "");
    }
  });
  useOnChange(template, (t) => { setName(t.name); setVersion(t.version); setModels(t.models.join(", ")); setStatus(t.status); setDescription(t.description); });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!doc.data) return;
    setBusy(true);
    errors.clear();
    setProblems([]);
    try {
      const manifest = {
        ...doc.data.manifest,
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
        <Card title="Files" subtitle="Jinja2 sources rendered in a sandbox. Use {% extends %} and {% block %} to override parts of the parent.">
          <div className="stack stack--sm">
            <SelectField label="File" value={current} options={files.map((f) => ({ value: f, label: f }))} onChange={(e) => setCurrent(e.target.value)} />
            {current ? (
              <TextArea label={<span className="mono">{current}</span>} rows={22} spellCheck={false} style={{ fontFamily: "var(--font-mono)", fontSize: 13 }} value={sources[current] ?? ""} onChange={(e) => setSources((s) => ({ ...s, [current]: e.target.value }))} />
            ) : <p className="muted">This template has no source files of its own.</p>}
          </div>
        </Card>
      </div>
      {problems.length ? <Callout tone="danger" title="The template did not validate"><ul style={{ margin: 0, paddingLeft: 18 }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul></Callout> : errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="form-actions"><Button variant="primary" type="submit" loading={busy} icon="check">Save template</Button></div>
    </form>
  );
}
