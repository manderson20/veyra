// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Checkbox, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, IVR_DIGITS, type DestinationDraft } from "@/lib/routing";
import type { Announcement, AnnouncementInput, Page, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface AnnouncementDraft {
  name: string;
  description: string;
  prompt_id: string;
  allow_skip: boolean;
  repeat_key: string;
  destination: DestinationDraft;
  is_enabled: boolean;
}

export const EMPTY_ANNOUNCEMENT: AnnouncementDraft = {
  name: "",
  description: "",
  prompt_id: "",
  allow_skip: false,
  repeat_key: "",
  destination: HANGUP,
  is_enabled: true,
};

export function announcementDraft(a: Announcement): AnnouncementDraft {
  return {
    name: a.name,
    description: a.description ?? "",
    prompt_id: a.prompt_id ?? "",
    allow_skip: a.allow_skip,
    repeat_key: a.repeat_key ?? "",
    destination: destinationDraft(a.destination, HANGUP),
    is_enabled: a.is_enabled,
  };
}

export function announcementBody(d: AnnouncementDraft): AnnouncementInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    prompt_id: d.prompt_id || null,
    allow_skip: d.allow_skip,
    repeat_key: d.repeat_key || null,
    destination: destinationBody(d.destination),
    is_enabled: d.is_enabled,
  };
}

export function announcementValid(d: AnnouncementDraft): boolean {
  return d.name.trim().length > 0 && destinationComplete(d.destination);
}

export function AnnouncementFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: AnnouncementDraft;
  onChange: (patch: Partial<AnnouncementDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: Announcement;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const prompts = useApiData<Page<Prompt>>(organizationId ? "/prompts" : null, { organization_id: organizationId, limit: 200 });
  const options = useDestinationOptions(organizationId);
  let promptOptions = (prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }));
  if (draft.prompt_id && !promptOptions.some((o) => o.value === draft.prompt_id)) {
    promptOptions = [...promptOptions, { value: draft.prompt_id, label: current?.prompt_name ?? "Deleted prompt" }];
  }
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Closed for the holiday"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : "Also names the announcement for routes and menus."} onChange={(e) => onChange({ name: e.target.value })} />
        <SelectField label="Recording to play" required disabled={disabled} value={draft.prompt_id} error={errors.prompt_id}
          placeholder={prompts.loading ? "Loading prompts…" : promptOptions.length ? "Choose a recording" : "No recordings yet (Telephony → Audio)"}
          help="Played once; then the call continues below." options={promptOptions} onChange={(e) => onChange({ prompt_id: e.target.value })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <div className="form-grid">
        <Checkbox label="Callers may press any key to skip the recording" checked={draft.allow_skip} disabled={disabled} onChange={(e) => onChange({ allow_skip: e.target.checked })} />
        <SelectField label="Key that replays the recording" disabled={disabled} value={draft.repeat_key} error={errors.repeat_key} placeholder="None"
          options={IVR_DIGITS.map((k) => ({ value: k, label: k }))} onChange={(e) => onChange({ repeat_key: e.target.value })} />
      </div>
      <DestinationPicker label="Then send the call to" idBase="ann-dest" draft={draft.destination} onChange={(destination) => onChange({ destination })} options={options} allowHangup
        current={current?.destination} error={errors.destination} disabled={disabled} exclude={current?.id} />
      <Switch label="Enabled" description="A disabled announcement is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
