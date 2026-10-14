// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { HoldMusicSelect } from "@/components/holdmusic/HoldMusicSelect";
import { MemberListEditor, membersFromIds, membersValid, type MemberDraft } from "@/components/groups/MemberListEditor";
import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Checkbox, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, type DestinationDraft } from "@/lib/routing";
import type { CallQueue, Page, Prompt, QueueInput, QueueMusic, QueueStrategy } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface QueueDraft {
  name: string;
  number: string;
  description: string;
  strategy: QueueStrategy;
  member_timeout: string;
  retry_seconds: string;
  wrapup_seconds: string;
  max_wait_seconds: string;
  max_callers: string;
  join_when_empty: boolean;
  announce_position: boolean;
  announce_frequency: string;
  announcement_prompt_id: string;
  periodic_prompt_id: string;
  periodic_seconds: string;
  music: QueueMusic;
  moh_class_id: string;
  failover: DestinationDraft;
  members: MemberDraft[];
  is_enabled: boolean;
}

export const EMPTY_QUEUE: QueueDraft = {
  name: "",
  number: "",
  description: "",
  strategy: "ringall",
  member_timeout: "15",
  retry_seconds: "5",
  wrapup_seconds: "0",
  max_wait_seconds: "300",
  max_callers: "0",
  join_when_empty: false,
  announce_position: false,
  announce_frequency: "60",
  announcement_prompt_id: "",
  periodic_prompt_id: "",
  periodic_seconds: "60",
  music: "default",
  moh_class_id: "",
  failover: HANGUP,
  members: [],
  is_enabled: true,
};

export const QUEUE_STRATEGY_LABELS: Record<QueueStrategy, string> = {
  ringall: "Ring all available agents",
  rrmemory: "Round robin (continues where it left off)",
  leastrecent: "Agent idle the longest",
  fewestcalls: "Agent with the fewest completed calls",
  random: "Random agent",
  linear: "Agents in the listed order",
};

export const QUEUE_MUSIC_LABELS: Record<QueueMusic, string> = {
  default: "Music on hold",
  ring: "Ringing tone",
};

export function queueDraft(q: CallQueue): QueueDraft {
  return {
    name: q.name,
    number: q.number,
    description: q.description ?? "",
    strategy: q.strategy,
    member_timeout: String(q.member_timeout),
    retry_seconds: String(q.retry_seconds),
    wrapup_seconds: String(q.wrapup_seconds),
    max_wait_seconds: String(q.max_wait_seconds),
    max_callers: String(q.max_callers),
    join_when_empty: q.join_when_empty,
    announce_position: q.announce_position,
    announce_frequency: String(q.announce_frequency),
    announcement_prompt_id: q.announcement_prompt_id ?? "",
    periodic_prompt_id: q.periodic_prompt_id ?? "",
    periodic_seconds: String(q.periodic_seconds),
    music: q.music,
    moh_class_id: q.moh_class_id ?? "",
    failover: destinationDraft(q.failover, HANGUP),
    members: membersFromIds(q.members),
    is_enabled: q.is_enabled,
  };
}

export function queueBody(d: QueueDraft): QueueInput {
  return {
    name: d.name.trim(),
    number: d.number.trim(),
    description: d.description.trim() || null,
    strategy: d.strategy,
    member_timeout: Number(d.member_timeout),
    retry_seconds: Number(d.retry_seconds),
    wrapup_seconds: Number(d.wrapup_seconds),
    max_wait_seconds: Number(d.max_wait_seconds),
    max_callers: Number(d.max_callers),
    join_when_empty: d.join_when_empty,
    announce_position: d.announce_position,
    announce_frequency: Number(d.announce_frequency),
    announcement_prompt_id: d.announcement_prompt_id || null,
    periodic_prompt_id: d.periodic_prompt_id || null,
    periodic_seconds: Number(d.periodic_seconds),
    music: d.music,
    moh_class_id: d.music === "default" ? d.moh_class_id || null : null,
    failover: destinationBody(d.failover),
    members: d.members.map((m) => ({ extension_id: m.extension_id, penalty: Number(m.penalty) })),
    is_enabled: d.is_enabled,
  };
}

const within = (v: string, lo: number, hi: number) => {
  const n = Number(v);
  return Number.isInteger(n) && n >= lo && n <= hi;
};

export function queueValid(d: QueueDraft): boolean {
  const wait = Number(d.max_wait_seconds);
  return d.name.trim().length > 0 && /^[0-9]+$/.test(d.number.trim())
    && within(d.member_timeout, 5, 60) && within(d.retry_seconds, 1, 30) && within(d.wrapup_seconds, 0, 600)
    && Number.isInteger(wait) && (wait === 0 || (wait >= 30 && wait <= 3600))
    && within(d.max_callers, 0, 100) && within(d.announce_frequency, 15, 600) && within(d.periodic_seconds, 15, 600)
    && destinationComplete(d.failover) && membersValid(d.members, true);
}

export function QueueFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: QueueDraft;
  onChange: (patch: Partial<QueueDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: CallQueue;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const options = useDestinationOptions(organizationId);
  const prompts = useApiData<Page<Prompt>>(organizationId ? "/prompts" : null, { organization_id: organizationId, limit: 200 });
  const promptOptions = (prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }));
  const withCurrent = (value: string, label: string | null) =>
    value && !promptOptions.some((o) => o.value === value) ? [...promptOptions, { value, label: label ?? "Deleted prompt" }] : promptOptions;
  const placeholder = prompts.loading ? "Loading prompts…" : promptOptions.length ? "None" : "None (no prompts yet: Telephony → Prompts)";
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Support"
          help={current ? <>Queue <span className="mono">{current.queue_name}</span> in the phone system stays the same.</> : "Shown on routes and menus that point at the queue."} onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Number" required inputMode="numeric" disabled={disabled} value={draft.number} error={errors.number} placeholder="e.g. 2400"
          help="From the numbering plan; dialable from any phone and from IVR menus." onChange={(e) => onChange({ number: e.target.value.replace(/\D/g, "") })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <MemberListEditor label="Agents" members={draft.members} extensions={options.extensions} loading={options.loading} onChange={(members) => onChange({ members })} penalties ordered={draft.strategy === "linear"} disabled={disabled}
        error={errors.members} emptyText="No agents yet: callers go straight to the failover destination."
        help="Penalty 0–9: agents with a higher penalty only ring when every agent with a lower one is busy or absent." />
      <div className="form-grid">
        <SelectField label="Strategy" required disabled={disabled} value={draft.strategy} error={errors.strategy}
          options={(Object.keys(QUEUE_STRATEGY_LABELS) as QueueStrategy[]).map((k) => ({ value: k, label: QUEUE_STRATEGY_LABELS[k] }))}
          onChange={(e) => onChange({ strategy: e.target.value as QueueStrategy })} />
        <SelectField label="Callers hear" required disabled={disabled} value={draft.music} error={errors.music}
          options={(Object.keys(QUEUE_MUSIC_LABELS) as QueueMusic[]).map((k) => ({ value: k, label: QUEUE_MUSIC_LABELS[k] }))}
          onChange={(e) => onChange({ music: e.target.value as QueueMusic })} />
      </div>
      {draft.music === "default" ? (
        <HoldMusicSelect organizationId={organizationId} value={draft.moh_class_id} disabled={disabled} error={errors.moh_class_id}
          help="Sets are managed under Telephony → Hold Music." onChange={(moh_class_id) => onChange({ moh_class_id })} />
      ) : null}
      <div className="form-grid">
        <TextField label="Agent ring time (seconds)" type="number" min={5} max={60} required disabled={disabled} value={draft.member_timeout} error={errors.member_timeout}
          help="Each attempt to reach an agent." onChange={(e) => onChange({ member_timeout: e.target.value })} />
        <TextField label="Pause between attempts (seconds)" type="number" min={1} max={30} required disabled={disabled} value={draft.retry_seconds} error={errors.retry_seconds}
          onChange={(e) => onChange({ retry_seconds: e.target.value })} />
        <TextField label="Agent rest after a call (seconds)" type="number" min={0} max={600} required disabled={disabled} value={draft.wrapup_seconds} error={errors.wrapup_seconds}
          onChange={(e) => onChange({ wrapup_seconds: e.target.value })} />
        <TextField label="Maximum wait (seconds)" type="number" min={0} max={3600} required disabled={disabled} value={draft.max_wait_seconds} error={errors.max_wait_seconds}
          help="0 = unlimited; otherwise 30–3600, then the failover." onChange={(e) => onChange({ max_wait_seconds: e.target.value })} />
        <TextField label="Maximum callers waiting" type="number" min={0} max={100} required disabled={disabled} value={draft.max_callers} error={errors.max_callers}
          help="0 = unlimited; a caller beyond it goes to the failover." onChange={(e) => onChange({ max_callers: e.target.value })} />
      </div>
      <Checkbox label="Let callers wait when no agent is available" description="Off: a caller whose agents are all unavailable goes straight to the failover." checked={draft.join_when_empty} disabled={disabled}
        onChange={(e) => onChange({ join_when_empty: e.target.checked })} />
      <div className="form-grid">
        <SelectField label="Announcement on joining" disabled={disabled} value={draft.announcement_prompt_id} error={errors.announcement_prompt_id} placeholder={placeholder}
          help="Played once before the caller starts waiting." options={withCurrent(draft.announcement_prompt_id, current?.announcement_prompt_name ?? null)} onChange={(e) => onChange({ announcement_prompt_id: e.target.value })} />
        <SelectField label="Announcement while waiting" disabled={disabled} value={draft.periodic_prompt_id} error={errors.periodic_prompt_id} placeholder={placeholder}
          options={withCurrent(draft.periodic_prompt_id, current?.periodic_prompt_name ?? null)} onChange={(e) => onChange({ periodic_prompt_id: e.target.value })} />
        <TextField label="Repeat every (seconds)" type="number" min={15} max={600} required disabled={disabled || !draft.periodic_prompt_id} value={draft.periodic_seconds} error={errors.periodic_seconds}
          onChange={(e) => onChange({ periodic_seconds: e.target.value })} />
      </div>
      <Checkbox label="Announce the caller's position in line" checked={draft.announce_position} disabled={disabled} onChange={(e) => onChange({ announce_position: e.target.checked })} />
      {draft.announce_position ? (
        <TextField label="Announce position every (seconds)" type="number" min={15} max={600} required disabled={disabled} value={draft.announce_frequency} error={errors.announce_frequency}
          onChange={(e) => onChange({ announce_frequency: e.target.value })} />
      ) : null}
      <DestinationPicker label="When the caller is not connected" idBase="q-failover" draft={draft.failover} onChange={(failover) => onChange({ failover })} options={options} allowHangup
        current={current?.failover} error={errors.failover} disabled={disabled} exclude={current?.id} />
      <Switch label="Enabled" description="A disabled queue is left out of the phone system; routes and menus that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
