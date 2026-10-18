// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Checkbox, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, type DestinationDraft } from "@/lib/routing";
import type { CallFlow, CallFlowInput } from "@/lib/types";

export interface CallFlowDraft {
  name: string;
  description: string;
  code_index: string;
  /** Typed to set or replace the PIN; empty: unchanged (edit) or none (create). */
  pin: string;
  clear_pin: boolean;
  normal: DestinationDraft;
  override_destination: DestinationDraft;
  is_enabled: boolean;
}

export const EMPTY_CALL_FLOW: CallFlowDraft = {
  name: "",
  description: "",
  code_index: "",
  pin: "",
  clear_pin: false,
  normal: HANGUP,
  override_destination: HANGUP,
  is_enabled: true,
};

export function callFlowDraft(f: CallFlow): CallFlowDraft {
  return {
    name: f.name,
    description: f.description ?? "",
    code_index: String(f.code_index),
    pin: "",
    clear_pin: false,
    normal: destinationDraft(f.normal, HANGUP),
    override_destination: destinationDraft(f.override_destination, HANGUP),
    is_enabled: f.is_enabled,
  };
}

export function callFlowBody(d: CallFlowDraft): CallFlowInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    code_index: Number(d.code_index),
    normal: destinationBody(d.normal),
    override_destination: destinationBody(d.override_destination),
    is_enabled: d.is_enabled,
    ...(d.clear_pin ? { pin: null } : d.pin.trim() ? { pin: d.pin.trim() } : {}),
  };
}

export function callFlowValid(d: CallFlowDraft): boolean {
  const idx = d.code_index.trim();
  return d.name.trim().length > 0
    && /^[0-9]{1,2}$/.test(idx) && Number(idx) <= 99
    && (!d.pin.trim() || /^[0-9]{4,10}$/.test(d.pin.trim()))
    && destinationComplete(d.normal) && destinationComplete(d.override_destination);
}

export function CallFlowFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: CallFlowDraft;
  onChange: (patch: Partial<CallFlowDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: CallFlow;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const options = useDestinationOptions(organizationId);
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Night mode"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : undefined} onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Code index" required disabled={disabled} value={draft.code_index} error={errors.code_index} inputMode="numeric" placeholder="e.g. 1"
          help={current?.code ? <>Phones dial <span className="mono">{current.code}</span> to switch; a BLF key with that code lights while switched.</> : "0 to 99, dialled after the toggle feature code (*28 by default). Unique per organization."}
          onChange={(e) => onChange({ code_index: e.target.value })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <DestinationPicker label="Normally, calls go to" idBase="flow-normal" draft={draft.normal} onChange={(normal) => onChange({ normal })} options={options} allowHangup
        current={current?.normal} error={errors.normal} disabled={disabled} exclude={current?.id} />
      <DestinationPicker label="While switched, calls go to" idBase="flow-override" draft={draft.override_destination} onChange={(override_destination) => onChange({ override_destination })} options={options} allowHangup
        current={current?.override_destination} error={errors.override_destination} disabled={disabled} exclude={current?.id} />
      <div className="stack stack--xs">
        <TextField label="PIN" type="password" autoComplete="off" inputMode="numeric" disabled={disabled || draft.clear_pin} value={draft.pin} error={errors.pin}
          help={draft.clear_pin ? "The PIN is removed when you save." : current?.has_pin ? "A PIN is set. Type a new one to replace it." : "4 to 10 digits asked before a phone switches; empty: no PIN."}
          onChange={(e) => onChange({ pin: e.target.value })} />
        {current?.has_pin ? <Checkbox label="Remove the PIN" checked={draft.clear_pin} disabled={disabled} onChange={(e) => onChange({ clear_pin: e.target.checked, pin: "" })} /> : null}
      </div>
      <Switch label="Enabled" description="A disabled call flow is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
