// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { SelectField } from "@/components/ui";
import { DESTINATION_LABELS, type DestinationDraft } from "@/lib/routing";
import type { Destination, DestinationType, Extension, IvrMenu, Page, VoicemailBox } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The lists a destination picker chooses from; load once per page and share between pickers. */
export interface DestinationOptions {
  extensions: Extension[];
  boxes: VoicemailBox[];
  menus: IvrMenu[];
  loading: boolean;
}

export function useDestinationOptions(organizationId: string | null | undefined): DestinationOptions {
  const org = organizationId || null;
  const extensions = useApiData<Page<Extension>>(org ? "/extensions" : null, { organization_id: org, limit: 200 });
  const boxes = useApiData<Page<VoicemailBox>>(org ? "/voicemail" : null, { organization_id: org, limit: 200 });
  const menus = useApiData<Page<IvrMenu>>(org ? "/ivr" : null, { organization_id: org, limit: 200 });
  return {
    extensions: extensions.data?.items ?? [],
    boxes: boxes.data?.items ?? [],
    menus: menus.data?.items ?? [],
    loading: extensions.loading || boxes.loading || menus.loading,
  };
}

const extLabel = (x: Extension) => `${x.number} — ${x.display_name}${x.is_enabled ? "" : " (disabled)"}`;

/**
 * Kind and target of a call destination (docs/VOICEMAIL_IVR.md §6). The voicemail
 * kind lists only extensions that have a box; `exclude` hides a menu from the IVR
 * list (a menu does not point at itself through a key).
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
  const kinds: DestinationType[] = allowHangup ? ["extension", "voicemail", "ivr", "hangup"] : ["extension", "voicemail", "ivr"];
  const withCurrent = (opts: { value: string; label: string }[], value: string, fallback: string) =>
    value && !opts.some((o) => o.value === value) ? [...opts, { value, label: current?.label ?? fallback }] : opts;
  let targetField: React.ReactNode = null;
  if (draft.type === "extension") {
    const opts = options.extensions.map((x) => ({ value: x.id, label: extLabel(x) }));
    targetField = (
      <SelectField id={idBase ? `${idBase}-target` : undefined} label={<span className="sr-only">{label}: extension</span>} required={required} disabled={disabled} value={draft.extension_id} error={error}
        placeholder={options.loading ? "Loading…" : "Choose an extension"} options={withCurrent(opts, draft.extension_id, "Deleted extension")}
        onChange={(e) => onChange({ ...draft, extension_id: e.target.value })} />
    );
  } else if (draft.type === "voicemail") {
    const opts = options.boxes.map((b) => ({ value: b.extension_id, label: `${b.extension_number} — ${b.extension_name}${b.is_enabled ? "" : " (box disabled)"}` }));
    targetField = (
      <SelectField id={idBase ? `${idBase}-target` : undefined} label={<span className="sr-only">{label}: voicemail box</span>} required={required} disabled={disabled} value={draft.extension_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a voicemail box" : "No voicemail boxes in this organization"}
        options={withCurrent(opts, draft.extension_id, "Extension without a box")}
        help={opts.length === 0 && !options.loading ? "Create a voicemail box on an extension first (Telephony → Voicemail)." : undefined}
        onChange={(e) => onChange({ ...draft, extension_id: e.target.value })} />
    );
  } else if (draft.type === "ivr") {
    const opts = options.menus.filter((m) => m.id !== exclude).map((m) => ({ value: m.id, label: m.is_enabled ? m.name : `${m.name} (disabled)` }));
    targetField = (
      <SelectField id={idBase ? `${idBase}-target` : undefined} label={<span className="sr-only">{label}: IVR menu</span>} required={required} disabled={disabled} value={draft.ivr_id} error={error}
        placeholder={options.loading ? "Loading…" : opts.length ? "Choose a menu" : "No IVR menus in this organization"}
        options={withCurrent(opts, draft.ivr_id, "Deleted menu")}
        onChange={(e) => onChange({ ...draft, ivr_id: e.target.value })} />
    );
  }
  return (
    <div className="form-grid">
      <SelectField id={idBase ? `${idBase}-type` : undefined} label={label} required={required} disabled={disabled} value={draft.type}
        options={kinds.map((k) => ({ value: k, label: DESTINATION_LABELS[k] }))}
        help={current?.missing ? "The saved target no longer exists or is disabled; choose a new one." : undefined}
        onChange={(e) => onChange({ type: e.target.value as DestinationType, extension_id: "", ivr_id: "" })} />
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
