// SPDX-License-Identifier: AGPL-3.0-or-later
/** Grouping of configuration check findings for the check window (docs/CONFIG_VERIFICATION.md §7.1). */

import type { ConfigFinding } from "@/lib/types";

/** Findings of the same setting, rule and value on several models: one row. */
export interface FindingGroup {
  key: string;
  first: ConfigFinding;
  models: string[];
  fingerprints: string[];
  overridden: boolean;
}

export function groupFindings(findings: ConfigFinding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>();
  for (const f of findings) {
    const key = [f.severity, f.rule, f.file, f.parameter, f.value, f.message, f.profile_id ?? ""].join("\u0000");
    const g = groups.get(key);
    if (g) {
      if (!g.models.includes(f.model)) g.models.push(f.model);
      if (!g.fingerprints.includes(f.fingerprint)) g.fingerprints.push(f.fingerprint);
      g.overridden = g.overridden && Boolean(f.override);
    } else {
      groups.set(key, { key, first: f, models: f.model ? [f.model] : [], fingerprints: [f.fingerprint], overridden: Boolean(f.override) });
    }
  }
  return [...groups.values()];
}

/** Counts by what the window shows: open errors, warnings, overridden, notes. */
export function countFindings(findings: ConfigFinding[]) {
  const groups = groupFindings(findings);
  return {
    errors: groups.filter((g) => g.first.severity === "error" && !g.overridden).length,
    overridden: groups.filter((g) => g.first.severity === "error" && g.overridden).length,
    warnings: groups.filter((g) => g.first.severity === "warning").length,
    notes: groups.filter((g) => g.first.severity === "info"),
  };
}

