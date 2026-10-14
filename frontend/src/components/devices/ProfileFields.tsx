// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { KeyListEditor } from "@/components/devices/KeyListEditor";
import { Checkbox, SelectField, TextArea, TextField } from "@/components/ui";
import type { DeviceProfile, DeviceProfileInput, FirmwareImage, LineKey, PagingMembershipInput, PagingRole, PagingZone, Site, TemplateDetail, TemplateSummary } from "@/lib/types";

export interface ProfileDraft {
  name: string;
  description: string;
  site_id: string;
  template_key: string;
  values: Record<string, string>;
  keys: LineKey[];
  paging: Record<string, { subscribed: boolean; transmit: boolean; role: PagingRole }>;
  firmware_image_id: string;
}

export const EMPTY_PROFILE: ProfileDraft = { name: "", description: "", site_id: "", template_key: "", values: {}, keys: [], paging: {}, firmware_image_id: "" };

export function profileDraft(p: DeviceProfile): ProfileDraft {
  return {
    name: p.name,
    description: p.description ?? "",
    site_id: p.site_id ?? "",
    template_key: p.template_key,
    values: Object.fromEntries(Object.entries(p.values).map(([k, v]) => [k, String(v)])),
    keys: p.keys,
    paging: Object.fromEntries(p.paging.map((m) => [m.zone_id, { subscribed: m.subscribed, transmit: m.transmit, role: m.role }])),
    firmware_image_id: p.firmware?.id ?? "",
  };
}

export function profileBody(d: ProfileDraft): DeviceProfileInput {
  const paging: PagingMembershipInput[] = Object.entries(d.paging).map(([zone_id, m]) => ({ zone_id, ...m }));
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    site_id: d.site_id || null,
    template_key: d.template_key,
    values: Object.fromEntries(Object.entries(d.values).filter(([, v]) => v.trim() !== "")),
    keys: d.keys,
    paging,
    firmware_image_id: d.firmware_image_id || null,
  };
}

const ROLE_LABELS: Record<PagingRole, string> = { none: "—", default: "Default group", priority: "Priority group", emergency: "Emergency group" };

/** The shared form of the profile dialog and page. */
export function ProfileFields({ draft, onChange, templates, template, zones, sites, firmware, errors, disabled }: {
  draft: ProfileDraft;
  onChange: (patch: Partial<ProfileDraft>) => void;
  templates: TemplateSummary[];
  template: TemplateDetail | null;
  zones: PagingZone[];
  sites: Site[];
  firmware: FirmwareImage[];
  errors: Record<string, string>;
  disabled?: boolean;
}) {
  const families = templates.filter((t) => t.abstract);
  const models = templates.filter((t) => !t.abstract);
  const manufacturer = template?.manufacturer;
  const variables = (template?.variables ?? []).filter((v) => !["sip_password", "sip_username", "extension_number"].includes(v.name));
  const setPaging = (zoneId: string, patch: Partial<{ subscribed: boolean; transmit: boolean; role: PagingRole }> | null) => {
    const next = { ...draft.paging };
    if (patch === null) delete next[zoneId];
    else next[zoneId] = { subscribed: true, transmit: true, role: "none", ...next[zoneId], ...patch };
    onChange({ paging: next });
  };
  return (
    <div className="stack stack--sm">
      <div className="form-grid">
        <TextField label="Name" required disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. VVX, Building A" onChange={(e) => onChange({ name: e.target.value })} />
        <SelectField label="Site (optional)" disabled={disabled} value={draft.site_id} error={errors.site_id} placeholder="No site" options={sites.map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => onChange({ site_id: e.target.value })} />
      </div>
      <SelectField label="Template" required disabled={disabled} value={draft.template_key} error={errors.template_key} placeholder="Choose a template family or model"
        help="A family (base template) serves every model under it; a model template serves that model only."
        options={[
          ...families.map((t) => ({ value: t.key, label: `${t.manufacturer} — ${t.name} (family)` })),
          ...models.map((t) => ({ value: t.key, label: `${t.manufacturer} — ${t.name}: ${t.models.join(", ")}` })),
        ]}
        onChange={(e) => onChange({ template_key: e.target.value, values: {} })} />
      {template?.abstract === false ? <p className="muted">Serves {template.models.join(", ")} only.</p> : null}
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} onChange={(e) => onChange({ description: e.target.value })} />
      <SelectField label="Firmware" disabled={disabled} value={draft.firmware_image_id} error={errors.firmware_image_id} placeholder="Keep the phones' current firmware"
        options={firmware.filter((f) => !manufacturer || f.manufacturer.toLowerCase() === manufacturer.toLowerCase()).map((f) => ({ value: f.id, label: `${f.manufacturer} ${f.version} (${f.models.join(", ") || "all models"})` }))}
        onChange={(e) => onChange({ firmware_image_id: e.target.value })} />

      <h3 className="field__label" style={{ marginTop: 8 }}>Settings</h3>
      {errors.values ? <p className="field__error">{errors.values}</p> : null}
      {variables.length === 0 ? <p className="muted">Choose a template to see its settings.</p> : null}
      <div className="form-grid">
        {variables.map((v) => (
          v.type === "boolean" ? (
            <Checkbox key={v.name} label={v.description || v.name} disabled={disabled} checked={(draft.values[v.name] ?? String(template?.defaults[v.name] ?? "")).toLowerCase() === "true"}
              onChange={(e) => onChange({ values: { ...draft.values, [v.name]: e.target.checked ? "true" : "false" } })} />
          ) : (
            <TextField key={v.name} label={v.description || v.name} disabled={disabled} type={v.sensitive ? "password" : v.type === "integer" ? "number" : "text"} autoComplete="off"
              value={draft.values[v.name] ?? ""} placeholder={v.sensitive ? "" : template?.defaults[v.name] !== undefined ? `Default: ${String(template.defaults[v.name])}` : ""}
              help={<span className="mono">{v.name}</span>} onChange={(e) => onChange({ values: { ...draft.values, [v.name]: e.target.value } })} />
          )
        ))}
      </div>

      <h3 className="field__label" style={{ marginTop: 8 }}>Line keys</h3>
      <KeyListEditor keys={draft.keys} onChange={(keys) => onChange({ keys })} zones={zones} disabled={disabled} error={errors.keys} />

      <h3 className="field__label" style={{ marginTop: 8 }}>Paging zones</h3>
      {errors.paging ? <p className="field__error">{errors.paging}</p> : null}
      {zones.length === 0 ? <p className="muted">No paging zones in this organization yet.</p> : null}
      {zones.map((z) => {
        const m = draft.paging[z.id];
        return (
          <div key={z.id} className="row" style={{ gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <Checkbox label={<span>{z.name} <span className="subtle">group {z.poly_group}</span></span>} disabled={disabled} checked={!!m} onChange={(e) => setPaging(z.id, e.target.checked ? {} : null)} />
            {m ? (
              <>
                <Checkbox label="Receive" disabled={disabled} checked={m.subscribed} onChange={(e) => setPaging(z.id, { subscribed: e.target.checked })} />
                <Checkbox label="Send" disabled={disabled} checked={m.transmit} onChange={(e) => setPaging(z.id, { transmit: e.target.checked })} />
                <SelectField label={<span className="sr-only">Role</span>} disabled={disabled} value={m.role} options={(Object.keys(ROLE_LABELS) as PagingRole[]).map((r) => ({ value: r, label: ROLE_LABELS[r] }))} onChange={(e) => setPaging(z.id, { role: e.target.value as PagingRole })} />
              </>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
