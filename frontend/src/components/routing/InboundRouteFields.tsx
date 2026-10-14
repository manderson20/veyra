// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, EMPTY_DESTINATION, type DestinationDraft } from "@/lib/routing";
import type { InboundRoute, InboundRouteInput, Page, RouteDestinationType, TimeCondition, TrunkPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface InboundRouteDraft {
  did: string;
  trunk_id: string;
  description: string;
  destination: DestinationDraft;
  time_condition_id: string;
  after_hours: DestinationDraft;
  caller_id_prefix: string;
  is_enabled: boolean;
}

export const EMPTY_INBOUND_ROUTE: InboundRouteDraft = {
  did: "",
  trunk_id: "",
  description: "",
  destination: EMPTY_DESTINATION,
  time_condition_id: "",
  after_hours: EMPTY_DESTINATION,
  caller_id_prefix: "",
  is_enabled: true,
};

export function inboundRouteDraft(r: InboundRoute): InboundRouteDraft {
  return {
    did: r.did,
    trunk_id: r.trunk_id ?? "",
    description: r.description ?? "",
    destination: {
      type: r.destination_type,
      extension_id: r.destination_extension_id ?? "",
      ivr_id: r.destination_ivr_id ?? "",
      ring_group_id: r.destination_ring_group_id ?? "",
      queue_id: r.destination_queue_id ?? "",
      voicemail_box_id: r.destination_voicemail_box_id ?? "",
    },
    time_condition_id: r.time_condition_id ?? "",
    after_hours: r.time_condition_id
      ? {
        type: r.after_hours_type,
        extension_id: r.after_hours_extension_id ?? "",
        ivr_id: r.after_hours_ivr_id ?? "",
        ring_group_id: r.after_hours_ring_group_id ?? "",
        queue_id: r.after_hours_queue_id ?? "",
        voicemail_box_id: r.after_hours_voicemail_box_id ?? "",
      }
      : destinationDraft(null),
    caller_id_prefix: r.caller_id_prefix ?? "",
    is_enabled: r.is_enabled,
  };
}

export function inboundRouteBody(d: InboundRouteDraft): InboundRouteInput {
  const dest = destinationBody(d.destination);
  const after = d.time_condition_id ? destinationBody(d.after_hours) : null;
  return {
    did: d.did.trim(),
    trunk_id: d.trunk_id || null,
    description: d.description.trim() || null,
    destination_type: dest.type as RouteDestinationType,
    destination_extension_id: dest.extension_id ?? null,
    destination_ivr_id: dest.ivr_id ?? null,
    destination_ring_group_id: dest.ring_group_id ?? null,
    destination_queue_id: dest.queue_id ?? null,
    time_condition_id: d.time_condition_id || null,
    after_hours_type: (after?.type ?? "extension") as RouteDestinationType,
    after_hours_extension_id: after?.extension_id ?? null,
    after_hours_ivr_id: after?.ivr_id ?? null,
    after_hours_ring_group_id: after?.ring_group_id ?? null,
    after_hours_queue_id: after?.queue_id ?? null,
    caller_id_prefix: d.caller_id_prefix.trim() || null,
    is_enabled: d.is_enabled,
  };
}

export function inboundRouteValid(d: InboundRouteDraft): boolean {
  return d.did.trim().length > 0 && destinationComplete(d.destination) && (!d.time_condition_id || destinationComplete(d.after_hours));
}

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
  const options = useDestinationOptions(organizationId);
  const conditions = useApiData<Page<TimeCondition>>(organizationId ? "/routing/time-conditions" : null, { organization_id: organizationId, limit: 200 });
  const trunks = useApiData<TrunkPage>("/trunks");
  const tcOptions = (conditions.data?.items ?? []).map((t) => ({ value: t.id, label: t.name }));
  const trunkOptions = (trunks.data?.items ?? []).map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name} (disabled)` }));
  // Keep the saved value selectable even if it is no longer in the list.
  const withCurrent = (opts: { value: string; label: string }[], value: string, label: string | null) =>
    value && !opts.some((o) => o.value === value) ? [...opts, { value, label: label ?? "Unknown" }] : opts;
  const conditionOptions = withCurrent(tcOptions, draft.time_condition_id, current?.time_condition_name ?? null);
  const canPickTrunk = !trunks.error;
  const destError = errors.destination_extension_id ?? errors.destination_ivr_id ?? errors.destination_ring_group_id ?? errors.destination_queue_id;
  const afterError = errors.after_hours_extension_id ?? errors.after_hours_ivr_id;
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
      {organizationId ? (
        <DestinationPicker label="Destination" idBase="ir-dest" draft={draft.destination} onChange={(destination) => onChange({ destination })} options={options}
          current={current?.destination} error={destError} disabled={disabled} />
      ) : (
        <SelectField label="Destination" required disabled value="" placeholder="Choose an organization first" options={[]} />
      )}
      <SelectField label="Time condition" disabled={disabled || !organizationId} value={draft.time_condition_id} error={errors.time_condition_id} placeholder="Always (no time condition)"
        help="When closed, calls go to the after-hours destination instead." options={conditionOptions}
        onChange={(e) => onChange({ time_condition_id: e.target.value })} />
      {draft.time_condition_id ? (
        <DestinationPicker label="After-hours destination" idBase="ir-after" draft={draft.after_hours} onChange={(after_hours) => onChange({ after_hours })} options={options}
          current={current?.after_hours} error={afterError} disabled={disabled} />
      ) : null}
      <TextField label="Caller ID prefix" disabled={disabled} value={draft.caller_id_prefix} error={errors.caller_id_prefix} placeholder="e.g. Sales:" autoComplete="off"
        help="Text put in front of the caller's name so the answering phone shows which number was called." onChange={(e) => onChange({ caller_id_prefix: e.target.value })} />
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <Switch label="Enabled" description="Disabled routes are kept but calls to the DID are not answered by them." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
