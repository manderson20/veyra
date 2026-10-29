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
  max_participants: string;
  record: boolean;
  announce_join_leave: boolean;
  music_on_hold_alone: boolean;
  wait_for_admin: boolean;
  moh_class_id: string;
  is_enabled: boolean;
}

export const EMPTY_CONFERENCE: ConferenceDraft = {
  name: "",
  number: "",
  description: "",
  user_pin: "",
  admin_pin: "",
  clear_user_pin: false,
  clear_admin_pin: false,
  max_participants: "0",
  record: false,
  announce_join_leave: true,
  music_on_hold_alone: true,
  wait_for_admin: false,
  moh_class_id: "",
  is_enabled: true,
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
  };
}

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
  };
  if (d.clear_user_pin) body.user_pin = null; else if (d.user_pin.trim()) body.user_pin = d.user_pin.trim();
  if (d.clear_admin_pin) body.admin_pin = null; else if (d.admin_pin.trim()) body.admin_pin = d.admin_pin.trim();
  return body;
}

const PIN_RE = /^[0-9]{4,10}$/;

export function conferenceValid(d: ConferenceDraft): boolean {
  const n = Number(d.max_participants);
  return d.name.trim().length > 0
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
      </div>
      <Switch label="Enabled" description="A disabled room is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
