// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { ExtensionListPicker, type ListedExtension } from "@/components/common/ExtensionListPicker";
import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Button, Checkbox, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { destinationBody, destinationComplete, destinationDraft, EMPTY_DESTINATION, HANGUP, IVR_DIGITS, type DestinationDraft } from "@/lib/routing";
import type { IvrMenu, IvrMenuInput, Page, Prompt, TimeCondition } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** A key's other destination while a time condition is closed. */
export interface IvrKeyHours {
  time_condition_id: string;
  closed: DestinationDraft;
}

/** The fixed keypad, then any longer keys in order. */
function menuKeys(entries: Partial<Record<string, DestinationDraft>>): string[] {
  const single: readonly string[] = IVR_DIGITS;
  const longer = Object.keys(entries).filter((k) => !single.includes(k)).sort((a, b) => a.length - b.length || a.localeCompare(b));
  return [...single, ...longer];
}

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
  hours: Partial<Record<string, IvrKeyHours>>;
  direct_dial_mode: "all" | "allow" | "block";
  queue_priority: string;
  direct_dial_extensions: ListedExtension[];
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
  hours: {},
  direct_dial_mode: "all",
  queue_priority: "0",
  direct_dial_extensions: [],
  is_enabled: true,
};

export function ivrMenuDraft(m: IvrMenu): IvrMenuDraft {
  const entries: IvrMenuDraft["entries"] = {};
  const hours: IvrMenuDraft["hours"] = {};
  for (const e of m.entries) {
    entries[e.digit] = destinationDraft(e.destination, EMPTY_DESTINATION);
    if (e.time_condition_id) hours[e.digit] = { time_condition_id: e.time_condition_id, closed: destinationDraft(e.closed_destination, HANGUP) };
  }
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
    hours,
    direct_dial_mode: m.direct_dial_mode ?? "all",
    queue_priority: String(m.queue_priority ?? 0),
    direct_dial_extensions: m.direct_dial_extensions ?? [],
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
    direct_dial_mode: d.direct_dial_mode,
    queue_priority: Number(d.queue_priority),
    direct_dial_extension_ids: d.direct_dial_mode === "all" ? [] : d.direct_dial_extensions.map((x) => x.id),
    timeout_destination: destinationBody(d.timeout_destination),
    invalid_destination: destinationBody(d.invalid_destination),
    entries: menuKeys(d.entries).filter((k) => d.entries[k]).map((k) => {
      const hours = d.hours[k];
      return { digit: k, destination: destinationBody(d.entries[k]!), ...(hours ? { time_condition_id: hours.time_condition_id, closed_destination: destinationBody(hours.closed) } : {}) };
    }),
    is_enabled: d.is_enabled,
  };
}

export function ivrMenuValid(d: IvrMenuDraft): boolean {
  const t = Number(d.timeout_seconds);
  const r = Number(d.max_retries);
  return d.name.trim().length > 0
    && Number.isInteger(t) && t >= 1 && t <= 30
    && Number.isInteger(r) && r >= 1 && r <= 9
    && Number.isInteger(Number(d.queue_priority)) && Number(d.queue_priority) >= 0 && Number(d.queue_priority) <= 10
    && destinationComplete(d.timeout_destination)
    && destinationComplete(d.invalid_destination)
    && menuKeys(d.entries).every((k) => !d.entries[k] || destinationComplete(d.entries[k]!))
    && Object.values(d.hours).every((h) => !h || (h.time_condition_id && destinationComplete(h.closed)));
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
  const conditions = useApiData<Page<TimeCondition>>(organizationId ? "/routing/time-conditions" : null, { organization_id: organizationId, limit: 200 });
  const conditionOptions = (conditions.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }));
  const [newKey, setNewKey] = useState("");
  const keyValid = /^[0-9*#]{2,8}$/.test(newKey) && !draft.entries[newKey];
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
          {menuKeys(draft.entries).map((digit) => {
            const entry = draft.entries[digit];
            const set = (next: DestinationDraft | null) => {
              const entries = { ...draft.entries };
              const hours = { ...draft.hours };
              if (next) entries[digit] = next; else { delete entries[digit]; delete hours[digit]; }
              onChange({ entries, hours });
            };
            const keyHours = draft.hours[digit];
            const setHours = (next: IvrKeyHours | null) => {
              const hours = { ...draft.hours };
              if (next) hours[digit] = next; else delete hours[digit];
              onChange({ hours });
            };
            const idKey = digit.replace(/\*/g, "star").replace(/#/g, "hash");
            return (
              <div key={digit} className="row" style={{ alignItems: "flex-start" }}>
                <span className="kv-chip" style={{ minWidth: 36, justifyContent: "center", marginTop: entry ? 30 : 6, fontSize: "var(--text-base)" }} aria-hidden="true">{digit}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {entry ? (
                    <div className="stack stack--sm">
                      <DestinationPicker label={`Key ${digit}`} idBase={`ivr-key-${idKey}`} draft={entry} onChange={set} options={options} allowHangup
                        current={currentEntry(digit)} error={errors[`entries.${digit}`]} disabled={disabled} exclude={current?.id} />
                      <Checkbox label="Goes somewhere else outside hours" checked={!!keyHours} disabled={disabled} onChange={(e) => setHours(e.target.checked ? { time_condition_id: "", closed: HANGUP } : null)} />
                      {keyHours ? (
                        <>
                          <SelectField label="Time condition" required disabled={disabled} value={keyHours.time_condition_id} placeholder="Choose a time condition" options={conditionOptions}
                            help="While it is open the key goes to the destination above." onChange={(e) => setHours({ ...keyHours, time_condition_id: e.target.value })} />
                          <DestinationPicker label="While closed" idBase={`ivr-key-${idKey}-closed`} draft={keyHours.closed} onChange={(closed) => setHours({ ...keyHours, closed })} options={options} allowHangup
                            current={current?.entries.find((e) => e.digit === digit)?.closed_destination ?? undefined} disabled={disabled} exclude={current?.id} />
                        </>
                      ) : null}
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" icon="plus" disabled={disabled} onClick={() => set(EMPTY_DESTINATION)} aria-label={`Map key ${digit}`}>Key {digit}: not mapped</Button>
                  )}
                </div>
                {entry && !disabled ? <Button size="sm" variant="ghost" icon="x" style={{ marginTop: 26 }} onClick={() => set(null)} aria-label={`Unmap key ${digit}`}>Remove</Button> : null}
              </div>
            );
          })}
          <div className="row" style={{ alignItems: "flex-end" }}>
            <TextField label="Add a longer key" disabled={disabled} value={newKey} placeholder="e.g. 42" inputMode="tel" error={errors.menu}
              help="2 to 8 digits, * or #. With key 4 also mapped, a caller pressing 4 waits a moment in case more digits follow." onChange={(e) => setNewKey(e.target.value.trim())} />
            <Button size="sm" icon="plus" disabled={disabled || !keyValid} onClick={() => { onChange({ entries: { ...draft.entries, [newKey]: EMPTY_DESTINATION } }); setNewKey(""); }}>Add key</Button>
          </div>
        </div>
      </fieldset>
      <Checkbox label="Callers may dial an extension number during the menu" description="Extensions of this organization only; a mapped key wins over an extension starting with the same digit." checked={draft.allow_direct_dial} disabled={disabled}
        onChange={(e) => onChange({ allow_direct_dial: e.target.checked })} />
      {draft.allow_direct_dial ? (
        <>
          <SelectField label="Extensions callers may dial" disabled={disabled} value={draft.direct_dial_mode} error={errors.direct_dial_mode}
            options={[{ value: "all", label: "All of them" }, { value: "allow", label: "Only the ones listed" }, { value: "block", label: "All but the ones listed" }]}
            help="Only the ones listed also shuts out ring group, queue and conference room numbers." onChange={(e) => onChange({ direct_dial_mode: e.target.value as IvrMenuDraft["direct_dial_mode"] })} />
          {draft.direct_dial_mode !== "all" ? (
            <ExtensionListPicker label={draft.direct_dial_mode === "allow" ? "Callers may dial" : "Callers may not dial"} organizationId={organizationId} value={draft.direct_dial_extensions} disabled={disabled}
              onChange={(direct_dial_extensions) => onChange({ direct_dial_extensions })} emptyText="None listed yet." error={errors.direct_dial_extension_ids} />
          ) : null}
        </>
      ) : null}
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
      <TextField label="Caller importance in queues" type="number" min={0} max={10} disabled={disabled} value={draft.queue_priority} error={errors.queue_priority}
        help="0 to 10. Callers who come through this menu wait ahead of callers with a lower number. 0 leaves it unchanged." onChange={(e) => onChange({ queue_priority: e.target.value })} />
      <Switch label="Enabled" description="A disabled menu is left out of the phone system; routes that point at it are flagged." checked={draft.is_enabled} disabled={disabled} onChange={(e) => onChange({ is_enabled: e.target.checked })} />
    </>
  );
}
