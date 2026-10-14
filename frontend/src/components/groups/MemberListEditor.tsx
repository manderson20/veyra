// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, IconButton, SelectField, TextField } from "@/components/ui";
import { moveItem } from "@/lib/routing";
import type { Extension } from "@/lib/types";

export interface MemberDraft {
  extension_id: string;
  /** Queue agents only (0–9). */
  penalty: string;
}

/**
 * Extensions of one organization as members of a ring group, queue or pickup group:
 * add from a select, remove, move up or down (`ordered`), set a penalty (`penalties`).
 */
export function MemberListEditor({ label, members, extensions, onChange, ordered = false, penalties = false, help, error, disabled, emptyText, loading }: {
  label: string;
  members: MemberDraft[];
  extensions: Extension[];
  onChange: (next: MemberDraft[]) => void;
  ordered?: boolean;
  penalties?: boolean;
  help?: string;
  error?: string | null;
  disabled?: boolean;
  emptyText: string;
  loading?: boolean;
}) {
  const [adding, setAdding] = useState("");
  const byId = new Map(extensions.map((x) => [x.id, x]));
  const chosen = new Set(members.map((m) => m.extension_id));
  const remaining = extensions.filter((x) => !chosen.has(x.id));
  const add = () => {
    if (!adding) return;
    onChange([...members, { extension_id: adding, penalty: "0" }]);
    setAdding("");
  };
  const name = (m: MemberDraft) => {
    const x = byId.get(m.extension_id);
    return x ? `${x.number} — ${x.display_name}` : "Deleted extension";
  };
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      {members.length === 0 ? <p className="subtle">{emptyText}</p> : (
        <ol className="list-plain" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
          {members.map((m, i) => {
            const x = byId.get(m.extension_id);
            return (
              <li key={m.extension_id} className="list-row" style={{ padding: "var(--space-2) var(--space-3)" }}>
                <span className="row" style={{ gap: "var(--space-3)" }}>
                  {ordered ? <span className="subtle mono" style={{ minWidth: 20 }}>{i + 1}.</span> : null}
                  <span className="table__primary">{name(m)}</span>
                  {x && !x.is_enabled ? <Badge tone="neutral">Disabled</Badge> : null}
                </span>
                <span className="row" style={{ gap: 2, alignItems: "center" }}>
                  {penalties ? (
                    <TextField label={<span className="sr-only">Penalty of {name(m)}</span>} type="number" min={0} max={9} disabled={disabled} value={m.penalty} style={{ width: 70 }}
                      onChange={(e) => onChange(members.map((o, j) => (j === i ? { ...o, penalty: e.target.value } : o)))} />
                  ) : null}
                  {!disabled && ordered ? (
                    <>
                      <IconButton size="sm" icon="chevronUp" label={`Move ${name(m)} up`} disabled={i === 0} onClick={() => onChange(moveItem(members, i, i - 1))} />
                      <IconButton size="sm" icon="chevronDown" label={`Move ${name(m)} down`} disabled={i === members.length - 1} onClick={() => onChange(moveItem(members, i, i + 1))} />
                    </>
                  ) : null}
                  {!disabled ? <IconButton size="sm" icon="trash" label={`Remove ${name(m)}`} onClick={() => onChange(members.filter((o) => o.extension_id !== m.extension_id))} /> : null}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {!disabled ? (
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <SelectField label={<span className="sr-only">Extension to add</span>} value={adding}
              placeholder={loading ? "Loading extensions…" : remaining.length ? "Choose an extension to add" : extensions.length ? "All extensions added" : "No extensions in this organization"}
              disabled={remaining.length === 0} options={remaining.map((x) => ({ value: x.id, label: `${x.number} — ${x.display_name}${x.is_enabled ? "" : " (disabled)"}` }))} onChange={(e) => setAdding(e.target.value)} />
          </div>
          <Button icon="plus" disabled={!adding} onClick={add}>Add</Button>
        </div>
      ) : null}
      {help ? <p className="field__help">{help}</p> : null}
      {error ? <p className="field__error" role="alert">{error}</p> : null}
    </div>
  );
}

export function membersFromIds(ids: { extension_id: string; penalty?: number | null }[]): MemberDraft[] {
  return ids.map((m) => ({ extension_id: m.extension_id, penalty: String(m.penalty ?? 0) }));
}

export function membersValid(members: MemberDraft[], penalties = false): boolean {
  return members.every((m) => {
    if (!penalties) return true;
    const p = Number(m.penalty);
    return Number.isInteger(p) && p >= 0 && p <= 9;
  });
}
