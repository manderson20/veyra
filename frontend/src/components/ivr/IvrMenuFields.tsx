// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Button, Checkbox, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, EMPTY_DESTINATION, HANGUP, IVR_DIGITS, type DestinationDraft } from "@/lib/routing";
import type { IvrMenu, IvrMenuInput, Page, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface IvrMenuDraft {
  name: string;
  description: string;
  prompt_id: string;
  invalid_prompt_id: string;
  timeout_seconds: string;
  max_retries: string;
  allow_direct_dial: boolean;
  timeout_destination: DestinationDraft;
  invalid_destination: DestinationDraft;
  /** Mapped keys only. */
  entries: Partial<Record<string, DestinationDraft>>;
  is_enabled: boolean;
}

export const EMPTY_IVR_MENU: IvrMenuDraft = {
  name: "",
  description: "",
  prompt_id: "",
  invalid_prompt_id: "",
  timeout_seconds: "5",
  max_retries: "3",
  allow_direct_dial: true,
  timeout_destination: HANGUP,
  invalid_destination: HANGUP,
  entries: {},
  is_enabled: true,
};

export function ivrMenuDraft(m: IvrMenu): IvrMenuDraft {
  const entries: IvrMenuDraft["entries"] = {};
  for (const e of m.entries) entries[e.digit] = destinationDraft(e.destination, EMPTY_DESTINATION);
  return {
    name: m.name,
    description: m.description ?? "",
    prompt_id: m.prompt_id ?? "",
    invalid_prompt_id: m.invalid_prompt_id ?? "",
    timeout_seconds: String(m.timeout_seconds),
    max_retries: String(m.max_retries),
    allow_direct_dial: m.allow_direct_dial,
    timeout_destination: destinationDraft(m.timeout_destination, HANGUP),
    invalid_destination: destinationDraft(m.invalid_destination, HANGUP),
    entries,
    is_enabled: m.is_enabled,
  };
}

export function ivrMenuBody(d: IvrMenuDraft): IvrMenuInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    prompt_id: d.prompt_id || null,
    invalid_prompt_id: d.invalid_prompt_id || null,
    timeout_seconds: Number(d.timeout_seconds),
    max_retries: Number(d.max_retries),
    allow_direct_dial: d.allow_direct_dial,
    timeout_destination: destinationBody(d.timeout_destination),
    invalid_destination: destinationBody(d.invalid_destination),
    entries: IVR_DIGITS.filter((k) => d.entries[k]).map((k) => ({ digit: k, destination: destinationBody(d.entries[k]!) })),
    is_enabled: d.is_enabled,
  };
}

export function ivrMenuValid(d: IvrMenuDraft): boolean {
  const t = Number(d.timeout_seconds);
  const r = Number(d.max_retries);
  return d.name.trim().length > 0
    && Number.isInteger(t) && t >= 1 && t <= 30
    && Number.isInteger(r) && r >= 1 && r <= 9
    && destinationComplete(d.timeout_destination)
    && destinationComplete(d.invalid_destination)
    && IVR_DIGITS.every((k) => !d.entries[k] || destinationComplete(d.entries[k]!));
}

/** Prompt pickers for one organization, with the saved name when the list cannot load. */
function usePromptOptions(organizationId: string) {
  const prompts = useApiData<Page<Prompt>>(organizationId ? "/prompts" : null, { organization_id: organizationId, limit: 200 });
  return { options: (prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name })), loading: prompts.loading };
}

export function IvrMenuFields({ draft, onChange, errors, organizationId, current, disabled, autoFocus }: {
  draft: IvrMenuDraft;
  onChange: (patch: Partial<IvrMenuDraft>) => void;
  errors: Record<string, string>;
  organizationId: string;
  current?: IvrMenu;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const prompts = usePromptOptions(organizationId);
  const options = useDestinationOptions(organizationId);
  const withCurrent = (opts: { value: string; label: string }[], value: string, label: string | null) =>
    value && !opts.some((o) => o.value === value) ? [...opts, { value, label: label ?? "Deleted prompt" }] : opts;
  const promptOptions = withCurrent(prompts.options, draft.prompt_id, current?.prompt_name ?? null);
  const invalidOptions = withCurrent(prompts.options, draft.invalid_prompt_id, current?.invalid_prompt_name ?? null);
  const currentEntry = (digit: string) => current?.entries.find((e) => e.digit === digit)?.destination;
  return (
    <>
      <div className="form-grid">
        <TextField label="Name" required autoFocus={autoFocus} disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Main menu"
          help={current ? <>Dialplan context <span className="mono">{current.context}</span> stays the same.</> : "Also names the menu for routes and other menus."} onChange={(e) => onChange({ name: e.target.value })} />
        <SelectField label="Menu prompt" required disabled={disabled} value={draft.prompt_id} error={errors.prompt_id}
          placeholder={prompts.loading ? "Loading prompts…" : promptOptions.length ? "Choose a prompt" : "No prompts yet (Telephony → Audio)"}
          help="Played when the call arrives; callers may press a key while it plays." options={promptOptions} onChange={(e) => onChange({ prompt_id: e.target.value })} />
      </div>
      <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="field__label" style={{ marginBottom: 8 }}>Keys</legend>
        <div className="stack stack--sm">
          {IVR_DIGITS.map((digit) => {
            const entry = draft.entries[digit];
            const set = (next: DestinationDraft | null) => {
              const entries = { ...draft.entries };
              if (next) entries[digit] = next; else delete entries[digit];
              onChange({ entries });
            };
            return (
              <div key={digit} className="row" style={{ alignItems: "flex-start" }}>
                <span className="kv-chip" style={{ minWidth: 36, justifyContent: "center", marginTop: entry ? 30 : 6, fontSize: "var(--text-base)" }} aria-hidden="true">{digit}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {entry ? (
                    <DestinationPicker label={`Key ${digit}`} idBase={`ivr-key-${digit === "*" ? "star" : digit === "#" ? "hash" : digit}`} draft={entry} onChange={set} options={options} allowHangup
                      current={currentEntry(digit)} error={errors[`entries.${digit}`]} disabled={disabled} exclude={current?.id} />
                  ) : (
                    <Button size="sm" variant="ghost" icon="plus" disabled={disabled} onClick={() => set(EMPTY_DESTINATION)} aria-label={`Map key ${digit}`}>Key {digit}: not mapped</Button>
                  )}
                </div>
                {entry && !disabled ? <Button size="sm" variant="ghost" icon="x" style={{ marginTop: 26 }} onClick={() => set(null)} aria-label={`Unmap key ${digit}`}>Remove</Button> : null}
              </div>
            );
          })}
        </div>
      </fieldset>
      <Checkbox label="Callers may dial an extension number during the menu" description="Extensions of this organization only; a mapped key wins over an extension starting with the same digit." checked={draft.allow_direct_dial} disabled={disabled}
        onChange={(e) => onChange({ allow_direct_dial: e.target.checked })} />
      <div className="form-grid">
        <TextField label="Wait for a key (seconds)" type="number" min={1} max={30} required disabled={disabled} value={draft.timeout_seconds} error={errors.timeout_seconds}
          help="After the prompt ends." onChange={(e) => onChange({ timeout_seconds: e.target.value })} />
        <TextField label="Attempts before giving up" type="number" min={1} max={9} required disabled={disabled} value={draft.max_retries} error={errors.max_retries}
          help="Timeouts or invalid keys before the fallback below." onChange={(e) => onChange({ max_retries: e.target.value })} />
      </div>
      <DestinationPicker label="After too many timeouts" idBase="ivr-timeout" draft={draft.timeout_destination} onChange={(timeout_destination) => onChange({ timeout_destination })} options={options} allowHangup
        current={current?.timeout_destination} error={errors.timeout_destination} disabled={disabled} exclude={current?.id} />
      <SelectField label="Invalid-key prompt" disabled={disabled} value={draft.invalid_prompt_id} error={errors.invalid_prompt_id} placeholder="Default (“I'm sorry, that's not a valid extension”)"
        options={invalidOptions} onChange={(e) => onChange({ invalid_prompt_id: e.target.value })} />
      <DestinationPicker label="After too many invalid keys" idBase="ivr-invalid" draft={draft.invalid_destination} onChange={(invalid_destination) => onChange({ invalid_destination })} options={options} allowHangup
        current={current?.invalid_destination} error={errors.invalid_destination} disabled={disabled} exclude={current?.id} />
      <Switch label="Enabled" description="A disabled menu is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
