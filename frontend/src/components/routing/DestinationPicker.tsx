// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { SelectField } from "@/components/ui";
import { DESTINATION_LABELS, emptyDestination, type DestinationDraft } from "@/lib/routing";
import type { Announcement, CallQueue, ConferenceRoom, Destination, DestinationType, Extension, IvrMenu, Page, RingGroup, VoicemailBox } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The lists a destination picker chooses from; load once per page and share between pickers. */
export interface DestinationOptions {
  extensions: Extension[];
  boxes: VoicemailBox[];
  menus: IvrMenu[];
  ringGroups: RingGroup[];
  queues: CallQueue[];
  announcements: Announcement[];
  conferences: ConferenceRoom[];
  loading: boolean;
}

export function useDestinationOptions(organizationId: string | null | undefined): DestinationOptions {
  const org = organizationId || null;
  const extensions = useApiData<Page<Extension>>(org ? "/extensions" : null, { organization_id: org, limit: 200 });
  const boxes = useApiData<Page<VoicemailBox>>(org ? "/voicemail" : null, { organization_id: org, limit: 200 });
  const menus = useApiData<Page<IvrMenu>>(org ? "/ivr" : null, { organization_id: org, limit: 200 });
  const ringGroups = useApiData<Page<RingGroup>>(org ? "/ring-groups" : null, { organization_id: org, limit: 200 });
  const queues = useApiData<Page<CallQueue>>(org ? "/queues" : null, { organization_id: org, limit: 200 });
  const announcements = useApiData<Page<Announcement>>(org ? "/announcements" : null, { organization_id: org, limit: 200 });
  const conferences = useApiData<Page<ConferenceRoom>>(org ? "/conferences" : null, { organization_id: org, limit: 200 });
  return {
    extensions: extensions.data?.items ?? [],
    boxes: boxes.data?.items ?? [],
    menus: menus.data?.items ?? [],
    ringGroups: ringGroups.data?.items ?? [],
    queues: queues.data?.items ?? [],
    announcements: announcements.data?.items ?? [],
    conferences: conferences.data?.items ?? [],
    loading: extensions.loading || boxes.loading || menus.loading || ringGroups.loading || queues.loading || announcements.loading || conferences.loading,
  };
}

const extLabel = (x: Extension) => `${x.number} — ${x.display_name}${x.is_enabled ? "" : " (disabled)"}`;
const groupLabel = (g: { number: string; name: string; is_enabled: boolean }) => `${g.number} — ${g.name}${g.is_enabled ? "" : " (disabled)"}`;

/**
 * Kind and target of a call destination (docs/VOICEMAIL_IVR.md §6, RING_GROUPS_QUEUES.md §5).
 * The voicemail kind lists only extensions that have a box; `exclude` hides the object
 * being edited from its own kind's list (a menu, group or queue does not point at itself).
 */
export function DestinationPicker({ label, draft, onChange, options, current, error, disabled, allowHangup = false, required = true, exclude, idBase }: {
  label: string;
  draft: DestinationDraft;
  onChange: (next: DestinationDraft) => void;
  options: DestinationOptions;
  /** The saved destination, so the name shows even when the target is gone or lists cannot load. */
  current?: Destination | null;
  error?: string;
  disabled?: boolean;
  allowHangup?: boolean;
  required?: boolean;
  exclude?: string;
  idBase?: string;
}) {
  const kinds: DestinationType[] = ["extension", "voicemail", "voicemail_box", "ivr", "ring_group", "queue", "announcement", "conference", "directory", ...(allowHangup ? ["hangup" as const] : [])];
  const withCurrent = (opts: { value: string; label: string }[], value: string, fallback: string) =>
    value && !opts.some((o) => o.value === value) ? [...opts, { value, label: current?.label ?? fallback }] : opts;
  const targetId = idBase ? `${idBase}-target` : undefined;
  const srLabel = (what: string) => <span className="sr-only">{label}: {what}</span>;
  let targetField: React.ReactNode = null;
  if (draft.type === "extension") {
    const opts = options.extensions.map((x) => ({ value: x.id, label: extLabel(x) }));
    targetField = (
      <SelectField id={targetId} label={srLabel("extension")} required={required} disabled={disabled} value={draft.extension_id} error={error}
        placeholder={options.loading ? "Loading…" : "Choose an extension"} options={withCurrent(opts, draft.extension_id, "Deleted extension")}
        onChange={(e) => onChange({ ...draft, extension_id: e.target.value })} />
    );
  } else if (draft.type === "voicemail") {
    const opts = options.boxes.filter((b) => !b.shared && b.extension_id).map((b) => ({ value: b.extension_id ?? "", label: `${b.extension_number} — ${b.extension_name}${b.is_enabled ? "" : " (box disabled)"}` }));
    targetField = (
      <SelectField id={targetId} label={srLabel("voicemail box")} required={required} disabled={disabled} value={draft.extension_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a voicemail box" : "No voicemail boxes in this organization"}
        options={withCurrent(opts, draft.extension_id, "Extension without a box")}
        help={opts.length === 0 && !options.loading ? "Create a voicemail box on an extension first (Telephony → Voicemail)." : undefined}
        onChange={(e) => onChange({ ...draft, extension_id: e.target.value })} />
    );
  } else if (draft.type === "voicemail_box") {
    const opts = options.boxes.filter((b) => b.shared).map((b) => ({ value: b.id, label: `${b.number} — ${b.name}${b.is_enabled ? "" : " (disabled)"}` }));
    targetField = (
      <SelectField id={targetId} label={srLabel("shared inbox")} required={required} disabled={disabled} value={draft.voicemail_box_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a shared inbox" : "No shared inboxes in this organization"}
        options={withCurrent(opts, draft.voicemail_box_id, "Deleted shared inbox")}
        help={opts.length === 0 && !options.loading ? "Create one under Telephony → Voicemail (New shared inbox)." : undefined}
        onChange={(e) => onChange({ ...draft, voicemail_box_id: e.target.value })} />
    );
  } else if (draft.type === "ivr") {
    const opts = options.menus.filter((m) => m.id !== exclude).map((m) => ({ value: m.id, label: m.is_enabled ? m.name : `${m.name} (disabled)` }));
    targetField = (
      <SelectField id={targetId} label={srLabel("IVR menu")} required={required} disabled={disabled} value={draft.ivr_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a menu" : "No IVR menus in this organization"}
        options={withCurrent(opts, draft.ivr_id, "Deleted menu")}
        onChange={(e) => onChange({ ...draft, ivr_id: e.target.value })} />
    );
  } else if (draft.type === "ring_group") {
    const opts = options.ringGroups.filter((g) => g.id !== exclude).map((g) => ({ value: g.id, label: groupLabel(g) }));
    targetField = (
      <SelectField id={targetId} label={srLabel("ring group")} required={required} disabled={disabled} value={draft.ring_group_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a ring group" : "No ring groups in this organization"}
        options={withCurrent(opts, draft.ring_group_id, "Deleted ring group")}
        help={opts.length === 0 && !options.loading ? "Create one under Telephony → Ring Groups." : undefined}
        onChange={(e) => onChange({ ...draft, ring_group_id: e.target.value })} />
    );
  } else if (draft.type === "queue") {
    const opts = options.queues.filter((q) => q.id !== exclude).map((q) => ({ value: q.id, label: groupLabel(q) }));
    targetField = (
      <SelectField id={targetId} label={srLabel("call queue")} required={required} disabled={disabled} value={draft.queue_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a queue" : "No call queues in this organization"}
        options={withCurrent(opts, draft.queue_id, "Deleted queue")}
        help={opts.length === 0 && !options.loading ? "Create one under Telephony → Call Queues." : undefined}
        onChange={(e) => onChange({ ...draft, queue_id: e.target.value })} />
    );
  } else if (draft.type === "announcement") {
    const opts = options.announcements.filter((a) => a.id !== exclude).map((a) => ({ value: a.id, label: a.is_enabled ? a.name : `${a.name} (disabled)` }));
    targetField = (
      <SelectField id={targetId} label={srLabel("announcement")} required={required} disabled={disabled} value={draft.announcement_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose an announcement" : "No announcements in this organization"}
        options={withCurrent(opts, draft.announcement_id, "Deleted announcement")}
        help={opts.length === 0 && !options.loading ? "Create one under Telephony → Announcements." : undefined}
        onChange={(e) => onChange({ ...draft, announcement_id: e.target.value })} />
    );
  } else if (draft.type === "conference") {
    const opts = options.conferences.map((c) => ({ value: c.id, label: groupLabel(c) }));
    targetField = (
      <SelectField id={targetId} label={srLabel("conference room")} required={required} disabled={disabled} value={draft.conference_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a conference room" : "No conference rooms in this organization"}
        options={withCurrent(opts, draft.conference_id, "Deleted conference room")}
        help={opts.length === 0 && !options.loading ? "Create one under Telephony → Conference Rooms." : undefined}
        onChange={(e) => onChange({ ...draft, conference_id: e.target.value })} />
    );
  } else if (draft.type === "directory") {
    targetField = <p className="field__help" style={{ margin: 0 }}>Callers spell a name on the keypad and reach the matching extension (extensions with a voicemail box are listed).</p>;
  }
  return (
    <div className="form-grid">
      <SelectField id={idBase ? `${idBase}-type` : undefined} label={label} required={required} disabled={disabled} value={draft.type}
        options={kinds.map((k) => ({ value: k, label: DESTINATION_LABELS[k] }))}
        help={current?.missing ? "The saved target no longer exists or is disabled; choose a new one." : undefined}
        onChange={(e) => onChange(emptyDestination(e.target.value as DestinationType))} />
      {targetField}
    </div>
  );
}

/** Read-only rendering of a destination with a warning when the target is gone. */
export function DestinationLabel({ d }: { d: Destination | null | undefined }) {
  if (!d) return <span className="subtle">—</span>;
  if (d.missing || !d.label) return <span className="badge badge--danger">{d.label ?? "No destination"}</span>;
  return <span>{d.label}</span>;
}
