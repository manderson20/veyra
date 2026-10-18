// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Checkbox, TextArea, TextField } from "@/components/ui";
import { parseList } from "@/lib/routing";
import type { TimeCondition, TimeConditionInput, TimeRange } from "@/lib/types";
import { DEFAULT_RANGE, RangesEditor } from "./RangesEditor";

export interface TimeConditionDraft {
  name: string;
  description: string;
  timezone: string;
  ranges: TimeRange[];
  /** Comma separated MM-DD. */
  holidays: string;
  /** Digits after the override code (*27<index>); empty: no code. */
  code_index: string;
  /** Typed to set or replace the PIN; empty: unchanged (edit) or none (create). */
  pin: string;
  clear_pin: boolean;
}

export const EMPTY_TIME_CONDITION: TimeConditionDraft = {
  name: "",
  description: "",
  timezone: "",
  ranges: [{ ...DEFAULT_RANGE, days: [...DEFAULT_RANGE.days] }],
  holidays: "",
  code_index: "",
  pin: "",
  clear_pin: false,
};

export function timeConditionDraft(tc: TimeCondition, organizationTimezone?: string): TimeConditionDraft {
  return {
    name: tc.name,
    description: tc.description ?? "",
    // The API returns the effective zone; show it as inherited when it equals the organization's.
    timezone: organizationTimezone && tc.timezone === organizationTimezone ? "" : tc.timezone,
    ranges: tc.ranges.map((r) => ({ ...r, days: [...r.days] })),
    holidays: tc.holidays.join(", "),
    code_index: tc.code_index === null ? "" : String(tc.code_index),
    pin: "",
    clear_pin: false,
  };
}

export function timeConditionBody(d: TimeConditionDraft): TimeConditionInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    timezone: d.timezone.trim() || null,
    ranges: d.ranges,
    holidays: parseList(d.holidays),
    code_index: d.code_index.trim() === "" ? null : Number(d.code_index),
    ...(d.clear_pin ? { pin: null } : d.pin.trim() ? { pin: d.pin.trim() } : {}),
  };
}

export function timeConditionValid(d: TimeConditionDraft): boolean {
  const idx = d.code_index.trim();
  return d.name.trim().length > 0 && d.ranges.length > 0 && d.ranges.every((r) => r.days.length > 0 && r.start && r.end)
    && (idx === "" || (/^[0-9]{1,2}$/.test(idx) && Number(idx) <= 99))
    && (!d.pin.trim() || /^[0-9]{4,10}$/.test(d.pin.trim()));
}

export function TimeConditionFields({ draft, onChange, errors, timezonePlaceholder, disabled, autoFocus, current }: {
  draft: TimeConditionDraft;
  onChange: (patch: Partial<TimeConditionDraft>) => void;
  errors: Record<string, string>;
  timezonePlaceholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  current?: TimeCondition;
}) {
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Office hours"
          onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Time zone" disabled={disabled} value={draft.timezone} error={errors.timezone} autoComplete="off" spellCheck={false}
          placeholder={timezonePlaceholder ? `${timezonePlaceholder} (organization default)` : "Organization default"}
          help="IANA name such as America/Chicago. Empty: the organization's time zone." onChange={(e) => onChange({ timezone: e.target.value })} />
      </div>
      <RangesEditor ranges={draft.ranges} onChange={(ranges) => onChange({ ranges })} error={errors.ranges} disabled={disabled} />
      <TextField label="Holidays" disabled={disabled} value={draft.holidays} error={errors.holidays} autoComplete="off" spellCheck={false} placeholder="01-01, 07-04, 12-25"
        help="Dates as MM-DD, comma separated. The condition is closed all day on these dates every year." onChange={(e) => onChange({ holidays: e.target.value })} />
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <div className="form-grid">
        <TextField label="Override code index" disabled={disabled} value={draft.code_index} error={errors.code_index} inputMode="numeric" placeholder="None"
          help={current?.code ? <>Phones dial <span className="mono">{current.code}</span> to force the opposite state until the schedule changes, and again to clear it; a BLF key with that code lights while forced.</> : "0 to 99, after the override feature code (*27 by default). Empty: no phone override."}
          onChange={(e) => onChange({ code_index: e.target.value })} />
        <div className="stack stack--xs">
          <TextField label="Override PIN" type="password" autoComplete="off" inputMode="numeric" disabled={disabled || draft.clear_pin} value={draft.pin} error={errors.pin}
            help={draft.clear_pin ? "The PIN is removed when you save." : current?.has_pin ? "A PIN is set. Type a new one to replace it." : "4 to 10 digits asked before a phone overrides; empty: no PIN."}
            onChange={(e) => onChange({ pin: e.target.value })} />
          {current?.has_pin ? <Checkbox label="Remove the PIN" checked={draft.clear_pin} disabled={disabled} onChange={(e) => onChange({ clear_pin: e.target.checked, pin: "" })} /> : null}
        </div>
      </div>
    </>
  );
}
