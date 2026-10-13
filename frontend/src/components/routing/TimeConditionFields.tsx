// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { TextArea, TextField } from "@/components/ui";
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
}

export const EMPTY_TIME_CONDITION: TimeConditionDraft = {
  name: "",
  description: "",
  timezone: "",
  ranges: [{ ...DEFAULT_RANGE, days: [...DEFAULT_RANGE.days] }],
  holidays: "",
};

export function timeConditionDraft(tc: TimeCondition, organizationTimezone?: string): TimeConditionDraft {
  return {
    name: tc.name,
    description: tc.description ?? "",
    // The API returns the effective zone; show it as inherited when it equals the organization's.
    timezone: organizationTimezone && tc.timezone === organizationTimezone ? "" : tc.timezone,
    ranges: tc.ranges.map((r) => ({ ...r, days: [...r.days] })),
    holidays: tc.holidays.join(", "),
  };
}

export function timeConditionBody(d: TimeConditionDraft): TimeConditionInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    timezone: d.timezone.trim() || null,
    ranges: d.ranges,
    holidays: parseList(d.holidays),
  };
}

export function timeConditionValid(d: TimeConditionDraft): boolean {
  return d.name.trim().length > 0 && d.ranges.length > 0 && d.ranges.every((r) => r.days.length > 0 && r.start && r.end);
}

export function TimeConditionFields({ draft, onChange, errors, timezonePlaceholder, disabled, autoFocus }: {
  draft: TimeConditionDraft;
  onChange: (patch: Partial<TimeConditionDraft>) => void;
  errors: Record<string, string>;
  timezonePlaceholder?: string;
  disabled?: boolean;
  autoFocus?: boolean;
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
    </>
  );
}
