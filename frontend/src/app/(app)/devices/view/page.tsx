// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { KeyListEditor } from "@/components/devices/KeyListEditor";
import { PhoneKeysCard } from "@/components/portal/PhoneKeysCard";
import { DEVICE_STATUS } from "@/app/(app)/devices/page";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, EmptyState, ErrorState, LoadingState, PageHeader, SelectField, Switch, TabPanel, Tabs, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { sameBrand } from "@/lib/brands";
import type { Building, Device, DeviceInput, DevicePreview, DeviceProfile, Extension, LineKey, Page, ReprovisionResult, ResolvedVariable } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

interface Draft {
  mac: string; manufacturer: string; model: string; label: string; site_id: string; profile_id: string;
  extension_id: string; lines: string[]; keys: LineKey[] | null; values: Record<string, string>; firmware_image_id: string; enabled: boolean;
  building_id: string; location: string;
}

function draftOf(d: Device): Draft {
  return {
    mac: d.mac_display, manufacturer: d.manufacturer, model: d.model, label: d.label ?? "", site_id: d.site_id ?? "", profile_id: d.profile_id ?? "",
    extension_id: d.extension?.id ?? "", lines: d.lines.map((l) => l.id), keys: d.keys, values: Object.fromEntries(Object.entries(d.values).map(([k, v]) => [k, String(v)])),
    firmware_image_id: d.firmware?.source === "device" ? d.firmware.id : "", enabled: d.is_enabled,
    building_id: d.building_id ?? "", location: d.location ?? "",
  };
}

function bodyOf(d: Draft): DeviceInput {
  return {
    mac_address: d.mac.trim(), manufacturer: d.manufacturer.trim(), model: d.model.trim(), label: d.label.trim() || null, site_id: d.site_id || null,
    profile_id: d.profile_id || null, primary_extension_id: d.extension_id || null, lines: d.lines, keys: d.keys,
    values: Object.fromEntries(Object.entries(d.values).filter(([, v]) => v.trim() !== "")), firmware_image_id: d.firmware_image_id || null, is_enabled: d.enabled,
    building_id: d.building_id || null, location: d.location.trim() || null,
  };
}

function DeviceView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const device = useApiData<Device>(id ? `/devices/${encodeURIComponent(id)}` : null);
  const editable = can("devices.write");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [tab, setTab] = useState("settings");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [preview, setPreview] = useState<DevicePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [notifyBusy, setNotifyBusy] = useState<string | null>(null);
  const [bootstrapBusy, setBootstrapBusy] = useState(false);
  const orgId = device.data?.organization_id ?? "";
  const profiles = useApiData<Page<DeviceProfile>>(orgId ? "/device-profiles" : null, { organization_id: orgId, limit: 200 });
  const extensions = useApiData<Page<Extension>>(orgId ? "/extensions" : null, { organization_id: orgId, limit: 500 });
  const buildings = useApiData<Building[]>(orgId ? "/buildings" : null, { organization_id: orgId });
  const selectedProfile = (profiles.data?.items ?? []).find((p) => p.id === draft?.profile_id);
  const options = useProfileOptions(orgId, selectedProfile?.template_key);

  useOnChange(device.data, (d) => { if (d) setDraft(draftOf(d)); });

  if (!id) return <ErrorState title="No device selected" error={{ message: "Open a device from the list." }} />;
  if (device.error) return <ErrorState title="Could not load device" error={device.error} onRetry={device.reload} />;
  if (!device.data || !draft) return <LoadingState />;
  const d = device.data;
  const dirty = JSON.stringify(bodyOf(draft)) !== JSON.stringify(bodyOf(draftOf(d)));
  const set = (patch: Partial<Draft>) => setDraft((s) => (s ? { ...s, ...patch } : s));
  const extOptions = (extensions.data?.items ?? []).map((x) => ({ value: x.id, label: `${x.number} — ${x.display_name}` }));
  const variables = (options.template?.variables ?? []).filter((v) => !["sip_password", "sip_username", "extension_number"].includes(v.name));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      device.setData(await api.patch<Device>(`/devices/${d.id}`, bodyOf(draft)));
      setPreview(null);
      toast.success("Device saved", "The phone picks up the change at its next provisioning check, or use Reprovision.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/devices/${d.id}`);
      toast.success(`Device ${d.mac_display} deleted`);
      router.push("/devices/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };
  const loadPreview = async () => {
    setPreviewBusy(true);
    try {
      setPreview(await api.get<DevicePreview>(`/devices/${d.id}/preview`));
    } catch (err) {
      setPreview({ template_key: null, files: [], error: errorMessage(err), error_code: null });
    } finally {
      setPreviewBusy(false);
    }
  };
  const allowBootstrap = async () => {
    setBootstrapBusy(true);
    try {
      device.setData(await api.post<Device>(`/devices/${d.id}/allow-bootstrap`));
      toast.success("Bootstrap allowed", "The phone can fetch the Veyra certificate over plain HTTP again.");
    } catch (err) {
      toast.error("Not changed", errorMessage(err));
    } finally {
      setBootstrapBusy(false);
    }
  };
  const notify = async (action: "check_config" | "reboot") => {
    setNotifyBusy(action);
    try {
      const r = await api.post<ReprovisionResult>(`/devices/${d.id}/reprovision`, { action });
      if (r.sent) toast.success(r.message, `NOTIFY sent to ${r.endpoint}.`);
      else toast.error("Not sent", r.message);
    } catch (err) {
      toast.error("Not sent", errorMessage(err));
    } finally {
      setNotifyBusy(null);
    }
  };

  return (
    <div className="stack">
      <PageHeader back={{ href: "/devices/", label: "Devices" }} title={d.label ?? d.mac_display}
        description={<span className="row"><span className="mono">{d.mac_display}</span><span>{d.manufacturer} {d.model}</span><Badge tone={DEVICE_STATUS[d.status].tone}>{DEVICE_STATUS[d.status].label}</Badge>{!d.is_enabled ? <Badge tone="neutral">Disabled</Badge> : null}</span>}
        actions={editable ? (
          <>
            <Button icon="refresh" loading={notifyBusy === "check_config"} onClick={() => notify("check_config")} disabled={!d.extension}>Reprovision</Button>
            <Button icon="power" loading={notifyBusy === "reboot"} onClick={() => notify("reboot")} disabled={!d.extension}>Reboot</Button>
            <Button variant="ghost" icon="trash" onClick={() => setDeleting(true)}>Delete</Button>
          </>
        ) : null} />
      {d.problems.length ? <Callout tone="warn" title="Needs attention"><ul style={{ margin: 0, paddingLeft: 18 }}>{d.problems.map((p) => <li key={p}>{p}</li>)}</ul></Callout> : null}
      <Tabs idBase="dev" active={tab} onChange={setTab} tabs={[{ id: "settings", label: "Settings" }, { id: "keys", label: "Line keys" }, { id: "preview", label: "Configuration" }, { id: "status", label: "Status" }]} />
      <TabPanel idBase="dev" id="settings" active={tab}>
        <Card title="Device" subtitle={editable ? undefined : "You can view but not change this device."}>
          <form className="stack stack--sm" onSubmit={save}>
            <div className="form-grid">
              <TextField label="MAC address" required disabled={!editable} value={draft.mac} error={errors.fields.mac_address} onChange={(e) => set({ mac: e.target.value })} />
              <TextField label="Label" disabled={!editable} value={draft.label} error={errors.fields.label} placeholder="e.g. Room 112" onChange={(e) => set({ label: e.target.value })} />
            </div>
            <div className="form-grid">
              <SelectField label="Manufacturer" required disabled={!editable} value={options.manufacturers.some((m) => m.name === draft.manufacturer) ? draft.manufacturer : ""} error={errors.fields.manufacturer} placeholder={draft.manufacturer || "Choose"}
                options={options.manufacturers.map((m) => ({ value: m.name, label: m.name }))} onChange={(e) => set({ manufacturer: e.target.value, model: "", ...(sameBrand(selectedProfile?.manufacturer, e.target.value) ? {} : { profile_id: "", values: {} }) })} />
              {(options.manufacturers.find((m) => m.name === draft.manufacturer)?.models ?? []).length ? (
                <SelectField label="Model" required disabled={!editable} value={draft.model} error={errors.fields.model} placeholder="Choose a model"
                  options={(options.manufacturers.find((m) => m.name === draft.manufacturer)?.models ?? []).map((m) => ({ value: m, label: m }))} onChange={(e) => set({ model: e.target.value })} />
              ) : (
                <TextField label="Model" required disabled={!editable} value={draft.model} error={errors.fields.model} onChange={(e) => set({ model: e.target.value })} />
              )}
            </div>
            <div className="form-grid">
              <SelectField label="Device profile" disabled={!editable} value={draft.profile_id} error={errors.fields.profile_id} placeholder="No profile (nothing is served)"
                help={`Profiles for ${draft.manufacturer} phones.`}
                options={(profiles.data?.items ?? []).filter((p) => p.id === draft.profile_id || sameBrand(p.manufacturer, draft.manufacturer)).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => set({ profile_id: e.target.value, values: {} })} />
              <SelectField label="Site" disabled={!editable} value={draft.site_id} error={errors.fields.site_id} placeholder="No site" options={options.sites.map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => set({ site_id: e.target.value })} />
              <SelectField label="Building" disabled={!editable} value={draft.building_id} error={errors.fields.building_id} placeholder="No building"
                options={[{ value: "", label: "No building" }, ...(buildings.data ?? []).filter((b) => !draft.site_id || b.site_id === draft.site_id).map((b) => ({ value: b.id, label: b.name }))]} onChange={(e) => set({ building_id: e.target.value })} />
              <TextField label="Location (dispatchable)" disabled={!editable} value={draft.location} error={errors.fields.location} placeholder="Room 101, first floor"
                help="Floor and room for emergency calls from this phone; wins over the extension's location." onChange={(e) => set({ location: e.target.value })} />
            </div>
            <SelectField label="Extension (line 1)" disabled={!editable} value={draft.extension_id} error={errors.fields.primary_extension_id} placeholder="No extension" options={extOptions} onChange={(e) => set({ extension_id: e.target.value })} />
            <div className="stack stack--sm">
              <span className="field__label">Extra lines</span>
              {draft.lines.map((lineId, i) => (
                <div key={i} className="row" style={{ gap: 8, alignItems: "flex-end" }}>
                  <span className="mono subtle" style={{ width: 24, paddingBottom: 10 }}>{i + 2}</span>
                  <SelectField label={<span className="sr-only">Line {i + 2}</span>} disabled={!editable} value={lineId} options={extOptions} onChange={(e) => set({ lines: draft.lines.map((l, j) => (j === i ? e.target.value : l)) })} />
                  {editable ? <Button size="sm" variant="ghost" icon="trash" aria-label={`Remove line ${i + 2}`} onClick={() => set({ lines: draft.lines.filter((_, j) => j !== i) })} /> : null}
                </div>
              ))}
              {errors.fields.lines ? <p className="field__error">{errors.fields.lines}</p> : null}
              {editable && draft.lines.length < 7 ? <div><Button size="sm" icon="plus" onClick={() => set({ lines: [...draft.lines, extOptions[0]?.value ?? ""] })} disabled={!extOptions.length}>Add line</Button></div> : null}
            </div>
            <SelectField label="Firmware override" disabled={!editable} value={draft.firmware_image_id} error={errors.fields.firmware_image_id} placeholder={d.firmware?.source === "profile" ? `From the profile: ${d.firmware.version}` : "From the profile"}
              options={options.firmware.filter((f) => f.manufacturer.toLowerCase() === draft.manufacturer.toLowerCase()).map((f) => ({ value: f.id, label: `${f.manufacturer} ${f.version}` }))} onChange={(e) => set({ firmware_image_id: e.target.value })} />
            {variables.length ? (
              <>
                <h3 className="field__label" style={{ marginTop: 8 }}>Setting overrides <span className="subtle">(blank = the profile&apos;s value)</span></h3>
                {errors.fields.values ? <p className="field__error">{errors.fields.values}</p> : null}
                <div className="form-grid">
                  {variables.map((v) => v.type === "boolean" ? (
                    <SelectField key={v.name} label={v.description || v.name} disabled={!editable} value={draft.values[v.name] ?? ""}
                      options={[
                        { value: "", label: `As the profile (${yesNo(selectedProfile?.values[v.name] ?? options.template?.defaults[v.name])})` },
                        { value: "true", label: "Yes" },
                        { value: "false", label: "No" },
                      ]}
                      help={<span className="mono">{v.name}</span>} onChange={(e) => set({ values: { ...draft.values, [v.name]: e.target.value } })} />
                  ) : (
                    <TextField key={v.name} label={v.description || v.name} disabled={!editable} type={v.sensitive ? "password" : v.type === "integer" ? "number" : "text"} autoComplete="off"
                      value={draft.values[v.name] ?? ""} placeholder={selectedProfile?.values[v.name] !== undefined ? `Profile: ${String(selectedProfile.values[v.name])}` : options.template?.defaults[v.name] !== undefined ? `Default: ${String(options.template.defaults[v.name])}` : ""}
                      help={<span className="mono">{v.name}</span>} onChange={(e) => set({ values: { ...draft.values, [v.name]: e.target.value } })} />
                  ))}
                </div>
              </>
            ) : null}
            <Switch label="Enabled" description="Disabled phones are refused configuration (403) until re-enabled." checked={draft.enabled} disabled={!editable} onChange={(e) => set({ enabled: e.target.checked })} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
      </TabPanel>
      <TabPanel idBase="dev" id="keys" active={tab}>
        <Card title="Line keys" subtitle="By default the phone uses its profile's keys. Override them here for this phone only.">
          <div className="stack stack--sm">
            <Checkbox label="Override the profile's keys for this phone" disabled={!editable} checked={draft.keys !== null} onChange={(e) => set({ keys: e.target.checked ? (selectedProfile?.keys ?? []) : null })} />
            {draft.keys !== null ? <KeyListEditor keys={draft.keys} onChange={(keys) => set({ keys })} zones={options.zones} disabled={!editable} error={errors.fields.keys} /> : (
              selectedProfile ? <KeyListEditor keys={selectedProfile.keys} onChange={() => undefined} zones={options.zones} disabled /> : <p className="muted">No profile selected.</p>
            )}
            {editable ? <div className="form-actions"><Button variant="primary" loading={busy} disabled={!dirty} onClick={(e) => save(e as unknown as FormEvent)}>Save changes</Button></div> : null}
          </div>
        </Card>
        {d.extension && editable ? <div style={{ marginTop: 16 }}><PhoneKeysCard key={d.updated_at} deviceId={d.id} /></div> : null}
      </TabPanel>
      <TabPanel idBase="dev" id="preview" active={tab}>
        <Card title="Configuration files" subtitle="What the phone downloads, rendered now with secrets masked." actions={<Button icon="eye" loading={previewBusy} onClick={loadPreview}>{preview ? "Refresh" : "Render"}</Button>}>
          {preview?.error ? <Callout tone="danger">{preview.error}</Callout> : null}
          {preview?.warnings?.length ? <Callout tone="warn" title="Missing variables">{preview.warnings.join("; ")}. Define them under Provisioning → Variables; until then those settings and keys are left out.</Callout> : null}
          {preview?.template_key ? <p className="muted">Template <span className="mono">{preview.template_key}</span></p> : null}
          {preview?.files.map((f) => (
            <div key={f.filename} className="stack stack--sm" style={{ marginTop: 12 }}>
              <div className="row" style={{ justifyContent: "space-between" }}><span className="mono">{f.filename}</span><CopyButton text={f.content} /></div>
              <pre className="code" tabIndex={0}>{f.content}</pre>
            </div>
          ))}
          {!preview && !previewBusy ? <p className="muted">Render to see the files.</p> : null}
        </Card>
        <DeviceVariables deviceId={d.id} />
      </TabPanel>
      <TabPanel idBase="dev" id="status" active={tab}>
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <Card title="Provisioning">
            <dl className="dl">
              <dt>Status</dt><dd><Badge tone={DEVICE_STATUS[d.status].tone}>{DEVICE_STATUS[d.status].label}</Badge></dd>
              <dt>Last request</dt><dd>{d.last_seen_at ? <>{formatDateTime(d.last_seen_at)} ({formatRelative(d.last_seen_at)}) · {d.last_result}</> : "Never"}</dd>
              <dt>From</dt><dd className="mono">{d.last_seen_ip ?? "—"}</dd>
              <dt>Phone reports</dt><dd>{d.last_user_agent ?? "—"}</dd>
              <dt>Template</dt><dd className="mono">{d.template_key ?? "—"}</dd>
              <dt>Credential user</dt><dd><span className="mono">{d.credential_user}</span> <span className="subtle">(set on the phone by its first configuration)</span></dd>
              <dt>Trust</dt><dd>{d.https_seen_at
                ? <><Badge tone="ok">Trusted, HTTPS</Badge> <span className="subtle">since {formatDateTime(d.https_seen_at)}</span></>
                : <span className="subtle">Not provisioned over HTTPS yet{d.allow_bootstrap ? "; the plain-HTTP bootstrap is allowed" : ""}</span>}</dd>
            </dl>
            {editable && !d.allow_bootstrap ? (
              <div className="stack stack--sm" style={{ marginTop: 12 }}>
                <p className="subtle">After a factory reset the phone no longer trusts Veyra and needs the plain-HTTP bootstrap once more.</p>
                <div><Button icon="refresh" loading={bootstrapBusy} onClick={allowBootstrap}>Allow bootstrap again</Button></div>
              </div>
            ) : null}
          </Card>
          <Card title="Firmware">
            <dl className="dl">
              <dt>Assigned</dt><dd>{d.firmware ? `${d.firmware.version} (${d.firmware.filename}, from the ${d.firmware.source})` : "Not managed"}</dd>
              <dt>Running</dt><dd>{d.firmware_reported ?? "Unknown until the phone checks in"}</dd>
              <dt>State</dt><dd>{d.firmware_state === "up_to_date" ? <Badge tone="ok">Up to date</Badge> : d.firmware_state === "pending" ? <Badge tone="warn">Update pending</Badge> : d.firmware_state === "unknown" ? <Badge tone="neutral">Unknown</Badge> : "—"}</dd>
              <dt>Registered</dt><dd>{formatDateTime(d.created_at)}</dd>
            </dl>
          </Card>
        </div>
      </TabPanel>
      <ConfirmDialog open={deleting} title={`Delete the device ${d.mac_display}?`} confirmLabel="Delete device" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>The phone keeps its last configuration until it is reset; its provisioning credential stops working.</p>
      </ConfirmDialog>
    </div>
  );
}

/** A yes/no value as the profile or template has it. */
function yesNo(value: unknown): string {
  const v = String(value ?? "").toLowerCase();
  return v === "true" ? "yes" : v === "false" ? "no" : "not set";
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><DeviceView /></Suspense>;
}

/** The provisioning variables this phone resolves, and where each comes from. */
function DeviceVariables({ deviceId }: { deviceId: string }) {
  const vars = useApiData<ResolvedVariable[]>(`/devices/${deviceId}/variables`);
  const SCOPE: Record<string, string> = { installation: "Installation", organization: "Organization", site: "Site", profile: "Profile" };
  return (
    <Card title="Variables" subtitle="Values this phone takes from Provisioning → Variables; the nearest scope wins." flush>
      <DataTable columns={[
        { key: "name", header: "Variable", render: (v: ResolvedVariable) => <span className="mono">{v.name}</span> },
        { key: "value", header: "Value", render: (v: ResolvedVariable) => <span className="mono">{v.value}</span> },
        { key: "scope", header: "From", render: (v: ResolvedVariable) => <Badge tone="neutral">{SCOPE[v.scope] ?? v.scope}</Badge> },
      ]} rows={vars.data} rowKey={(v) => v.name} loading={vars.loading} error={vars.error} onRetry={vars.reload}
        caption="Resolved variables" empty={<EmptyState compact icon="settings" title="No variables reach this phone" />} />
    </Card>
  );
}
