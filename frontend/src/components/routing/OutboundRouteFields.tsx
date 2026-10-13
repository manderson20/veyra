// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Checkbox, Switch, TextArea, TextField } from "@/components/ui";
import type { OutboundPattern, OutboundRoute, OutboundRouteInput } from "@/lib/types";
import { EMPTY_PATTERN, PatternsEditor } from "./PatternsEditor";
import { TrunkOrderEditor, type TrunkOption } from "./TrunkOrderEditor";

export interface OutboundRouteDraft {
  name: string;
  description: string;
  is_emergency: boolean;
  is_enabled: boolean;
  patterns: OutboundPattern[];
  trunk_ids: string[];
  caller_id_number: string;
}

export const EMPTY_OUTBOUND_ROUTE: OutboundRouteDraft = {
  name: "",
  description: "",
  is_emergency: false,
  is_enabled: true,
  patterns: [{ ...EMPTY_PATTERN }],
  trunk_ids: [],
  caller_id_number: "",
};

export function outboundRouteDraft(r: OutboundRoute): OutboundRouteDraft {
  return {
    name: r.name,
    description: r.description ?? "",
    is_emergency: r.is_emergency,
    is_enabled: r.is_enabled,
    patterns: r.patterns.map((p) => ({ ...p })),
    trunk_ids: r.trunks.map((t) => t.id),
    caller_id_number: r.caller_id_number ?? "",
  };
}

export function outboundRouteBody(d: OutboundRouteDraft): OutboundRouteInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    is_emergency: d.is_emergency,
    is_enabled: d.is_enabled,
    patterns: d.patterns.map((p) => ({ prefix: p.prefix.trim(), match: p.match.trim(), prepend: p.prepend.trim() })),
    trunk_ids: d.trunk_ids,
    caller_id_number: d.caller_id_number.trim() || null,
  };
}

export function outboundRouteValid(d: OutboundRouteDraft): boolean {
  return d.name.trim().length > 0 && d.patterns.length > 0 && d.patterns.every((p) => p.match.trim()) && d.trunk_ids.length > 0;
}

export function OutboundRouteFields({ draft, onChange, errors, trunks, disabled, autoFocus }: {
  draft: OutboundRouteDraft;
  onChange: (patch: Partial<OutboundRouteDraft>) => void;
  errors: Record<string, string>;
  trunks: TrunkOption[];
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Local calls"
          onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Caller ID number" inputMode="tel" disabled={disabled} value={draft.caller_id_number} error={errors.caller_id_number}
          help="Overrides the extension's caller ID for calls on this route." onChange={(e) => onChange({ caller_id_number: e.target.value })} />
      </div>
      <Checkbox label="Emergency route" description="Emergency routes are evaluated before all others and cannot be moved below them. Use for 911 and similar numbers." checked={draft.is_emergency} disabled={disabled}
        onChange={(e) => onChange({ is_emergency: e.target.checked })} />
      <PatternsEditor patterns={draft.patterns} onChange={(patterns) => onChange({ patterns })} error={errors.patterns ?? errors.route} disabled={disabled} />
      <TrunkOrderEditor trunkIds={draft.trunk_ids} trunks={trunks} onChange={(trunk_ids) => onChange({ trunk_ids })} error={errors.trunk_ids} disabled={disabled} />
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <Switch label="Enabled" description="Disabled routes are kept but never match a dialled number." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
