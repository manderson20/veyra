// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Button, IconButton, SelectField, Switch, TextField } from "@/components/ui";
import type { TemplateVariable } from "@/lib/types";

export type VarType = TemplateVariable["type"];

/** One of the template's own variables as the form holds it: every value a string. */
export interface VarRow {
  id: string;
  name: string;
  type: VarType;
  description: string;
  default: string;
  required: boolean;
  sensitive: boolean;
  pattern: string;
  max_length: string;
}

const TYPES: { value: VarType; label: string }[] = [
  { value: "string", label: "Text" },
  { value: "integer", label: "Number" },
  { value: "boolean", label: "Yes / no" },
];

let seq = 0;
export function newRow(v?: Partial<TemplateVariable>): VarRow {
  seq += 1;
  return {
    id: `var-${seq}`,
    name: v?.name ?? "",
    type: v?.type ?? "string",
    description: v?.description ?? "",
    default: v?.default === null || v?.default === undefined ? "" : String(v.default),
    required: v?.required ?? false,
    sensitive: v?.sensitive ?? false,
    pattern: v?.pattern ?? "",
    max_length: v?.max_length && v.max_length !== 255 ? String(v.max_length) : "",
  };
}

function typed(type: VarType, text: string): string | number | boolean | null {
  const t = text.trim();
  if (t === "") return null;
  if (type === "integer") return /^-?\d+$/.test(t) ? Number(t) : t;
  if (type === "boolean") return t === "true";
  return text;
}

/** The manifest form of a row (the server validates names and patterns). */
export function rowToVariable(r: VarRow): Record<string, unknown> {
  const out: Record<string, unknown> = { name: r.name.trim(), type: r.type, description: r.description.trim(), required: r.required, sensitive: r.sensitive };
  const d = r.sensitive ? null : typed(r.type, r.default);
  if (d !== null) out.default = d;
  if (r.type === "string" && r.pattern.trim()) out.pattern = r.pattern.trim();
  if (r.type === "string" && r.max_length.trim()) out.max_length = Number(r.max_length);
  return out;
}

export function defaultValue(type: VarType, text: string): string | number | boolean | null {
  return typed(type, text);
}

function DefaultField({ type, value, onChange, label, disabled, placeholder }: { type: VarType; value: string; onChange: (v: string) => void; label: string; disabled?: boolean; placeholder?: string }) {
  if (type === "boolean") {
    return <SelectField label={label} value={value} disabled={disabled} options={[{ value: "", label: placeholder ?? "No default" }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]} onChange={(e) => onChange(e.target.value)} />;
  }
  return <TextField label={label} value={value} disabled={disabled} placeholder={placeholder} inputMode={type === "integer" ? "numeric" : undefined} spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
}

/** The template's own variables, and defaults for the ones it inherits
 *  (docs/DEVICE_PROVISIONING.md §7). */
export function VariablesEditor({ rows, onRows, inherited, defaults, onDefaults }: {
  rows: VarRow[];
  onRows: (rows: VarRow[]) => void;
  inherited: TemplateVariable[];
  defaults: Record<string, string>;
  onDefaults: (d: Record<string, string>) => void;
}) {
  const set = (id: string, patch: Partial<VarRow>) => onRows(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  return (
    <div className="stack">
      <div className="stack stack--sm">
        {rows.length === 0 ? <p className="muted" style={{ margin: 0 }}>This template declares no variables of its own. Add one to make a setting adjustable per profile or device, then use it in a file as <span className="mono">{"{{ name }}"}</span>.</p> : null}
        {rows.map((r) => (
          <div key={r.id} className="var-row">
            <div className="var-row__grid">
              <TextField label="Name" required value={r.name} spellCheck={false} placeholder="backlight_level" help="Lower case, digits and _." onChange={(e) => set(r.id, { name: e.target.value })} />
              <SelectField label="Type" value={r.type} options={TYPES} onChange={(e) => set(r.id, { type: e.target.value as VarType, default: "" })} />
              <DefaultField label="Default" type={r.type} value={r.default} disabled={r.sensitive} placeholder={r.sensitive ? "Secrets have no default" : undefined} onChange={(v) => set(r.id, { default: v })} />
              <IconButton icon="trash" label={`Remove ${r.name || "variable"}`} onClick={() => onRows(rows.filter((x) => x.id !== r.id))} />
            </div>
            <TextField label="Description" value={r.description} placeholder="Shown next to the field on the profile and device" onChange={(e) => set(r.id, { description: e.target.value })} />
            <div className="row" style={{ gap: "var(--space-6)", flexWrap: "wrap" }}>
              <Switch label="Required" checked={r.required} onChange={(e) => set(r.id, { required: e.target.checked })} />
              <Switch label="Secret" description="Masked in previews, never exported, no default." checked={r.sensitive} onChange={(e) => set(r.id, { sensitive: e.target.checked, default: e.target.checked ? "" : r.default })} />
            </div>
            {r.type === "string" ? (
              <div className="form-grid">
                <TextField label="Allowed pattern" value={r.pattern} spellCheck={false} placeholder="^[0-9]{1,4}$" help="Optional regular expression the value must match." onChange={(e) => set(r.id, { pattern: e.target.value })} />
                <TextField label="Maximum length" inputMode="numeric" value={r.max_length} placeholder="255" onChange={(e) => set(r.id, { max_length: e.target.value.replace(/\D/g, "").slice(0, 4) })} />
              </div>
            ) : null}
          </div>
        ))}
        <div><Button icon="plus" onClick={() => onRows([...rows, newRow()])}>Add a variable</Button></div>
      </div>
      {inherited.length ? (
        <div className="stack stack--sm">
          <strong>Inherited from the parent</strong>
          <p className="muted" style={{ margin: 0 }}>Give a different default here; leave it empty to keep the parent&apos;s. Profiles and devices can still set their own value.</p>
          <div className="var-inherited">
            {inherited.map((v) => (
              <div key={v.name} className="var-inherited__row">
                <div>
                  <span className="mono">{v.name}</span>
                  <span className="subtle" style={{ display: "block" }}>{v.description || `${v.type} value`}</span>
                </div>
                <DefaultField label={`Default for ${v.name}`} type={v.type} value={defaults[v.name] ?? ""} disabled={v.sensitive}
                  placeholder={v.sensitive ? "Secret" : v.default === null || v.default === undefined ? "No default" : `Parent: ${String(v.default)}`}
                  onChange={(val) => onDefaults({ ...defaults, [v.name]: val })} />
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
