// SPDX-License-Identifier: AGPL-3.0-or-later
/** Labels and formatting shared by the call history views (docs/REPORTING.md §8). */
import type { Tone } from "@/components/ui";
import type { CallDirection, CallOutcome } from "@/lib/types";

export const OUTCOME: Record<CallOutcome, { label: string; tone: Tone }> = {
  answered: { label: "Answered", tone: "ok" },
  missed: { label: "Missed", tone: "warn" },
  busy: { label: "Busy", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
  voicemail: { label: "Voicemail", tone: "info" },
  abandoned: { label: "Abandoned", tone: "warn" },
};
export const DIRECTION: Record<CallDirection, { label: string; icon: string }> = {
  internal: { label: "Internal", icon: "phone" },
  inbound: { label: "Inbound", icon: "arrowIn" },
  outbound: { label: "Outbound", icon: "arrowOut" },
};

/** 65 → "1:05", 3723 → "1:02:03". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function party(number: string | null, name: string | null, ext?: { number: string; display_name: string } | null) {
  if (ext) return <><span>{ext.display_name}</span> <span className="subtle mono">{ext.number}</span></>;
  if (name && name !== number) return <><span>{name}</span> <span className="subtle mono">{number}</span></>;
  return <span className="mono">{number ?? "—"}</span>;
}
