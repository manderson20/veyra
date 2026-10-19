// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Button, Checkbox, IconButton, SelectField, TextField } from "@/components/ui";
import { MONTH_DAYS, MONTH_NAMES, NTH_LABELS, WEEKDAYS, WEEKDAY_NAMES, describeHoliday, formatHoliday, newHoliday, type Holiday } from "@/lib/holidays";
import type { Weekday } from "@/lib/types";

const KIND_OPTIONS = [
  { value: "yearly", label: "Same date every year" },
  { value: "once", label: "Once (this year's dates)" },
  { value: "nth", label: "A weekday of a month" },
];
const MONTH_OPTIONS = MONTH_NAMES.map((m, i) => ({ value: String(i + 1), label: m }));
const dayOptions = (month: number) => Array.from({ length: MONTH_DAYS[month - 1] ?? 31 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }));

/** Closed days of a time condition: fixed dates, one-off dates or ranges
 * (snow days, winter break), and moving holidays such as Thanksgiving. */
export function HolidaysEditor({ holidays, onChange, error, disabled }: {
  holidays: Holiday[];
  onChange: (next: Holiday[]) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  const update = (i: number, h: Holiday) => onChange(holidays.map((x, j) => (j === i ? h : x)));
  return (
    <div className="field">
      <span className="field__label">Holidays and closed days</span>
      {holidays.map((h, i) => (
        <div key={i} className="stack stack--sm" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-3)" }}>
          <div className="row row--between" style={{ alignItems: "flex-end" }}>
            {h.kind === "raw" ? <span className="mono">{h.value}</span> : (
              <SelectField label="Repeats" disabled={disabled} value={h.kind} options={KIND_OPTIONS} onChange={(e) => update(i, newHoliday(e.target.value as Holiday["kind"]))} />
            )}
            <IconButton size="sm" icon="trash" label={`Remove holiday ${i + 1}`} disabled={disabled} onClick={() => onChange(holidays.filter((_, j) => j !== i))} />
          </div>
          {h.kind === "yearly" ? (
            <>
              <div className="form-grid">
                <SelectField label="Month" disabled={disabled} value={String(h.month)} options={MONTH_OPTIONS}
                  onChange={(e) => update(i, { ...h, month: Number(e.target.value), day: Math.min(h.day, MONTH_DAYS[Number(e.target.value) - 1]!) })} />
                <SelectField label="Day" disabled={disabled} value={String(h.day)} options={dayOptions(h.month)} onChange={(e) => update(i, { ...h, day: Number(e.target.value) })} />
              </div>
              <Checkbox label="Several days in a row" disabled={disabled} checked={h.untilMonth !== null}
                onChange={(e) => update(i, e.target.checked ? { ...h, untilMonth: h.month, untilDay: Math.min(h.day + 1, MONTH_DAYS[h.month - 1]!) } : { ...h, untilMonth: null, untilDay: null })} />
              {h.untilMonth !== null ? (
                <div className="form-grid">
                  <SelectField label="Until month" disabled={disabled} value={String(h.untilMonth)} options={MONTH_OPTIONS}
                    onChange={(e) => update(i, { ...h, untilMonth: Number(e.target.value), untilDay: Math.min(h.untilDay ?? 1, MONTH_DAYS[Number(e.target.value) - 1]!) })} />
                  <SelectField label="Until day" disabled={disabled} value={String(h.untilDay)} options={dayOptions(h.untilMonth)} onChange={(e) => update(i, { ...h, untilDay: Number(e.target.value) })} />
                </div>
              ) : null}
            </>
          ) : null}
          {h.kind === "once" ? (
            <div className="form-grid">
              <TextField label="Date" type="date" required disabled={disabled} value={h.date} onChange={(e) => update(i, { ...h, date: e.target.value })} />
              <TextField label="Until (optional)" type="date" disabled={disabled} value={h.until} min={h.date || undefined} onChange={(e) => update(i, { ...h, until: e.target.value })} />
            </div>
          ) : null}
          {h.kind === "nth" ? (
            <div className="form-grid form-grid--3">
              <SelectField label="Which" disabled={disabled} value={h.nth} options={Object.entries(NTH_LABELS).map(([value, label]) => ({ value, label }))}
                onChange={(e) => update(i, { ...h, nth: e.target.value as typeof h.nth })} />
              <SelectField label="Weekday" disabled={disabled} value={h.weekday} options={WEEKDAYS.map((d) => ({ value: d, label: WEEKDAY_NAMES[d] }))}
                onChange={(e) => update(i, { ...h, weekday: e.target.value as Weekday })} />
              <SelectField label="Month" disabled={disabled} value={String(h.month)} options={MONTH_OPTIONS} onChange={(e) => update(i, { ...h, month: Number(e.target.value) })} />
            </div>
          ) : null}
          {h.kind !== "once" || h.date ? <p className="field__help" style={{ margin: 0 }}>{describeHoliday(formatHoliday(h))}</p> : null}
        </div>
      ))}
      <p className="field__help">The condition is closed all day on these days, whatever the open hours say.</p>
      {error ? <p className="field__error" role="alert">{error}</p> : null}
      {!disabled ? (
        <div className="row" style={{ gap: 8 }}>
          <Button size="sm" icon="plus" onClick={() => onChange([...holidays, newHoliday("yearly")])}>Add holiday</Button>
          <Button size="sm" icon="plus" onClick={() => onChange([...holidays, newHoliday("once")])}>Add closed day</Button>
        </div>
      ) : null}
    </div>
  );
}
