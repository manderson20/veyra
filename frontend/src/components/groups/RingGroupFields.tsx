// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { HoldMusicSelect } from "@/components/holdmusic/HoldMusicSelect";
import { MemberListEditor, membersFromIds, membersValid, type MemberDraft } from "@/components/groups/MemberListEditor";
import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Checkbox, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, type DestinationDraft } from "@/lib/routing";
import type { QueueMusic, RingGroup, RingGroupInput, RingGroupStrategy } from "@/lib/types";

export interface RingGroupDraft {
  name: string;
  number: string;
  description: string;
  strategy: RingGroupStrategy;
  ring_seconds: string;
  ring_busy_members: boolean;
  caller_id_prefix: string;
  music: QueueMusic;
  moh_class_id: string;
  failover: DestinationDraft;
  members: MemberDraft[];
  is_enabled: boolean;
}

export const EMPTY_RING_GROUP: RingGroupDraft = {
  name: "",
  number: "",
  description: "",
  strategy: "ringall",
  ring_seconds: "20",
  ring_busy_members: false,
  caller_id_prefix: "",
  music: "ring",
  moh_class_id: "",
  failover: HANGUP,
  members: [],
  is_enabled: true,
};

export const RING_STRATEGY_LABELS: Record<RingGroupStrategy, string> = {
  ringall: "Ring all members at once",
  sequential: "Ring members one after the other",
};

export function ringGroupDraft(g: RingGroup): RingGroupDraft {
  return {
    name: g.name,
    number: g.number,
    description: g.description ?? "",
    strategy: g.strategy,
    ring_seconds: String(g.ring_seconds),
    ring_busy_members: g.ring_busy_members,
    caller_id_prefix: g.caller_id_prefix ?? "",
    music: g.music ?? "ring",
    moh_class_id: g.moh_class_id ?? "",
    failover: destinationDraft(g.failover, HANGUP),
    members: membersFromIds(g.members),
    is_enabled: g.is_enabled,
  };
}

export function ringGroupBody(d: RingGroupDraft): RingGroupInput {
  return {
    name: d.name.trim(),
    number: d.number.trim(),
    description: d.description.trim() || null,
    strategy: d.strategy,
    ring_seconds: Number(d.ring_seconds),
    ring_busy_members: d.ring_busy_members,
    caller_id_prefix: d.caller_id_prefix.trim() || null,
    music: d.music,
    moh_class_id: d.music === "default" ? d.moh_class_id || null : null,
    failover: destinationBody(d.failover),
    members: d.members.map((m) => m.extension_id),
    is_enabled: d.is_enabled,
  };
}

export function ringGroupValid(d: RingGroupDraft): boolean {
  const r = Number(d.ring_seconds);
  return d.name.trim().length > 0 && /^[0-9]+$/.test(d.number.trim())
    && Number.isInteger(r) && r >= 5 && r <= 120
    && destinationComplete(d.failover) && membersValid(d.members);
}

export function RingGroupFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: RingGroupDraft;
  onChange: (patch: Partial<RingGroupDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: RingGroup;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const options = useDestinationOptions(organizationId);
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Front office"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : "Shown on routes and menus that point at the group."} onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Number" required inputMode="numeric" disabled={disabled} value={draft.number} error={errors.number} placeholder="e.g. 2300"
          help="From the numbering plan; dialable from any phone and from IVR menus." onChange={(e) => onChange({ number: e.target.value.replace(/\D/g, "") })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <MemberListEditor label="Members" members={draft.members} extensions={options.extensions} loading={options.loading} onChange={(members) => onChange({ members })} ordered disabled={disabled}
        error={errors.members} emptyText="No members yet: callers go straight to the failover destination."
        help={draft.strategy === "sequential" ? "Rung in this order, each for the ring time below." : "All rung at once; the order only matters if you switch to ringing one after the other."} />
      <div className="form-grid">
        <SelectField label="Strategy" required disabled={disabled} value={draft.strategy} error={errors.strategy}
          options={(Object.keys(RING_STRATEGY_LABELS) as RingGroupStrategy[]).map((k) => ({ value: k, label: RING_STRATEGY_LABELS[k] }))}
          onChange={(e) => onChange({ strategy: e.target.value as RingGroupStrategy })} />
        <TextField label="Ring time (seconds)" type="number" min={5} max={120} required disabled={disabled} value={draft.ring_seconds} error={errors.ring_seconds}
          help={draft.strategy === "sequential" ? "Per member." : "For the whole group."} onChange={(e) => onChange({ ring_seconds: e.target.value })} />
      </div>
      <TextField label="Caller ID prefix" disabled={disabled} value={draft.caller_id_prefix} error={errors.caller_id_prefix} placeholder="e.g. Front: "
        help="Shown on the ringing phones before the caller's name, so users see which group the call came in on." onChange={(e) => onChange({ caller_id_prefix: e.target.value })} />
      <div className="form-grid">
        <SelectField label="Callers hear" required disabled={disabled} value={draft.music} error={errors.music}
          options={[{ value: "ring", label: "Ringing tone" }, { value: "default", label: "Music on hold" }]}
          onChange={(e) => onChange({ music: e.target.value as QueueMusic })} />
        {draft.music === "default" ? (
          <HoldMusicSelect organizationId={organizationId} value={draft.moh_class_id} disabled={disabled} error={errors.moh_class_id}
            onChange={(moh_class_id) => onChange({ moh_class_id })} />
        ) : null}
      </div>
      <Checkbox label="Ring members who are already on a call" description="Off: a member on a call is skipped. On: the phone gets a second call (call waiting)." checked={draft.ring_busy_members} disabled={disabled}
        onChange={(e) => onChange({ ring_busy_members: e.target.checked })} />
      <DestinationPicker label="When nobody answers" idBase="rg-failover" draft={draft.failover} onChange={(failover) => onChange({ failover })} options={options} allowHangup
        current={current?.failover} error={errors.failover} disabled={disabled} exclude={current?.id} />
      <Switch label="Enabled" description="A disabled group is left out of the phone system; routes and menus that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
