// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { KeyListEditor } from "@/components/devices/KeyListEditor";
import { EMPTY_PROFILE, ProfileFields, profileBody, profileDraft, type ProfileDraft } from "@/components/devices/ProfileFields";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, Dialog, EmptyState, ErrorState, LoadingState, PageHeader, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { DeviceProfile, LineKey, PagingZone } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

/** A model's own line keys, or the template's. Changes join the template's draft. */
function ModelKeysDialog({ model, draft, zones, disabled, onChange, onClose }: { model: string | null; draft: ProfileDraft; zones: PagingZone[]; disabled: boolean; onChange: (model: string, keys: LineKey[] | null) => void; onClose: () => void }) {
  const own = model ? draft.model_keys[model] : undefined;
  return (
    <Dialog open={!!model} onClose={onClose} size="lg" title={`Line keys of the ${model ?? ""}`} description="These apply to this model when you save the template."
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      {model ? (
        <div className="stack stack--sm">
          <Checkbox label="Give this model its own keys" disabled={disabled} checked={own !== undefined} onChange={(e) => onChange(model, e.target.checked ? draft.keys : null)} />
          {own !== undefined
            ? <KeyListEditor keys={own} onChange={(keys) => onChange(model, keys)} zones={zones} disabled={disabled} />
            : <KeyListEditor keys={draft.keys} onChange={() => undefined} zones={zones} disabled />}
        </div>
      ) : null}
    </Dialog>
  );
}

function TemplateView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can, refresh } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const profile = useApiData<DeviceProfile>(id ? `/device-profiles/${encodeURIComponent(id)}` : null);
  const editable = can("devices.write");
  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_PROFILE);
  const [busy, setBusy] = useState<"save" | "update" | null>(null);
  const [openModel, setOpenModel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const options = useProfileOptions(profile.data?.organization_id ?? "", draft.template_key || undefined);

  useOnChange(profile.data, (p) => { if (p) setDraft(profileDraft(p)); });

  if (!id) return <ErrorState title="No template selected" error={{ message: "Open a template from its brand." }} />;
  if (profile.error) return <ErrorState title="Could not load template" error={profile.error} onRetry={profile.reload} />;
  if (!profile.data) return <LoadingState />;
  const p = profile.data;
  const dirty = JSON.stringify(profileBody(draft)) !== JSON.stringify(profileBody(profileDraft(p)));
  const brandHref = p.manufacturer ? `/provisioning/brands/view/?name=${encodeURIComponent(p.manufacturer)}` : "/provisioning/brands/";

  const save = async (updatePhones: boolean) => {
    setBusy(updatePhones ? "update" : "save");
    errors.clear();
    try {
      if (dirty) profile.setData(await api.patch<DeviceProfile>(`/device-profiles/${p.id}`, profileBody(draft)));
      if (updatePhones) {
        const r = await api.post<{ phones: number; asked: number }>(`/device-profiles/${p.id}/update-phones`, {});
        toast.success("Phones asked to update", `${r.asked} of ${r.phones} accepted the request. A phone that did not picks up the change at its next check.`);
      } else {
        toast.success("Template saved", "Phones pick up the change at their next check. Use Save and Update Phones to ask them now.");
      }
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void save(false); };
  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/device-profiles/${p.id}`);
      toast.success(`Template "${p.name}" deleted`);
      void refresh();
      router.push(brandHref);
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };
  const setModelKeys = (model: string, keys: LineKey[] | null) => setDraft((d) => {
    const next = { ...d.model_keys };
    if (keys) next[model] = keys;
    else delete next[model];
    return { ...d, model_keys: next };
  });
  interface ModelRow { model: string; base: string }
  const modelRows: ModelRow[] = Object.entries(p.models).map(([model, base]) => ({ model, base }));
  const modelColumns: Column<ModelRow>[] = [
    { key: "model", header: "Model", render: (m) => <span className="table__primary">{m.model}</span> },
    { key: "base", header: "Base file", render: (m) => <span className="mono">{m.base}</span> },
    { key: "keys", header: "Line keys", render: (m) => { const own = draft.model_keys[m.model]; return own ? <Badge tone="info">Own keys ({own.length})</Badge> : <span className="subtle">As the template ({draft.keys.length})</span>; } },
  ];

  return (
    <div className="stack">
      <PageHeader back={{ href: brandHref, label: p.manufacturer ?? "Brands" }} title={p.name}
        description={<span className="row"><span>{p.organization_name}</span>{p.site_name ? <span className="subtle">· {p.site_name}</span> : null}{p.is_default ? <Badge tone="info">Default</Badge> : null}{p.problems.length ? <Badge tone="warn" icon="alert">{p.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge>}</span>}
        actions={editable ? <Button variant="ghost" icon="trash" onClick={() => setDeleting(true)} disabled={p.devices > 0} title={p.devices > 0 ? "Move its phones to another template first" : undefined}>Delete</Button> : null} />
      <Card title="Template" subtitle={editable ? undefined : "You can view but not change this template."}>
        <form className="stack stack--sm" onSubmit={submit}>
          <ProfileFields brand={p.manufacturer} draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} templates={options.templates} template={options.template}
            zones={options.zones} sites={options.sites} firmware={options.firmware} errors={errors.fields} disabled={!editable} />
          {errors.fields.model_keys ? <p className="field__error">{errors.fields.model_keys}</p> : null}
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
          {editable ? (
            <div className="form-actions">
              <Button type="button" loading={busy === "update"} disabled={!!busy || p.devices === 0} onClick={() => void save(true)}>Save and Update Phones</Button>
              <Button variant="primary" type="submit" loading={busy === "save"} disabled={!dirty || !!busy}>Save</Button>
            </div>
          ) : null}
        </form>
      </Card>
      <Card title="Used By" subtitle={`${p.devices} phone${p.devices === 1 ? "" : "s"}`}>
        {p.devices ? (
          <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>
            {p.used_by.map((u) => <Link key={u.device_id} className="kv-chip" href={`/devices/view/?id=${u.device_id}`}>{u.label}</Link>)}
            {p.devices > p.used_by.length ? <Link className="kv-chip" href={`/devices/?profile=${p.id}`}>{p.devices - p.used_by.length} more</Link> : null}
          </span>
        ) : <p className="muted">Not in use.</p>}
        <dl className="dl" style={{ marginTop: 12 }}>
          <dt>Firmware</dt><dd>{p.firmware ? `${p.firmware.manufacturer ?? ""} ${p.firmware.version} (${p.firmware.filename})` : "Phones keep their current firmware"}</dd>
          <dt>Created</dt><dd>{formatDateTime(p.created_at)}</dd>
          <dt>Updated</dt><dd>{formatDateTime(p.updated_at)}</dd>
        </dl>
      </Card>
      <Card title="Available Phones" subtitle="Open a model to see its line keys or give it its own." flush>
        <DataTable columns={modelColumns} rows={modelRows} rowKey={(m) => m.model} caption="Available phones" onRowClick={(m) => setOpenModel(m.model)} rowLabel={(m) => `Line keys of the ${m.model}`}
          empty={<EmptyState compact icon="device" title="No model's base file under this family yet" />} />
      </Card>
      <div><Link href={`/provisioning/base-file-edit/?template=${p.id}`}>Base File Edit{p.base_edits.length ? ` (${p.base_edits.length} change${p.base_edits.length === 1 ? "" : "s"})` : ""}</Link></div>
      <ModelKeysDialog model={openModel} draft={draft} zones={options.zones} disabled={!editable} onChange={setModelKeys} onClose={() => setOpenModel(null)} />
      <ConfirmDialog open={deleting} title={`Delete the template "${p.name}"?`} confirmLabel="Delete template" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Templates with phones cannot be deleted.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><TemplateView /></Suspense>;
}
