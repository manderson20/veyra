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
  /** Unanswered calls in a row before a member is skipped; empty: never (issue #166). */
  skip_after_misses: string;
  skip_minutes: string;
  /** One outside number per line. */
  external_members: string;
  confirm_external: boolean;
  caller_id_prefix: string;
  answered_elsewhere: boolean;
  ignore_forwards: boolean;
  alert_info: string;
  music: QueueMusic;
  moh_class_id: string;
  failover: DestinationDraft;
  members: MemberDraft[];
  /** Extension id -> ring time in seconds as typed; empty: the group's (issue #166). */
  member_rings: Record<string, string>;
  is_enabled: boolean;
}

export const EMPTY_RING_GROUP: RingGroupDraft = {
  name: "",
  number: "",
  description: "",
  strategy: "ringall",
  ring_seconds: "20",
  ring_busy_members: false,
  skip_after_misses: "",
  skip_minutes: "15",
  external_members: "",
  confirm_external: false,
  caller_id_prefix: "",
  answered_elsewhere: false,
  ignore_forwards: false,
  alert_info: "",
  music: "ring",
  moh_class_id: "",
  failover: HANGUP,
  members: [],
  member_rings: {},
  is_enabled: true,
};

export const RING_STRATEGY_LABELS: Record<RingGroupStrategy, string> = {
  ringall: "Ring all members at once",
  sequential: "Ring members one after the other",
  circular: "One at a time, starting after the last who answered",
  roundrobin: "One at a time, each call starting one member later",
  longest_idle: "One at a time, longest without a call first",
};

/** Strategies that ring one member at a time, where a member's own ring time applies. */
const ONE_AT_A_TIME: RingGroupStrategy[] = ["sequential", "circular", "roundrobin", "longest_idle"];

export function ringGroupDraft(g: RingGroup): RingGroupDraft {
  return {
    name: g.name,
    number: g.number,
    description: g.description ?? "",
    strategy: g.strategy,
    ring_seconds: String(g.ring_seconds),
    ring_busy_members: g.ring_busy_members,
    skip_after_misses: g.skip_after_misses ? String(g.skip_after_misses) : "",
    skip_minutes: String(g.skip_minutes ?? 15),
    external_members: (g.external_members ?? []).join("\n"),
    confirm_external: g.confirm_external ?? false,
    caller_id_prefix: g.caller_id_prefix ?? "",
    answered_elsewhere: g.answered_elsewhere ?? false,
    ignore_forwards: g.ignore_forwards ?? false,
    alert_info: g.alert_info ?? "",
    music: g.music ?? "ring",
    moh_class_id: g.moh_class_id ?? "",
    failover: destinationDraft(g.failover, HANGUP),
    members: membersFromIds(g.members),
    member_rings: Object.fromEntries(g.members.filter((m) => m.ring_seconds).map((m) => [m.extension_id, String(m.ring_seconds)])),
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
    skip_after_misses: ONE_AT_A_TIME.includes(d.strategy) && d.skip_after_misses.trim() ? Number(d.skip_after_misses) : null,
    skip_minutes: Number(d.skip_minutes) || 15,
    external_members: d.external_members.split("\n").map((n) => n.trim()).filter(Boolean),
    confirm_external: d.confirm_external,
    caller_id_prefix: d.caller_id_prefix.trim() || null,
    answered_elsewhere: d.answered_elsewhere,
    ignore_forwards: d.ignore_forwards,
    alert_info: d.alert_info.trim() || null,
    music: d.music,
    moh_class_id: d.music === "default" ? d.moh_class_id || null : null,
    failover: destinationBody(d.failover),
    members: d.members.map((m) => m.extension_id),
    member_ring_seconds: Object.fromEntries(d.members.filter((m) => (d.member_rings[m.extension_id] ?? "").trim()).map((m) => [m.extension_id, Number(d.member_rings[m.extension_id])])),
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
        help={draft.strategy === "ringall" ? "All rung at once; the order only matters if you switch to ringing one at a time." : "Rung one at a time in this order (or starting further down the list, by the strategy), each for its ring time."} />
      {ONE_AT_A_TIME.includes(draft.strategy) && draft.members.length ? (
        <details>
          <summary>Ring time per member</summary>
          <div className="form-grid" style={{ marginTop: 8 }}>
            {draft.members.map((m) => {
              const ext = options.extensions.find((e) => e.id === m.extension_id);
              return (
                <TextField key={m.extension_id} label={ext ? `${ext.number} ${ext.display_name}` : "Member"} type="number" min={5} max={120} disabled={disabled}
                  value={draft.member_rings[m.extension_id] ?? ""} placeholder={`${draft.ring_seconds || 20} (the group's)`}
                  onChange={(e) => onChange({ member_rings: { ...draft.member_rings, [m.extension_id]: e.target.value } })} />
              );
            })}
          </div>
        </details>
      ) : null}
      <TextArea label="Outside numbers" rows={2} value={draft.external_members} disabled={disabled} error={errors.external_members} placeholder="5735550100" spellCheck={false}
        help="Mobile or other outside numbers rung with the members, one per line; they leave through the organization’s outbound routes." onChange={(e) => onChange({ external_members: e.target.value })} />
      <Checkbox label="Outside numbers must press 1 to accept" description="Keeps a mobile’s voicemail from swallowing the call." checked={draft.confirm_external} disabled={disabled} onChange={(e) => onChange({ confirm_external: e.target.checked })} />
      <div className="form-grid">
        <SelectField label="Strategy" required disabled={disabled} value={draft.strategy} error={errors.strategy}
          options={(Object.keys(RING_STRATEGY_LABELS) as RingGroupStrategy[]).map((k) => ({ value: k, label: RING_STRATEGY_LABELS[k] }))}
          onChange={(e) => onChange({ strategy: e.target.value as RingGroupStrategy })} />
        <TextField label="Ring time (seconds)" type="number" min={5} max={120} required disabled={disabled} value={draft.ring_seconds} error={errors.ring_seconds}
          help={draft.strategy === "ringall" ? "For the whole group." : "Per member, unless a member has its own below."} onChange={(e) => onChange({ ring_seconds: e.target.value })} />
      </div>
      <TextField label="Caller ID prefix" disabled={disabled} value={draft.caller_id_prefix} error={errors.caller_id_prefix} placeholder="e.g. Front: "
        help="Shown on the ringing phones before the caller's name, so users see which group the call came in on." onChange={(e) => onChange({ caller_id_prefix: e.target.value })} />
      <TextField label="Ring tone (Alert-Info)" disabled={disabled} value={draft.alert_info} error={errors.alert_info} placeholder="e.g. info=ring2" spellCheck={false}
        help="Sent to the ringing phones so this group can ring differently. The value depends on the phone's brand and settings." onChange={(e) => onChange({ alert_info: e.target.value })} />
      <Checkbox label="Show “answered elsewhere” on the other phones" description="Phones that stop ringing because someone answered don't list it as a missed call, if they support this." checked={draft.answered_elsewhere} disabled={disabled} onChange={(e) => onChange({ answered_elsewhere: e.target.checked })} />
      <Checkbox label="Ignore forwarding set on a member's phone" description="A call forward set on the phone itself is not followed. Forwarding set in Veyra is not affected." checked={draft.ignore_forwards} disabled={disabled} onChange={(e) => onChange({ ignore_forwards: e.target.checked })} />
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
      {ONE_AT_A_TIME.includes(draft.strategy) ? (
        <div className="form-grid">
          <TextField label="Skip a member after unanswered calls" type="number" min={1} max={10} disabled={disabled} value={draft.skip_after_misses} error={errors.skip_after_misses} placeholder="Never"
            help="A member who let this many calls in a row go unanswered is passed over for a while; answering a call clears it. If every member would be skipped, none is." onChange={(e) => onChange({ skip_after_misses: e.target.value })} />
          {draft.skip_after_misses.trim() ? (
            <TextField label="Skip for (minutes)" type="number" min={1} max={1440} disabled={disabled} value={draft.skip_minutes} error={errors.skip_minutes}
              help="Counted from the last unanswered call." onChange={(e) => onChange({ skip_minutes: e.target.value })} />
          ) : null}
        </div>
      ) : null}
      <DestinationPicker label="When nobody answers" idBase="rg-failover" draft={draft.failover} onChange={(failover) => onChange({ failover })} options={options} allowHangup
        current={current?.failover} error={errors.failover} disabled={disabled} exclude={current?.id} />
      <Switch label="Enabled" description="A disabled group is left out of the phone system; routes and menus that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
