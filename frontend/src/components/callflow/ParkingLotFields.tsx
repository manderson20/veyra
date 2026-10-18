// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Checkbox, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, type DestinationDraft } from "@/lib/routing";
import type { ParkingLot, ParkingLotInput } from "@/lib/types";

export interface ParkingLotDraft {
  name: string;
  description: string;
  park_exten: string;
  slot_first: string;
  slot_last: string;
  timeout_seconds: string;
  return_ring_seconds: string;
  courtesy_tone: boolean;
  timeout: DestinationDraft;
  is_enabled: boolean;
}

export const EMPTY_PARKING_LOT: ParkingLotDraft = {
  name: "",
  description: "",
  park_exten: "70",
  slot_first: "71",
  slot_last: "79",
  timeout_seconds: "45",
  return_ring_seconds: "20",
  courtesy_tone: true,
  timeout: HANGUP,
  is_enabled: true,
};

export function parkingLotDraft(l: ParkingLot): ParkingLotDraft {
  return {
    name: l.name,
    description: l.description ?? "",
    park_exten: l.park_exten,
    slot_first: String(l.slot_first),
    slot_last: String(l.slot_last),
    timeout_seconds: String(l.timeout_seconds),
    return_ring_seconds: String(l.return_ring_seconds),
    courtesy_tone: l.courtesy_tone,
    timeout: destinationDraft(l.timeout, HANGUP),
    is_enabled: l.is_enabled,
  };
}

export function parkingLotBody(d: ParkingLotDraft): ParkingLotInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    park_exten: d.park_exten.trim(),
    slot_first: Number(d.slot_first),
    slot_last: Number(d.slot_last),
    timeout_seconds: Number(d.timeout_seconds),
    return_ring_seconds: Number(d.return_ring_seconds),
    courtesy_tone: d.courtesy_tone,
    timeout: destinationBody(d.timeout),
    is_enabled: d.is_enabled,
  };
}

export function parkingLotValid(d: ParkingLotDraft): boolean {
  const first = Number(d.slot_first);
  const last = Number(d.slot_last);
  const park = Number(d.park_exten.trim());
  const t = Number(d.timeout_seconds);
  const r = Number(d.return_ring_seconds);
  return d.name.trim().length > 0
    && /^[0-9]{1,32}$/.test(d.park_exten.trim())
    && Number.isInteger(first) && Number.isInteger(last) && first >= 1 && last >= first && last - first + 1 <= 50
    && !(park >= first && park <= last)
    && Number.isInteger(t) && t >= 10 && t <= 1800
    && Number.isInteger(r) && r >= 5 && r <= 120
    && destinationComplete(d.timeout);
}

export function ParkingLotFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: ParkingLotDraft;
  onChange: (patch: Partial<ParkingLotDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: ParkingLot;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const options = useDestinationOptions(organizationId);
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Front office lot"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : undefined} onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Park extension" required disabled={disabled} value={draft.park_exten} error={errors.park_exten} inputMode="numeric"
          help="Transfer a call here to park it in the next free slot; the parker hears the slot number." onChange={(e) => onChange({ park_exten: e.target.value })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <div className="form-grid">
        <TextField label="First slot" required type="number" min={1} disabled={disabled} value={draft.slot_first} error={errors.slot_first} onChange={(e) => onChange({ slot_first: e.target.value })} />
        <TextField label="Last slot" required type="number" min={1} disabled={disabled} value={draft.slot_last} error={errors.slot_last}
          help="At most 50 slots. Dial a slot to pick the call up; a line key with the slot number lights while a call waits there." onChange={(e) => onChange({ slot_last: e.target.value })} />
      </div>
      <div className="form-grid">
        <TextField label="Parked call times out after (seconds)" required type="number" min={10} max={1800} disabled={disabled} value={draft.timeout_seconds} error={errors.timeout_seconds}
          help="Then the phone that parked the call rings." onChange={(e) => onChange({ timeout_seconds: e.target.value })} />
        <TextField label="Ring the parker for (seconds)" required type="number" min={5} max={120} disabled={disabled} value={draft.return_ring_seconds} error={errors.return_ring_seconds}
          help="Unanswered, the call goes to the destination below." onChange={(e) => onChange({ return_ring_seconds: e.target.value })} />
      </div>
      <DestinationPicker label="When the parker does not answer" idBase="park-timeout" draft={draft.timeout} onChange={(timeout) => onChange({ timeout })} options={options} allowHangup
        current={current?.timeout} error={errors.timeout} disabled={disabled} />
      <Checkbox label="Play a courtesy tone when a call is picked up" checked={draft.courtesy_tone} disabled={disabled} onChange={(e) => onChange({ courtesy_tone: e.target.checked })} />
      <Switch label="Enabled" description="A disabled lot is left out of the phone system." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
