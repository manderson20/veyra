// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { SelectField, TextField } from "@/components/ui";

type Mode = "" | "followme" | "number";
const modeOf = (v: string): Mode => (!v ? "" : v === "followme" ? "followme" : "number");

/** What a key pressed during a voicemail greeting does (#131): nothing,
 * follow me (key 1 of an extension's box) or another number. The parent
 * keys it on the box so the mode starts from the saved value. */
export function LocaterField({ digit, value, onChange, followMe, error, disabled }: {
  digit: "1" | "2";
  value: string;
  onChange: (next: string) => void;
  /** Offer follow me (key 1 of an extension's own box). */
  followMe: boolean;
  error?: string;
  disabled?: boolean;
}) {
  const [mode, setMode] = useState<Mode>(() => modeOf(value));
  return (
    <div className="form-grid">
      <SelectField label={`Press ${digit} during the greeting`} disabled={disabled} value={mode} error={mode !== "number" ? error : undefined}
        options={[{ value: "", label: "Does nothing" }, ...(followMe || mode === "followme" ? [{ value: "followme", label: "Tries the follow-me numbers" }] : []), { value: "number", label: "Rings another number" }]}
        onChange={(e) => {
          const next = e.target.value as Mode;
          setMode(next);
          onChange(next === "followme" ? "followme" : next === "number" && modeOf(value) === "number" ? value : "");
        }} />
      {mode === "number" ? (
        <TextField label="Number" required inputMode="numeric" disabled={disabled} value={value} error={error} placeholder="e.g. 1002"
          help="An extension, ring group or queue of the organization." onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} />
      ) : null}
    </div>
  );
}
