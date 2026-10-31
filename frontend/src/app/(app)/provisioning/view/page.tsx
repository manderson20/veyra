// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { TEMPLATE_SOURCE } from "@/components/common/labels";
import { CustomizeDialog } from "@/components/provisioning/CustomizeDialog";
import { TemplateEditor } from "@/components/provisioning/TemplateEditor";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfirmDialog,
  DataTable,
  Dialog,
  ErrorState,
  LoadingState,
  PageHeader,
  SelectField,
  TabPanel,
  Tabs,
  TextArea,
  TextField,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { RenderedFile, TemplateDetail, TemplateVariable } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const SAMPLE: Record<string, string> = {
  extension_number: "1001",
  sip_username: "ext1001",
  sip_password: "example-secret",
  sip_server: "pbx.example.local",
  display_name: "Front Office",
};

interface StoredTemplate { key: string; version: string; manifest: Record<string, unknown>; sources: Record<string, string>; problems: string[] }

/** A local template that does not load: its problems and its stored text, to fix or delete (issue #350). */
function StoredTemplateRepair({ templateKey, error, onFixed }: { templateKey: string; error: unknown; onFixed: () => void }) {
  const router = useRouter();
  const base = `/provisioning/templates/${encodeURIComponent(templateKey)}`;
  const stored = useApiData<StoredTemplate>(`${base}/stored`);
  const [manifest, setManifest] = useState<string | null>(null);
  const [sources, setSources] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string | null>(null);
  useOnChange(stored.data, (d) => {
    if (d) {
      setManifest(JSON.stringify(d.manifest, null, 2));
      setSources(d.sources);
    }
  });
  if (stored.error) return <ErrorState title="Could not load base file" error={error as { message: string }} onRetry={onFixed} />;
  if (!stored.data || manifest === null || sources === null) return <LoadingState />;
  const save = async () => {
    setBusy(true);
    setProblems(null);
    try {
      await api.put(base, { manifest: JSON.parse(manifest), sources });
      onFixed();
    } catch (err) {
      setProblems(err instanceof SyntaxError ? `The manifest is not valid JSON: ${err.message}` : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    setProblems(null);
    try {
      await api.del(base);
      router.push("/provisioning/");
    } catch (err) {
      setProblems(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <PageHeader back={{ href: "/provisioning/", label: "Base files" }} title={templateKey} description="This base file does not load, so phones cannot use it. Fix it here or delete it." />
      <Callout tone="danger" title="What is wrong"><ul style={{ margin: 0, paddingLeft: 18 }}>{stored.data.problems.map((m) => <li key={m}>{m}</li>)}</ul></Callout>
      <Card title="Stored base file">
        <div className="stack stack--sm">
          <TextArea label="Manifest (JSON)" value={manifest} rows={14} className="mono" onChange={(e) => setManifest(e.target.value)} />
          {Object.entries(sources).map(([name, text]) => <TextArea key={name} label={name} value={text} rows={12} className="mono" onChange={(e) => setSources({ ...sources, [name]: e.target.value })} />)}
          {problems ? <Callout tone="danger">{problems}</Callout> : null}
          <div className="form-actions"><Button variant="danger" onClick={remove} disabled={busy}>Delete base file</Button><Button variant="primary" onClick={save} loading={busy}>Save and check</Button></div>
        </div>
      </Card>
    </div>
  );
}

function TemplateView() {
  const key = useSearchParams().get("key");
  const router = useRouter();
  const { can } = useSession();
  const detail = useApiData<TemplateDetail>(key ? `/provisioning/templates/${encodeURIComponent(key)}` : null);
  const [tab, setTab] = useState("overview");
  const [exportText, setExportText] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [parentBusy, setParentBusy] = useState(false);
  const [parentError, setParentError] = useState<string | null>(null);
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  if (!key) return <ErrorState title="No base file selected" error={{ message: "Open a base file from the list." }} />;
  if (detail.error) return can("provisioning.write") ? <StoredTemplateRepair templateKey={key} error={detail.error} onFixed={detail.reload} /> : <ErrorState title="Could not load base file" error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <LoadingState />;
  const t = detail.data;

  const fetchExport = async () => {
    setExportError(null);
    const doc = await api.get<Record<string, unknown>>(`/provisioning/templates/${encodeURIComponent(t.key)}/export`);
    return doc;
  };
  const openExport = async () => {
    try {
      setExportText(JSON.stringify(await fetchExport(), null, 2));
    } catch (err) {
      setExportError(errorMessage(err));
      setExportText("");
    }
  };
  const acceptParent = async () => {
    setParentBusy(true);
    setParentError(null);
    try {
      detail.setData(await api.post<TemplateDetail>(`/provisioning/templates/${encodeURIComponent(t.key)}/accept-parent`, {}));
    } catch (err) {
      setParentError(errorMessage(err));
    } finally {
      setParentBusy(false);
    }
  };
  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/provisioning/templates/${encodeURIComponent(t.key)}`);
      router.push("/provisioning/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  const varColumns: Column<TemplateVariable>[] = [
    { key: "name", header: "Variable", render: (v) => <span className="mono">{v.name}</span> },
    { key: "desc", header: "Description", render: (v) => v.description || "—" },
    { key: "type", header: "Type", render: (v) => v.type },
    {
      key: "flags",
      header: "",
      render: (v) => (
        <span className="row">
          {v.required ? <Badge tone="outline">Required</Badge> : null}
          {v.sensitive ? <Badge tone="warn" icon="lock">Sensitive</Badge> : null}
        </span>
      ),
    },
    { key: "default", header: "Default", render: (v) => (v.sensitive ? <span className="subtle">hidden</span> : <span className="mono">{t.defaults[v.name] !== undefined ? String(t.defaults[v.name]) : "—"}</span>) },
  ];

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/provisioning/", label: "Base files" }}
        title={t.name}
        description={
          <span className="row">
            <span className="mono">{t.key}</span>
            <span className="mono">v{t.version}</span>
            <Badge tone={TEMPLATE_SOURCE[t.source]?.tone ?? "neutral"}>{TEMPLATE_SOURCE[t.source]?.label ?? t.source}</Badge>
            {t.status !== "stable" ? <Badge tone="warn">{t.status}</Badge> : null}
          </span>
        }
        actions={
          <>
            <Button icon="download" onClick={openExport}>Export</Button>
            {can("provisioning.write") ? <Button icon="copy" onClick={() => setCustomizeOpen(true)}>Customize</Button> : null}
            {can("provisioning.write") && t.source === "local" ? <Button variant="ghost" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
          </>
        }
      />
      {t.parent_updated ? (
        <Callout tone="info" title="The parent base file has a new version">
          <p style={{ marginTop: 0 }}>This base file was made from <span className="mono">{t.parent}</span> version {t.parent_version}; it is now version {t.parent_current_version}. Phones already use the new version together with your changes. Check <strong>Preview</strong>, and when it is right, take the new version so that this note goes away.</p>
          {parentError ? <p>{parentError}</p> : null}
          {can("provisioning.write") ? <Button size="sm" loading={parentBusy} onClick={acceptParent}>Take version {t.parent_current_version}</Button> : null}
        </Callout>
      ) : null}
      {t.status === "experimental" ? (
        <Callout tone="warn" title="Experimental base file">This base file has not yet been verified on hardware. Test it with a single phone before wider use.</Callout>
      ) : null}
      {t.validation.length ? (
        <Callout tone="danger" title="Validation problems">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{t.validation.map((v) => <li key={v}>{v}</li>)}</ul>
        </Callout>
      ) : null}
      {exportError ? <Callout tone="danger">{exportError}</Callout> : null}

      <div>
        <Tabs idBase="tpl" active={tab} onChange={setTab} tabs={[
          { id: "overview", label: "Overview" },
          { id: "variables", label: `Variables (${t.variables.length})` },
          { id: "preview", label: "Preview" },
          ...(t.source === "local" && can("provisioning.write") ? [{ id: "editor", label: "Edit" }] : []),
        ]} />
        <TabPanel idBase="tpl" id="overview" active={tab}>
          <div className="grid grid--2" style={{ alignItems: "start" }}>
            <Card title="Details">
              <dl className="dl">
                <dt>Manufacturer</dt><dd>{t.manufacturer}</dd>
                <dt>Models</dt><dd>{t.abstract ? "Family (serves the models under it)" : t.models.join(", ")}</dd>
                <dt>Firmware</dt><dd>{t.firmware || "—"}</dd>
                <dt>Features</dt><dd>{t.features.length ? <span className="row">{t.features.map((f) => <span key={f} className="kv-chip">{f}</span>)}</span> : "—"}</dd>
                <dt>Description</dt><dd>{t.description || "—"}</dd>
              </dl>
            </Card>
            <Card title="Inheritance and files">
              <p className="field__label">Inheritance chain</p>
              <ol style={{ margin: "6px 0 16px", paddingLeft: 20 }}>
                {t.chain.map((k, i) => (
                  <li key={k}>
                    {i === 0 ? <strong className="mono">{k}</strong> : <a className="mono" href={`/provisioning/view/?key=${encodeURIComponent(k)}`} onClick={(e) => { e.preventDefault(); router.push(`/provisioning/view/?key=${encodeURIComponent(k)}`); }}>{k}</a>}
                    {i === 0 ? <span className="subtle"> (this template)</span> : null}
                  </li>
                ))}
              </ol>
              <p className="field__label">Generated files</p>
              <ul className="list-plain" style={{ marginTop: 6 }}>
                {t.files.map((f) => (
                  <li key={f.name} style={{ padding: "6px 0", borderTop: 0 }}>
                    <span className="mono">{f.name}</span> <span className="subtle">from {f.source} · {f.format.toUpperCase()}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </TabPanel>
        <TabPanel idBase="tpl" id="variables" active={tab}>
          <Card flush>
            <DataTable columns={varColumns} rows={t.variables} rowKey={(v) => v.name} caption="Template variables" />
          </Card>
        </TabPanel>
        <TabPanel idBase="tpl" id="editor" active={tab}>
          {t.source === "local" ? <TemplateEditor template={t} onSaved={(saved) => detail.setData(saved)} /> : null}
        </TabPanel>
        <TabPanel idBase="tpl" id="preview" active={tab}>
          {t.abstract ? (
            <Callout tone="neutral">Base templates cannot be previewed directly. Open one of the model templates that inherit from it.</Callout>
          ) : (
            <PreviewPanel template={t} />
          )}
        </TabPanel>
      </div>

      <Dialog open={exportText !== null} onClose={() => setExportText(null)} size="lg" title="Export template"
        description="Template exports never include SIP passwords or other secrets. Copy the JSON to save or share it."
        footer={exportText ? <CopyButton text={exportText} label="Copy JSON" /> : undefined}>
        {exportText ? <pre className="code" tabIndex={0}>{exportText}</pre> : <LoadingState />}
      </Dialog>
      <CustomizeDialog open={customizeOpen} template={t} onClose={() => setCustomizeOpen(false)} onCreated={(k) => router.push(`/provisioning/view/?key=${encodeURIComponent(k)}`)} />
      <ConfirmDialog open={deleting} title={`Delete the local template "${t.name}"?`} confirmLabel="Delete template" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Base files used by a template or inherited by another base file cannot be deleted.</p>
      </ConfirmDialog>
    </div>
  );
}

function PreviewPanel({ template }: { template: TemplateDetail }) {
  const editable = template.variables;
  const [model, setModel] = useState(template.models[0] ?? "");
  const [mac, setMac] = useState("0004f2000001");
  const initialValues = (t: TemplateDetail) =>
    Object.fromEntries(t.variables.map((v) => [v.name, SAMPLE[v.name] ?? (t.defaults[v.name] !== undefined ? String(t.defaults[v.name]) : "")]));
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(template));
  const [files, setFiles] = useState<RenderedFile[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useOnChange(template, (t) => setValues(initialValues(t)));

  const render = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErrors([]);
    setFiles(null);
    const body = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
    try {
      const r = await api.post<{ files: RenderedFile[] }>(`/provisioning/templates/${encodeURIComponent(template.key)}/preview`, { model, mac, values: body });
      setFiles(r.files);
    } catch (err) {
      const list = (err as { errors?: { message: string }[] }).errors?.map((x) => x.message) ?? [];
      setErrors(list.length ? list : [errorMessage(err)]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid--2" style={{ alignItems: "start" }}>
      <Card title="Sample values" subtitle="Rendered on the server in the same sandbox used for real phones. Secrets are masked.">
        <form className="stack stack--sm" onSubmit={render}>
          <div className="form-grid">
            <SelectField label="Model" value={model} options={template.models.map((m) => ({ value: m, label: m }))} onChange={(e) => setModel(e.target.value)} />
            <TextField label="MAC address" value={mac} onChange={(e) => setMac(e.target.value)} />
          </div>
          {editable.map((v) => (
            <TextField key={v.name} label={<span className="mono">{v.name}</span>} required={v.required} help={v.description || undefined}
              type={v.sensitive ? "password" : v.type === "integer" ? "number" : "text"} autoComplete="off"
              value={values[v.name] ?? ""} onChange={(e) => setValues((s) => ({ ...s, [v.name]: e.target.value }))} />
          ))}
          <div className="form-actions"><Button variant="primary" type="submit" loading={busy} icon="eye">Render preview</Button></div>
        </form>
      </Card>
      <div className="stack stack--sm">
        {errors.length ? (
          <Callout tone="danger" title="Could not render">
            <ul style={{ margin: 0, paddingLeft: 18 }}>{errors.map((e) => <li key={e}>{e}</li>)}</ul>
          </Callout>
        ) : null}
        {files === null && !errors.length ? <Card><p className="muted">Fill in the values and render a preview to see the generated files.</p></Card> : null}
        {files?.map((f) => (
          <Card key={f.filename} title={<span className="mono">{f.filename}</span>} actions={<CopyButton text={f.content} />}>
            <pre className="code" tabIndex={0}>{f.content}</pre>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><TemplateView /></Suspense>;
}
