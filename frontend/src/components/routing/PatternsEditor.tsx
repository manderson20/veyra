// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Button, IconButton, TextField } from "@/components/ui";
import type { OutboundPattern } from "@/lib/types";

export const EMPTY_PATTERN: OutboundPattern = { prefix: "", match: "", prepend: "" };

/**
 * Rows of prefix / match / prepend. The prefix is dialled by the user and
 * stripped; the match uses Asterisk pattern letters; the prepend is added
 * before the number is sent to the trunk.
 */
export function PatternsEditor({ patterns, onChange, error, disabled }: {
  patterns: OutboundPattern[];
  onChange: (next: OutboundPattern[]) => void;
  error?: string | null;
  disabled?: boolean;
}) {
  const update = (i: number, patch: Partial<OutboundPattern>) => onChange(patterns.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const grid = { display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 2fr) minmax(0, 1fr) 36px", gap: "var(--space-3)", alignItems: "start" } as const;
  return (
    <div className="field">
      <span className="field__label">Dial patterns<span className="field__required" aria-hidden="true">*</span></span>
      <div style={grid} aria-hidden="true">
        <span className="subtle">Prefix (stripped)</span>
        <span className="subtle">Match</span>
        <span className="subtle">Prepend</span>
        <span />
      </div>
      {patterns.map((p, i) => (
        <div key={i} style={grid}>
          <TextField label={<span className="sr-only">Prefix for pattern {i + 1}</span>} disabled={disabled} value={p.prefix} placeholder="9" autoComplete="off" spellCheck={false}
            onChange={(e) => update(i, { prefix: e.target.value })} />
          <TextField label={<span className="sr-only">Match for pattern {i + 1}</span>} required disabled={disabled} value={p.match} placeholder="NXXNXXXXXX" autoComplete="off" spellCheck={false}
            onChange={(e) => update(i, { match: e.target.value })} />
          <TextField label={<span className="sr-only">Prepend for pattern {i + 1}</span>} disabled={disabled} value={p.prepend} placeholder="1" autoComplete="off" spellCheck={false}
            onChange={(e) => update(i, { prepend: e.target.value })} />
          <IconButton icon="trash" label={`Remove pattern ${i + 1}`} disabled={disabled || patterns.length <= 1} onClick={() => onChange(patterns.filter((_, j) => j !== i))} />
        </div>
      ))}
      <p className="field__help">
        Match letters: <span className="mono">X</span> any digit, <span className="mono">Z</span> 1–9, <span className="mono">N</span> 2–9, <span className="mono">.</span> one or more of anything,
        <span className="mono"> !</span> zero or more, <span className="mono">[2-5]</span> a range. Example: prefix <span className="mono">9</span>, match <span className="mono">NXXNXXXXXX</span>, prepend <span className="mono">1</span>.
      </p>
      {error ? <p className="field__error" role="alert">{error}</p> : null}
      {!disabled ? <div><Button size="sm" icon="plus" onClick={() => onChange([...patterns, { ...EMPTY_PATTERN }])}>Add pattern</Button></div> : null}
    </div>
  );
}
