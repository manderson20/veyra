// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { SelectField } from "@/components/ui";
import type { HoldMusicSet, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/**
 * Choose a hold music set of an organization (docs/PAGING_RECORDINGS.md §3.2);
 * the empty choice is the built-in set.
 */
export function HoldMusicSelect({ organizationId, value, onChange, label = "Hold music set", help, error, disabled, builtinLabel = "Built-in music" }: {
  organizationId: string;
  value: string;
  onChange: (id: string) => void;
  label?: string;
  help?: React.ReactNode;
  error?: string;
  disabled?: boolean;
  builtinLabel?: string;
}) {
  const sets = useApiData<Page<HoldMusicSet>>(organizationId ? "/hold-music" : null, { organization_id: organizationId, limit: 200 });
  const opts = [{ value: "", label: builtinLabel }, ...(sets.data?.items ?? []).map((s) => ({ value: s.id, label: s.problems.length ? `${s.name} (needs attention)` : s.name }))];
  return (
    <SelectField label={label} disabled={disabled} value={value} error={error} help={help}
      options={value && !opts.some((o) => o.value === value) ? [...opts, { value, label: "Loading…" }] : opts}
      onChange={(e) => onChange(e.target.value)} />
  );
}
