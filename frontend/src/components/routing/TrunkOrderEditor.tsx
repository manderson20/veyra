// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, IconButton, SelectField } from "@/components/ui";
import { moveItem } from "@/lib/routing";

export interface TrunkOption {
  id: string;
  name: string;
  is_enabled: boolean;
}

/** Ordered trunk list (failover order): add from a select, remove, move up or down. */
export function TrunkOrderEditor({ trunkIds, trunks, onChange, error, disabled }: {
  trunkIds: string[];
  trunks: TrunkOption[];
  onChange: (next: string[]) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  const [adding, setAdding] = useState("");
  const byId = new Map(trunks.map((t) => [t.id, t]));
  const remaining = trunks.filter((t) => !trunkIds.includes(t.id));
  const add = () => {
    if (!adding) return;
    onChange([...trunkIds, adding]);
    setAdding("");
  };
  return (
    <div className="field">
      <span className="field__label">Trunks (failover order)<span className="field__required" aria-hidden="true">*</span></span>
      {trunkIds.length === 0 ? <p className="subtle">No trunks yet. Calls matching this route need at least one trunk.</p> : null}
      {trunkIds.length > 0 ? (
        <ol className="list-plain" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
          {trunkIds.map((id, i) => {
            const t = byId.get(id);
            return (
              <li key={id} className="list-row" style={{ padding: "var(--space-2) var(--space-3)" }}>
                <span className="row" style={{ gap: "var(--space-3)" }}>
                  <span className="subtle mono" style={{ minWidth: 20 }}>{i + 1}.</span>
                  <span className="table__primary">{t?.name ?? "Unknown trunk"}</span>
                  {t && !t.is_enabled ? <Badge tone="neutral">Disabled</Badge> : null}
                </span>
                {!disabled ? (
                  <span className="row" style={{ gap: 2 }}>
                    <IconButton size="sm" icon="chevronUp" label={`Move ${t?.name ?? "trunk"} up`} disabled={i === 0} onClick={() => onChange(moveItem(trunkIds, i, i - 1))} />
                    <IconButton size="sm" icon="chevronDown" label={`Move ${t?.name ?? "trunk"} down`} disabled={i === trunkIds.length - 1} onClick={() => onChange(moveItem(trunkIds, i, i + 1))} />
                    <IconButton size="sm" icon="trash" label={`Remove ${t?.name ?? "trunk"}`} onClick={() => onChange(trunkIds.filter((x) => x !== id))} />
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : null}
      {!disabled ? (
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <SelectField label={<span className="sr-only">Trunk to add</span>} value={adding} placeholder={remaining.length ? "Choose a trunk to add" : "All trunks added"}
              disabled={remaining.length === 0} options={remaining.map((t) => ({ value: t.id, label: t.is_enabled ? t.name : `${t.name} (disabled)` }))} onChange={(e) => setAdding(e.target.value)} />
          </div>
          <Button icon="plus" disabled={!adding} onClick={add}>Add trunk</Button>
        </div>
      ) : null}
      <p className="field__help">Calls try the first trunk; if it is unavailable or rejects the call, the next one is tried.</p>
      {error ? <p className="field__error" role="alert">{error}</p> : null}
    </div>
  );
}
