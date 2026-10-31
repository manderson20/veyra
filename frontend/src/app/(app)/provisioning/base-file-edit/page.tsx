// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, LoadingState, PageHeader, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { BaseEdit, BaseFile, BaseFileSetting, DeviceProfile, Page as ApiPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

/** The file with each setting's value as a button; secrets stay plain text. */
function FileText({ file, edits, model, chosen, onChoose }: { file: BaseFile; edits: BaseEdit[]; model: string; chosen: string | null; onChoose: (s: BaseFileSetting) => void }) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const s of file.settings) {
    if (s.start < at) continue;
    parts.push(file.content.slice(at, s.start));
    const shown = file.content.slice(s.start, s.end);
    if (s.secret) {
      parts.push(shown);
    } else {
      const edited = edits.some((e) => e.file === file.file && e.parameter === s.parameter && e.models.includes(model));
      parts.push(
        <button key={`${s.parameter}-${s.start}`} type="button" title={s.parameter} aria-label={`Change ${s.parameter}`} onClick={() => onChoose(s)}
          style={{ font: "inherit", color: "inherit", cursor: "pointer", padding: "0 2px", border: 0, borderRadius: 3, minWidth: 12, display: "inline-block",
            textDecoration: "underline dotted", background: chosen === s.parameter ? "var(--accent-soft)" : edited ? "var(--warn-soft)" : "transparent" }}>
          {shown || " "}
        </button>,
      );
    }
    at = s.end;
  }
  parts.push(file.content.slice(at));
  return <pre className="code" tabIndex={0} style={{ maxHeight: "60vh", overflow: "auto" }}>{parts}</pre>;
}

interface Panel { parameter: string; value: string; models: string[]; isNew: boolean }

function BaseFileEdit() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const { can, brands } = useSession();
  const errors = useFormErrors();
  const templateId = params.get("template") ?? "";
  const [brand, setBrand] = useState("");
  const [modelChoice, setModel] = useState("");
  const [fileChoice, setFile] = useState("");
  const [panel, setPanel] = useState<Panel | null>(null);
  const [busy, setBusy] = useState(false);
  const [updating, setUpdating] = useState(false);

  const template = useApiData<DeviceProfile>(templateId ? `/device-profiles/${encodeURIComponent(templateId)}` : null);
  const shownBrand = brand || template.data?.manufacturer || "";
  const templates = useApiData<ApiPage<DeviceProfile>>(shownBrand ? "/device-profiles" : null, { manufacturer: shownBrand, limit: 200 });
  const t = template.data?.id === templateId ? template.data : null;
  const modelNames = Object.keys(t?.models ?? {});
  const model = modelNames.includes(modelChoice) ? modelChoice : modelNames[0] ?? "";
  const files = useApiData<BaseFile[]>(t && model ? `/device-profiles/${t.id}/base-files` : null, { model });
  const file = files.data?.find((f) => f.file === fileChoice) ?? files.data?.[0];
  const editable = can("devices.write") && can("provisioning.write");
  const edits = t?.base_edits ?? [];

  useOnChange(templateId, () => { setPanel(null); setModel(""); setFile(""); errors.clear(); });

  const choose = (s: BaseFileSetting) => {
    if (!file || !editable) return;
    errors.clear();
    const existing = edits.find((e) => e.file === file.file && e.parameter === s.parameter && e.models.includes(model));
    setPanel({ parameter: s.parameter, value: existing && !existing.remove ? existing.value : s.value, models: existing?.models ?? [model], isNew: false });
  };
  /** The other edits, with these models no longer on this setting. */
  const without = (fileName: string, parameter: string, models: string[]) => edits
    .map((e) => (e.file === fileName && e.parameter === parameter ? { ...e, models: e.models.filter((m) => !models.includes(m)) } : e))
    .filter((e) => e.models.length > 0);
  const save = async (next: BaseEdit[], done: string) => {
    if (!t) return;
    setBusy(true);
    errors.clear();
    try {
      template.setData(await api.put<DeviceProfile>(`/device-profiles/${t.id}/base-edits`, { edits: next }));
      files.reload();
      setPanel(null);
      toast.success(done, "Phones pick it up at their next check, or choose Update Phones.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const change = (remove: boolean) => {
    if (!panel || !file) return;
    void save([...without(file.file, panel.parameter, panel.models), { file: file.file, parameter: panel.parameter, value: remove ? "" : panel.value, remove, models: panel.models }], remove ? "Entry deleted" : "Base file changed");
  };
  const updatePhones = async () => {
    if (!t) return;
    setUpdating(true);
    try {
      const r = await api.post<{ phones: number; asked: number }>(`/device-profiles/${t.id}/update-phones`, {});
      toast.success("Phones asked to update", `${r.asked} of ${r.phones} accepted the request.`);
    } catch (err) {
      toast.error("The phones were not asked", errorMessage(err));
    } finally {
      setUpdating(false);
    }
  };
  const columns: Column<BaseEdit>[] = [
    { key: "parameter", header: "Parameter", render: (e) => <span className="mono">{e.parameter}</span> },
    { key: "value", header: "Value", render: (e) => e.remove ? <Badge tone="warn">Deleted</Badge> : <span className="mono">{e.value || <span className="subtle">empty</span>}</span> },
    { key: "models", header: "Applies to", render: (e) => <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{e.models.map((m) => <span key={m} className="kv-chip">{m}</span>)}</span> },
    { key: "file", header: "File", render: (e) => <span className="mono">{e.file}</span> },
    ...(editable ? [{ key: "actions", header: "", render: (e: BaseEdit) => <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save(without(e.file, e.parameter, e.models), "Change undone")}>Undo</Button> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Base File Edit" description="Change single settings of the files a template's phones download. Changes belong to the template, survive updates and are applied after the file is built."
        actions={t && editable ? <Button loading={updating} disabled={!t.devices} onClick={() => void updatePhones()}>Update Phones</Button> : null} />
      <Card>
        <div className="form-grid">
          <SelectField label="Brand" value={shownBrand} placeholder="Choose a brand" options={brands.filter((b) => b !== "Other").map((b) => ({ value: b, label: b }))} onChange={(e) => { setBrand(e.target.value); router.replace("/provisioning/base-file-edit/"); }} />
          <SelectField label="Template" value={t?.id ?? ""} disabled={!shownBrand} placeholder={shownBrand ? "Choose a template" : "Choose a brand first"} options={(templates.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => router.replace(`/provisioning/base-file-edit/?template=${e.target.value}`)} />
          <SelectField label="Model" value={model} disabled={!t} placeholder="Choose a template first" options={modelNames.map((m) => ({ value: m, label: m }))} onChange={(e) => { setModel(e.target.value); setPanel(null); }} />
          <SelectField label="File" value={file?.file ?? ""} disabled={!files.data?.length} placeholder="Choose a model first" options={(files.data ?? []).map((f) => ({ value: f.file, label: f.filename }))} onChange={(e) => { setFile(e.target.value); setPanel(null); }} />
        </div>
      </Card>
      {!t ? <Card><EmptyState icon="template" title="Choose a template">Its changes apply to its phones only.</EmptyState></Card> : null}
      {files.error ? <Callout tone="danger">{errorMessage(files.error)}</Callout> : null}
      {t && files.loading && !files.data ? <LoadingState /> : null}
      {t && file ? (
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <Card title={file.filename} subtitle={<>Choose a setting to change it. The line and server details are examples and passwords are hidden. Line keys and paging appear on a real phone&apos;s Configuration tab.</>}>
            <FileText file={file} edits={edits} model={model} chosen={panel?.parameter ?? null} onChoose={choose} />
            {editable ? <div style={{ marginTop: 8 }}><Button size="sm" icon="plus" onClick={() => { errors.clear(); setPanel({ parameter: "", value: "", models: [model], isNew: true }); }}>Add Entry</Button></div> : null}
          </Card>
          <Card title={panel ? (panel.isNew ? "Add Entry" : "Change setting") : "Setting"}>
            {panel ? (
              <div className="stack stack--sm">
                {panel.isNew
                  ? <TextField label="Parameter" required className="mono" value={panel.parameter} error={errors.fields.edits} help="As the phone maker's documentation names it." onChange={(e) => setPanel({ ...panel, parameter: e.target.value.trim() })} />
                  : <p className="field__label" style={{ margin: 0 }}>Parameter: <span className="mono">{panel.parameter}</span></p>}
                <TextField label="Value" value={panel.value} autoComplete="off" onChange={(e) => setPanel({ ...panel, value: e.target.value })} />
                <div>
                  <p className="field__label" style={{ marginTop: 0 }}>Applies to Model(s)</p>
                  <div className="row" style={{ gap: 4, flexWrap: "wrap" }}>
                    {modelNames.map((m) => {
                      const on = panel.models.includes(m);
                      return <button key={m} type="button" className="kv-chip" aria-pressed={on} style={{ cursor: "pointer", opacity: on ? 1 : 0.5, fontWeight: on ? 600 : 400 }}
                        onClick={() => setPanel({ ...panel, models: on ? panel.models.filter((x) => x !== m) : [...panel.models, m] })}>{m}</button>;
                    })}
                  </div>
                </div>
                {!panel.isNew && errors.fields.edits ? <p className="field__error">{errors.fields.edits}</p> : null}
                {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
                <div className="form-actions">
                  <Button variant="ghost" disabled={busy} onClick={() => { setPanel(null); errors.clear(); }}>Cancel</Button>
                  {!panel.isNew ? <Button variant="danger" disabled={busy || !panel.models.length} onClick={() => change(true)}>Delete Entry</Button> : null}
                  <Button variant="primary" loading={busy} disabled={!panel.models.length || !panel.parameter} onClick={() => change(false)}>Change Basefile</Button>
                </div>
              </div>
            ) : <p className="muted">{editable ? "Choose a setting in the file." : "You can view but not change these files."}</p>}
          </Card>
        </div>
      ) : null}
      {t ? (
        <Card title="Changes in this template" subtitle={<>Official base files stay as they are. To change the file&apos;s structure, use the code editor under <Link href="/provisioning/">Base Files</Link>.</>} flush>
          <DataTable columns={columns} rows={edits} rowKey={(e) => `${e.file}|${e.parameter}|${e.models.join()}`} caption="Changes in this template" empty={<EmptyState compact icon="template" title="No changes yet" />} />
        </Card>
      ) : null}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><BaseFileEdit /></Suspense>;
}
