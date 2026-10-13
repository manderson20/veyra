// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Button, IconButton, TextField } from "@/components/ui";
import { WEEKDAYS, WEEKDAY_LABELS } from "@/lib/routing";
import type { TimeRange, Weekday } from "@/lib/types";

export const DEFAULT_RANGE: TimeRange = { days: ["mon", "tue", "wed", "thu", "fri"], start: "08:00", end: "17:00" };

/** Rows of weekday toggles plus start and end times. */
export function RangesEditor({ ranges, onChange, error, disabled }: {
  ranges: TimeRange[];
  onChange: (next: TimeRange[]) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  const update = (i: number, patch: Partial<TimeRange>) => onChange(ranges.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const toggleDay = (i: number, day: Weekday) => {
    const r = ranges[i];
    if (!r) return;
    const days = r.days.includes(day) ? r.days.filter((d) => d !== day) : WEEKDAYS.filter((d) => d === day || r.days.includes(d));
    update(i, { days });
  };
  return (
    <div className="field">
      <span className="field__label">Open hours<span className="field__required" aria-hidden="true">*</span></span>
      {ranges.map((r, i) => (
        <div key={i} className="stack stack--sm" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-3)" }}>
          <div className="row row--between">
            <div className="row" role="group" aria-label={`Days for range ${i + 1}`} style={{ gap: 4 }}>
              {WEEKDAYS.map((d) => {
                const on = r.days.includes(d);
                return (
                  <button key={d} type="button" className={on ? "btn btn--sm btn--primary" : "btn btn--sm btn--secondary"} aria-pressed={on} disabled={disabled}
                    onClick={() => toggleDay(i, d)}>
                    {WEEKDAY_LABELS[d]}
                  </button>
                );
              })}
            </div>
            <IconButton size="sm" icon="trash" label={`Remove range ${i + 1}`} disabled={disabled || ranges.length <= 1} onClick={() => onChange(ranges.filter((_, j) => j !== i))} />
          </div>
          <div className="form-grid">
            <TextField label="From" type="time" required disabled={disabled} value={r.start} onChange={(e) => update(i, { start: e.target.value })} />
            <TextField label="Until" type="time" required disabled={disabled} value={r.end} onChange={(e) => update(i, { end: e.target.value })} />
          </div>
        </div>
      ))}
      <p className="field__help">Calls arriving within any range count as open; everything else, and holidays, as closed.</p>
      {error ? <p className="field__error" role="alert">{error}</p> : null}
      {!disabled ? <div><Button size="sm" icon="plus" onClick={() => onChange([...ranges, { days: ["sat"], start: "09:00", end: "12:00" }])}>Add range</Button></div> : null}
    </div>
  );
}
