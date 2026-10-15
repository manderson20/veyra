// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useId } from "react";

/** A scrollable list of checkboxes for choosing several items. */
export function PickList({ label, options, value, onChange, error }: {
  label: string;
  options: { id: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
  error?: string;
}) {
  const id = useId();
  const chosen = new Set(value);
  return (
    <fieldset className="field" aria-describedby={error ? `${id}-error` : undefined} style={{ border: 0, padding: 0, margin: 0 }}>
      <legend className="field__label">{label} <span className="subtle">({value.length} chosen)</span></legend>
      <div className="picklist">
        {options.length === 0 ? <p className="subtle" style={{ margin: 8 }}>None in this organization.</p> : options.map((o) => (
          <label key={o.id} className="check">
            <input type="checkbox" checked={chosen.has(o.id)}
              onChange={(e) => onChange(e.target.checked ? [...value, o.id] : value.filter((v) => v !== o.id))} />
            <span className="check__text"><span>{o.label}</span></span>
          </label>
        ))}
      </div>
      {error ? <p className="field__error" id={`${id}-error`} role="alert">{error}</p> : null}
    </fieldset>
  );
}
