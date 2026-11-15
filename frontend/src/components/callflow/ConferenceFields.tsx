// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { HoldMusicSelect } from "@/components/holdmusic/HoldMusicSelect";
import { Checkbox, Switch, TextArea, TextField } from "@/components/ui";
import type { ConferenceRoom, ConferenceRoomInput } from "@/lib/types";

export interface ConferenceDraft {
  name: string;
  number: string;
  description: string;
  /** Empty: unchanged (edit) or none (create); "-": remove the stored PIN. */
  user_pin: string;
  admin_pin: string;
  clear_user_pin: boolean;
  clear_admin_pin: boolean;
  listener_pin: string;
  clear_listener_pin: boolean;
  max_participants: string;
  record: boolean;
  announce_join_leave: boolean;
  music_on_hold_alone: boolean;
  wait_for_admin: boolean;
  moh_class_id: string;
  is_enabled: boolean;
  announce_count: boolean;
  /** Empty: never; "0": on every join. */
  announce_count_above: string;
  /** Minutes; empty: never. */
  end_on_silence_minutes: string;
  /** One number per line. */
  auto_outcall: string;
  /** Empty: never. */
  record_at_members: string;
}

export const EMPTY_CONFERENCE: ConferenceDraft = {
  name: "",
  number: "",
  description: "",
  user_pin: "",
  admin_pin: "",
  clear_user_pin: false,
  clear_admin_pin: false,
  listener_pin: "",
  clear_listener_pin: false,
  max_participants: "0",
  record: false,
  announce_join_leave: true,
  music_on_hold_alone: true,
  wait_for_admin: false,
  moh_class_id: "",
  is_enabled: true,
  announce_count: false,
  announce_count_above: "",
  end_on_silence_minutes: "",
  auto_outcall: "",
  record_at_members: "",
};

export function conferenceDraft(c: ConferenceRoom): ConferenceDraft {
  return {
    ...EMPTY_CONFERENCE,
    name: c.name,
    number: c.number,
    description: c.description ?? "",
    max_participants: String(c.max_participants),
    record: c.record,
    announce_join_leave: c.announce_join_leave,
    music_on_hold_alone: c.music_on_hold_alone,
    wait_for_admin: c.wait_for_admin,
    moh_class_id: c.moh_class_id ?? "",
    is_enabled: c.is_enabled,
    announce_count: c.announce_count,
    announce_count_above: c.announce_count_above == null ? "" : String(c.announce_count_above),
    end_on_silence_minutes: c.end_on_silence_seconds == null ? "" : String(Math.round(c.end_on_silence_seconds / 60)),
    auto_outcall: c.auto_outcall.join("\n"),
    record_at_members: c.record_at_members == null ? "" : String(c.record_at_members),
  };
}

const optionalInt = (v: string): number | null => (v.trim() === "" ? null : Number(v.trim()));
const outcallList = (v: string): string[] => v.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

/** The PATCH body: PINs are sent only when typed or cleared. */
export function conferenceBody(d: ConferenceDraft): ConferenceRoomInput {
  const body: ConferenceRoomInput = {
    name: d.name.trim(),
    number: d.number.trim(),
    description: d.description.trim() || null,
    max_participants: Number(d.max_participants),
    record: d.record,
    announce_join_leave: d.announce_join_leave,
    music_on_hold_alone: d.music_on_hold_alone,
    wait_for_admin: d.wait_for_admin,
    moh_class_id: d.moh_class_id || null,
    is_enabled: d.is_enabled,
    announce_count: d.announce_count,
    announce_count_above: optionalInt(d.announce_count_above),
    end_on_silence_seconds: d.end_on_silence_minutes.trim() === "" ? null : Number(d.end_on_silence_minutes) * 60,
    auto_outcall: outcallList(d.auto_outcall),
    record_at_members: d.record ? null : optionalInt(d.record_at_members),
  };
  if (d.clear_listener_pin) body.listener_pin = null; else if (d.listener_pin.trim()) body.listener_pin = d.listener_pin.trim();
  if (d.clear_user_pin) body.user_pin = null; else if (d.user_pin.trim()) body.user_pin = d.user_pin.trim();
  if (d.clear_admin_pin) body.admin_pin = null; else if (d.admin_pin.trim()) body.admin_pin = d.admin_pin.trim();
  return body;
}

const PIN_RE = /^[0-9]{4,10}$/;

const inRange = (v: string, min: number, max: number) => {
  if (v.trim() === "") return true;
  const n = Number(v.trim());
  return Number.isInteger(n) && n >= min && n <= max;
};

export function conferenceValid(d: ConferenceDraft): boolean {
  const n = Number(d.max_participants);
  const pins = [d.user_pin, d.admin_pin, d.listener_pin].map((p) => p.trim()).filter(Boolean);
  return d.name.trim().length > 0
    && new Set(pins).size === pins.length
    && (!d.listener_pin.trim() || PIN_RE.test(d.listener_pin.trim()))
    && inRange(d.announce_count_above, 0, 500)
    && inRange(d.end_on_silence_minutes, 1, 1440)
    && inRange(d.record_at_members, 2, 500)
    && outcallList(d.auto_outcall).length <= 10
    && outcallList(d.auto_outcall).every((x) => /^\+?[0-9 ().-]{2,30}$/.test(x))
    && /^[0-9]{2,32}$/.test(d.number.trim())
    && Number.isInteger(n) && n >= 0 && n <= 500
    && (!d.user_pin.trim() || PIN_RE.test(d.user_pin.trim()))
    && (!d.admin_pin.trim() || PIN_RE.test(d.admin_pin.trim()))
    && !(d.user_pin.trim() && d.user_pin.trim() === d.admin_pin.trim());
}

export function ConferenceFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: ConferenceDraft;
  onChange: (patch: Partial<ConferenceDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: ConferenceRoom;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const pinHelp = (has: boolean, clear: boolean) => clear ? "The PIN is removed when you save." : has ? "A PIN is set. Type a new one to replace it." : "4 to 10 digits; empty: no PIN.";
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Board room"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : undefined} onChange={(e) => onChange({ name: e.target.value })} />
        <TextField label="Number" required disabled={disabled} value={draft.number} error={errors.number} placeholder="e.g. 2500" inputMode="numeric"
          help="Dialled from any phone of the organization; shares the number space with extensions and groups. A line key with this number lights while the room is in use." onChange={(e) => onChange({ number: e.target.value })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <div className="form-grid">
        <div className="stack stack--xs">
          <TextField label="Participant PIN" type="password" autoComplete="off" inputMode="numeric" disabled={disabled || draft.clear_user_pin} value={draft.user_pin} error={errors.user_pin}
            help={pinHelp(current?.has_user_pin ?? false, draft.clear_user_pin)} onChange={(e) => onChange({ user_pin: e.target.value })} />
          {current?.has_user_pin ? <Checkbox label="Remove the participant PIN" checked={draft.clear_user_pin} disabled={disabled} onChange={(e) => onChange({ clear_user_pin: e.target.checked, user_pin: "" })} /> : null}
        </div>
        <div className="stack stack--xs">
          <TextField label="Administrator PIN" type="password" autoComplete="off" inputMode="numeric" disabled={disabled || draft.clear_admin_pin} value={draft.admin_pin} error={errors.admin_pin}
            help={pinHelp(current?.has_admin_pin ?? false, draft.clear_admin_pin)} onChange={(e) => onChange({ admin_pin: e.target.value })} />
          {current?.has_admin_pin ? <Checkbox label="Remove the administrator PIN" checked={draft.clear_admin_pin} disabled={disabled} onChange={(e) => onChange({ clear_admin_pin: e.target.checked, admin_pin: "" })} /> : null}
        </div>
      </div>
      <div className="form-grid">
        <TextField label="Participant limit" type="number" min={0} max={500} disabled={disabled} value={draft.max_participants} error={errors.max_participants} help="0: no limit." onChange={(e) => onChange({ max_participants: e.target.value })} />
        <HoldMusicSelect organizationId={organizationId} value={draft.moh_class_id} disabled={disabled} error={errors.moh_class_id} label="Hold music while waiting alone"
          help="Sets are managed under Telephony → Hold Music." onChange={(moh_class_id) => onChange({ moh_class_id })} />
      </div>
      <div className="stack stack--xs">
        <Checkbox label="Announce when participants join and leave" checked={draft.announce_join_leave} disabled={disabled} onChange={(e) => onChange({ announce_join_leave: e.target.checked })} />
        <Checkbox label="Play hold music to a participant who is alone" checked={draft.music_on_hold_alone} disabled={disabled} onChange={(e) => onChange({ music_on_hold_alone: e.target.checked })} />
        <Checkbox label="Participants wait until an administrator joins" description="Needs an administrator PIN; the room starts when someone enters it." checked={draft.wait_for_admin} disabled={disabled} onChange={(e) => onChange({ wait_for_admin: e.target.checked })} />
        <Checkbox label="Record the conference" description="Each conference is recorded and listed under Call Recording, marked Conference, with the same access rules and retention as other recordings." checked={draft.record} disabled={disabled} onChange={(e) => onChange({ record: e.target.checked })} />
        <Checkbox label="Tell each caller how many are in the room" checked={draft.announce_count} disabled={disabled} onChange={(e) => onChange({ announce_count: e.target.checked })} />
      </div>
      <div className="form-grid">
        <TextField label="Announce the count to everyone above" type="number" min={0} max={500} disabled={disabled} value={draft.announce_count_above} error={errors.announce_count_above}
          help="When someone joins and more than this many are in the room, everyone hears the count. 0: on every join; empty: never." onChange={(e) => onChange({ announce_count_above: e.target.value })} />
        <TextField label="Start recording at" type="number" min={2} max={500} disabled={disabled || draft.record} value={draft.record ? "" : draft.record_at_members} error={errors.record_at_members}
          help={draft.record ? "The room records every conference." : "Participants; recording starts when this many are in the room. Empty: never."} onChange={(e) => onChange({ record_at_members: e.target.value })} />
      </div>
      <div className="form-grid">
        <TextField label="End after silence (minutes)" type="number" min={1} max={1440} disabled={disabled} value={draft.end_on_silence_minutes} error={errors.end_on_silence_seconds}
          help="Ends the conference for everyone when nobody has spoken for this long. Empty: never." onChange={(e) => onChange({ end_on_silence_minutes: e.target.value })} />
        <div className="stack stack--xs">
          <TextField label="Silent listener PIN" type="password" autoComplete="off" inputMode="numeric" disabled={disabled || draft.clear_listener_pin} value={draft.listener_pin} error={errors.listener_pin}
            help={draft.clear_listener_pin ? "The PIN is removed when you save." : current?.has_listener_pin ? "A PIN is set. Type a new one to replace it." : "Joins muted and unannounced, for someone who only listens. 4 to 10 digits; empty: none."}
            onChange={(e) => onChange({ listener_pin: e.target.value })} />
          {current?.has_listener_pin ? <Checkbox label="Remove the silent listener PIN" checked={draft.clear_listener_pin} disabled={disabled} onChange={(e) => onChange({ clear_listener_pin: e.target.checked, listener_pin: "" })} /> : null}
        </div>
      </div>
      <TextArea label="Call when the conference starts" rows={3} disabled={disabled} value={draft.auto_outcall} error={errors.auto_outcall}
        help="One extension or phone number per line, at most 10. When the first caller joins, Veyra calls each one into the room from the room's number; they join without a PIN. Emergency numbers are refused."
        onChange={(e) => onChange({ auto_outcall: e.target.value })} />
      <Switch label="Enabled" description="A disabled room is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
