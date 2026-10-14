// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Button, SelectField, TextField } from "@/components/ui";
import type { LineKey, LineKeyType, PagingZone } from "@/lib/types";

export const KEY_TYPE_LABELS: Record<LineKeyType, string> = { line: "Line", blf: "BLF (watch a phone or group)", speed_dial: "Speed dial", page: "Page a zone" };

/** Ordered line keys of a profile or device (docs/DEVICE_PROVISIONING.md §4.2). */
export function KeyListEditor({ keys, onChange, zones, disabled, error }: { keys: LineKey[]; onChange: (keys: LineKey[]) => void; zones: PagingZone[]; disabled?: boolean; error?: string }) {
  const update = (i: number, patch: Partial<LineKey>) => onChange(keys.map((k, j) => (j === i ? { ...k, ...patch } : k)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= keys.length) return;
    const next = [...keys];
    [next[i], next[j]] = [next[j]!, next[i]!];
    onChange(next);
  };
  return (
    <div className="stack stack--sm">
      {keys.length === 0 ? <p className="muted">No line keys. Line 1 is always the first key on Poly phones; add BLF, speed dial and paging keys here.</p> : null}
      {keys.map((k, i) => (
        <div key={i} className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <span className="mono subtle" style={{ width: 24, paddingBottom: 10 }}>{i + 1}</span>
          <SelectField label={<span className="sr-only">Key {i + 1} type</span>} value={k.type} disabled={disabled} options={(Object.keys(KEY_TYPE_LABELS) as LineKeyType[]).map((t) => ({ value: t, label: KEY_TYPE_LABELS[t] }))}
            onChange={(e) => update(i, { type: e.target.value as LineKeyType, value: e.target.value === "line" ? "1" : "" })} />
          {k.type === "page" ? (
            <SelectField label={<span className="sr-only">Zone</span>} value={k.value} disabled={disabled} placeholder="Choose a zone" options={zones.map((z) => ({ value: z.slug, label: `${z.name} (group ${z.poly_group})` }))} onChange={(e) => update(i, { value: e.target.value })} />
          ) : (
            <TextField label={<span className="sr-only">Key {i + 1} value</span>} disabled={disabled} value={k.value} placeholder={k.type === "line" ? "Line number" : "Number"} inputMode={k.type === "line" ? "numeric" : "tel"} style={{ width: 140 }} onChange={(e) => update(i, { value: e.target.value })} />
          )}
          <TextField label={<span className="sr-only">Key {i + 1} label</span>} disabled={disabled} value={k.label ?? ""} placeholder="Label (optional)" style={{ width: 160 }} onChange={(e) => update(i, { label: e.target.value || null })} />
          {!disabled ? (
            <span className="row" style={{ gap: 2, paddingBottom: 2 }}>
              <Button size="sm" variant="ghost" icon="chevronUp" onClick={() => move(i, -1)} aria-label="Move up" disabled={i === 0} />
              <Button size="sm" variant="ghost" icon="chevronDown" onClick={() => move(i, 1)} aria-label="Move down" disabled={i === keys.length - 1} />
              <Button size="sm" variant="ghost" icon="trash" onClick={() => onChange(keys.filter((_, j) => j !== i))} aria-label="Remove key" />
            </span>
          ) : null}
        </div>
      ))}
      {error ? <p className="field__error">{error}</p> : null}
      {!disabled ? <div><Button size="sm" icon="plus" onClick={() => onChange([...keys, { type: "blf", label: null, value: "" }])}>Add key</Button></div> : null}
    </div>
  );
}
