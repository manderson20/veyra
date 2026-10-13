// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { SelectField, Switch, TextArea, TextField } from "@/components/ui";
import type { Extension, InboundRoute, InboundRouteInput, Page, TimeCondition, TrunkPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface InboundRouteDraft {
  did: string;
  trunk_id: string;
  description: string;
  destination_extension_id: string;
  time_condition_id: string;
  after_hours_extension_id: string;
  caller_id_prefix: string;
  is_enabled: boolean;
}

export const EMPTY_INBOUND_ROUTE: InboundRouteDraft = {
  did: "",
  trunk_id: "",
  description: "",
  destination_extension_id: "",
  time_condition_id: "",
  after_hours_extension_id: "",
  caller_id_prefix: "",
  is_enabled: true,
};

export function inboundRouteDraft(r: InboundRoute): InboundRouteDraft {
  return {
    did: r.did,
    trunk_id: r.trunk_id ?? "",
    description: r.description ?? "",
    destination_extension_id: r.destination_extension_id ?? "",
    time_condition_id: r.time_condition_id ?? "",
    after_hours_extension_id: r.after_hours_extension_id ?? "",
    caller_id_prefix: r.caller_id_prefix ?? "",
    is_enabled: r.is_enabled,
  };
}

export function inboundRouteBody(d: InboundRouteDraft): InboundRouteInput {
  return {
    did: d.did.trim(),
    trunk_id: d.trunk_id || null,
    description: d.description.trim() || null,
    destination_type: "extension",
    destination_extension_id: d.destination_extension_id || null,
    time_condition_id: d.time_condition_id || null,
    after_hours_extension_id: d.time_condition_id ? d.after_hours_extension_id || null : null,
    caller_id_prefix: d.caller_id_prefix.trim() || null,
    is_enabled: d.is_enabled,
  };
}

export function inboundRouteValid(d: InboundRouteDraft): boolean {
  return d.did.trim().length > 0 && !!d.destination_extension_id && (!d.time_condition_id || !!d.after_hours_extension_id);
}

const extLabel = (x: Extension) => `${x.number} — ${x.display_name}${x.is_enabled ? "" : " (disabled)"}`;

/**
 * Fields shared by the create dialog and the detail page. Pickers are scoped
 * to `organizationId`; the trunk picker is hidden when the caller may not list trunks.
 */
export function InboundRouteFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: InboundRouteDraft;
  onChange: (patch: Partial<InboundRouteDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  /** The saved route, so that names show even when pickers cannot load. */
  current?: InboundRoute;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const extensions = useApiData<Page<Extension>>(organizationId ? "/extensions" : null, { organization_id: organizationId, limit: 200 });
  const conditions = useApiData<Page<TimeCondition>>(organizationId ? "/routing/time-conditions" : null, { organization_id: organizationId, limit: 200 });
  const trunks = useApiData<TrunkPage>("/trunks");
  const extOptions = (extensions.data?.items ?? []).map((x) => ({ value: x.id, label: extLabel(x) }));
  const tcOptions = (conditions.data?.items ?? []).map((t) => ({ value: t.id, label: t.name }));
  const trunkOptions = (trunks.data?.items ?? []).map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name} (disabled)` }));
  // Keep the saved value selectable even if it is no longer in the list.
  const withCurrent = (opts: { value: string; label: string }[], value: string, label: string | null) =>
    value && !opts.some((o) => o.value === value) ? [...opts, { value, label: label ?? "Unknown" }] : opts;
  const destOptions = withCurrent(extOptions, draft.destination_extension_id, current?.destination_number ? `${current.destination_number} — ${current.destination_name ?? ""}` : "Deleted extension");
  const afterOptions = withCurrent(extOptions, draft.after_hours_extension_id, current?.after_hours_number ? `${current.after_hours_number} — ${current.after_hours_name ?? ""}` : "Deleted extension");
  const conditionOptions = withCurrent(tcOptions, draft.time_condition_id, current?.time_condition_name ?? null);
  const canPickTrunk = !trunks.error;
  return (
    <>
      <div className="form-grid">
        <TextField label="DID" required autoFocus={autoFocus} disabled={disabled} value={draft.did} error={errors.did} inputMode="tel" autoComplete="off" spellCheck={false}
          placeholder="+15555550100 or any" help="The number the carrier sends, digits with an optional leading +. Enter any for a catch-all route."
          onChange={(e) => onChange({ did: e.target.value })} />
        {canPickTrunk ? (
          <SelectField label="Trunk" disabled={disabled} value={draft.trunk_id} error={errors.trunk_id} placeholder="Any trunk"
            help="Restrict this route to calls arriving on one trunk." options={withCurrent(trunkOptions, draft.trunk_id, current?.trunk_name ?? null)} onChange={(e) => onChange({ trunk_id: e.target.value })} />
        ) : (
          <TextField label="Trunk" disabled value={current?.trunk_name ?? "Any trunk"} help="Only platform administrators can change the trunk." />
        )}
      </div>
      <SelectField label="Destination extension" required disabled={disabled || !organizationId} value={draft.destination_extension_id} error={errors.destination_extension_id}
        placeholder={organizationId ? (extensions.loading ? "Loading extensions…" : "Choose an extension") : "Choose an organization first"}
        help={current?.destination_missing ? "The previous destination no longer exists; choose a new one." : undefined}
        options={destOptions} onChange={(e) => onChange({ destination_extension_id: e.target.value })} />
      <div className="form-grid">
        <SelectField label="Time condition" disabled={disabled || !organizationId} value={draft.time_condition_id} error={errors.time_condition_id} placeholder="Always (no time condition)"
          help="When closed, calls go to the after-hours extension instead." options={conditionOptions}
          onChange={(e) => onChange({ time_condition_id: e.target.value, after_hours_extension_id: e.target.value ? draft.after_hours_extension_id : "" })} />
        {draft.time_condition_id ? (
          <SelectField label="After-hours extension" required disabled={disabled} value={draft.after_hours_extension_id} error={errors.after_hours_extension_id} placeholder="Choose an extension"
            options={afterOptions} onChange={(e) => onChange({ after_hours_extension_id: e.target.value })} />
        ) : null}
      </div>
      <TextField label="Caller ID prefix" disabled={disabled} value={draft.caller_id_prefix} error={errors.caller_id_prefix} placeholder="e.g. Sales:" autoComplete="off"
        help="Text put in front of the caller's name so the answering phone shows which number was called." onChange={(e) => onChange({ caller_id_prefix: e.target.value })} />
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <Switch label="Enabled" description="Disabled routes are kept but calls to the DID are not answered by them." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
