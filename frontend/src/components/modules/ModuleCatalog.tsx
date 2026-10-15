// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, Dialog, EmptyState, IconButton, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { CatalogModuleItem, CatalogSourceItem } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";

export const VEYRA_CATALOG_URL = "https://raw.githubusercontent.com/manderson20/veyra-modules/main/catalog/index.json";

/** Modules offered by the catalog sources (docs/MODULE_CATALOG.md §3). */
export function ModuleCatalog({ manage, onChanged }: { manage: boolean; onChanged: () => void }) {
  const toast = useToast();
  const list = useApiData<CatalogModuleItem[]>("/modules/catalog");
  const [target, setTarget] = useState<CatalogModuleItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const install = async () => {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ result: string; version: string; restart_required: boolean }>("/modules/catalog/install", { module_id: target.id, enable: true });
      toast.success(`${target.name} ${r.version}: ${r.result}`, r.restart_required ? "Restart Veyra's services to load the new code." : undefined);
      setTarget(null);
      list.reload();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const columns: Column<CatalogModuleItem>[] = [
    { key: "name", header: "Module", render: (m) => <><span className="table__primary">{m.name}</span><span className="table__secondary" style={{ display: "block" }}>{m.summary ?? m.id}</span></> },
    { key: "pub", header: "Publisher", render: (m) => m.publisher ?? "—" },
    { key: "latest", header: "Latest", render: (m) => (m.latest_compatible ? <span className="mono">{m.latest_compatible}</span> : <Badge tone="warn">{m.versions[0]?.problem ?? "not compatible"}</Badge>) },
    { key: "inst", header: "Installed", render: (m) => (m.installed_version ? <><span className="mono">{m.installed_version}</span>{m.update_available ? <> <Badge tone="info">Update</Badge></> : null}</> : <span className="subtle">—</span>) },
    {
      key: "act", header: <span className="sr-only">Actions</span>, render: (m) => manage && m.latest_compatible && (!m.installed_version || m.update_available) ? (
        <Button size="sm" variant={m.update_available ? "primary" : "secondary"} icon={m.update_available ? "update" : "download"} onClick={() => { setError(null); setTarget(m); }}>
          {m.update_available ? `Update to ${m.latest_compatible}` : "Install"}
        </Button>
      ) : null,
    },
  ];
  const latest = target?.versions.find((v) => v.version === target.latest_compatible);
  return (
    <Card flush>
      <DataTable columns={columns} rows={list.data} rowKey={(m) => m.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Module catalog"
        empty={<EmptyState icon="modules" title="The catalog is empty" compact>Add a catalog source (the Sources tab), or wait for the daily refresh.</EmptyState>} />
      <ConfirmDialog open={target !== null} title={target ? `${target.update_available ? "Update" : "Install"} ${target.name}?` : ""}
        confirmLabel={target?.update_available ? "Update" : "Install and enable"} busy={busy} error={error} onConfirm={install} onCancel={() => setTarget(null)}>
        {latest ? (
          <dl className="dl">
            <dt>Version</dt><dd className="mono">{latest.version}{target?.installed_version ? ` (installed ${target.installed_version})` : ""}</dd>
            <dt>From</dt><dd>{latest.source}{latest.released ? ` · released ${latest.released}` : ""} · {formatBytes(latest.size)}</dd>
            <dt>Notes</dt><dd>{latest.notes ?? "—"}</dd>
          </dl>
        ) : null}
        <p className="subtle">The package is checked against the catalog&apos;s checksum and its publisher&apos;s signature before anything runs. {target?.update_available ? "Its database changes run now; the new code runs after Veyra's services restart." : ""}</p>
      </ConfirmDialog>
    </Card>
  );
}

/** Catalog sources: signed index addresses (docs/MODULE_CATALOG.md §3). */
export function CatalogSources({ manage, onChanged }: { manage: boolean; onChanged: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const list = useApiData<CatalogSourceItem[]>("/modules/catalog-sources");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("Veyra modules");
  const [url, setUrl] = useState(VEYRA_CATALOG_URL);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<CatalogSourceItem | null>(null);
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const s = await api.post<CatalogSourceItem>("/modules/catalog-sources", { name: name.trim(), url: url.trim() });
      if (s.last_status === "ok") toast.success("Catalog added", `${s.modules} module(s), signed by ${s.signed_by}.`);
      else toast.error("Catalog added but not usable yet", s.last_error ?? undefined);
      setAdding(false);
      list.reload();
      onChanged();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const refresh = async () => {
    try {
      await api.post("/modules/catalog/refresh");
      list.reload();
      onChanged();
    } catch (err) {
      toast.error("Not refreshed", errorMessage(err));
    }
  };
  const remove = async () => {
    if (!removing) return;
    await api.del(`/modules/catalog-sources/${removing.id}`).catch((err) => toast.error("Not removed", errorMessage(err)));
    setRemoving(null);
    list.reload();
    onChanged();
  };
  const columns: Column<CatalogSourceItem>[] = [
    { key: "name", header: "Source", render: (s) => <><span className="table__primary">{s.name}</span><span className="table__secondary mono" style={{ display: "block", wordBreak: "break-all" }}>{s.url}</span></> },
    { key: "state", header: "State", render: (s) => (s.last_status === "ok" ? <Badge tone="ok">{s.modules} module(s), signed by {s.signed_by}</Badge> : s.last_status === "failed" ? <Badge tone="danger">{s.last_error ?? "failed"}</Badge> : <Badge tone="neutral">Not fetched</Badge>) },
    { key: "when", header: "Checked", render: (s) => (s.last_fetched_at ? <span className="nowrap">{formatDateTime(s.last_fetched_at)}</span> : "—") },
    { key: "act", header: <span className="sr-only">Actions</span>, render: (s) => (manage ? <IconButton size="sm" icon="trash" label={`Remove ${s.name}`} onClick={() => setRemoving(s)} /> : null) },
  ];
  return (
    <Card title="Catalog sources" subtitle="Signed module indexes, checked once a day. A catalog is used only when it is signed by a key in /etc/veyra/trust/catalog/ on this server."
      actions={manage ? <><Button icon="refresh" onClick={refresh}>Check now</Button><Button icon="plus" onClick={() => { errors.clear(); setAdding(true); }}>Add source</Button></> : null} flush>
      <DataTable columns={columns} rows={list.data} rowKey={(s) => s.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Catalog sources"
        empty={<EmptyState icon="modules" title="No catalog sources" compact>Add the Veyra catalog, or your own.</EmptyState>} />
      <Dialog open={adding} onClose={() => setAdding(false)} busy={busy} title="Add a catalog source"
        footer={<><Button onClick={() => setAdding(false)} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="catalog-source-form" loading={busy}>Add</Button></>}>
        <form id="catalog-source-form" className="stack stack--sm" onSubmit={add}>
          <TextField label="Name" required value={name} error={errors.fields.name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Index address" required value={url} error={errors.fields.url} help="The URL of index.json (HTTPS). index.json.sig must sit next to it." onChange={(e) => setUrl(e.target.value)} />
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        </form>
      </Dialog>
      <ConfirmDialog open={removing !== null} title={`Remove ${removing?.name ?? ""}?`} confirmLabel="Remove" tone="danger" onConfirm={remove} onCancel={() => setRemoving(null)}>
        <p>Modules installed from it stay installed; they just no longer get updates from this source.</p>
      </ConfirmDialog>
    </Card>
  );
}

/** Upload a .vmod package (docs/MODULE_CATALOG.md §3). */
export function ModuleUpload({ onChanged }: { onChanged: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [enable, setEnable] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await api.upload<{ module_id: string; version: string; result: string; restart_required: boolean }>(`/modules/upload?enable=${enable}`, form);
      toast.success(`${r.module_id} ${r.version}: ${r.result}`, r.restart_required ? "Restart Veyra's services to load the new code." : undefined);
      setFile(null);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Upload a module" subtitle="A .vmod package signed by a publisher key this server trusts (/etc/veyra/trust/). Unsigned packages are refused in production.">
      <form className="stack stack--sm" onSubmit={submit}>
        <input type="file" accept=".vmod" aria-label="Module package" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <label className="check"><input type="checkbox" checked={enable} onChange={(e) => setEnable(e.target.checked)} /><span className="check__text"><span>Enable it after installing</span></span></label>
        {error ? <Callout tone="danger">{error}</Callout> : null}
        <div><Button variant="primary" type="submit" icon="upload" loading={busy} disabled={!file}>Upload and install</Button></div>
      </form>
    </Card>
  );
}
