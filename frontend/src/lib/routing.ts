// SPDX-License-Identifier: AGPL-3.0-or-later
/** Pure helpers for trunks, routes and time conditions (unit tested). */

import type { CallerIdHeader, Destination, DestinationInput, DestinationType, DtmfMode, TimeRange, Trunk, TrunkAuthMode, TrunkTransport, Weekday } from "./types";

export const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const WEEKDAY_LABELS: Record<Weekday, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

export const CODECS = ["ulaw", "alaw", "g722", "opus", "g729", "gsm", "h264"] as const;

export const AUTH_MODES: { value: TrunkAuthMode; label: string }[] = [
  { value: "registration", label: "Registration" },
  { value: "ip", label: "IP authentication" },
];
export const TRANSPORTS: { value: TrunkTransport; label: string }[] = [
  { value: "udp", label: "UDP" },
  { value: "tcp", label: "TCP" },
  { value: "tls", label: "TLS" },
];
export const CALLER_ID_HEADERS: { value: CallerIdHeader; label: string }[] = [
  { value: "pai", label: "P-Asserted-Identity" },
  { value: "rpid", label: "Remote-Party-ID" },
  { value: "none", label: "None (From header only)" },
];
export const DTMF_MODES: { value: DtmfMode; label: string }[] = [
  { value: "rfc4733", label: "RFC 4733 (RTP events)" },
  { value: "inband", label: "In-band audio" },
  { value: "info", label: "SIP INFO" },
  { value: "auto", label: "Automatic" },
];

export function authModeLabel(mode: TrunkAuthMode): string {
  return mode === "ip" ? "IP" : "Registration";
}

/** Split a comma- or newline-separated list, trimming blanks and duplicates. */
export function parseList(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\n,]/)) {
    const v = raw.trim();
    if (v && !out.includes(v)) out.push(v);
  }
  return out;
}

/** Status badge tone and label for a trunk: disabled trunks never show as online. */
export function trunkStatus(t: Pick<Trunk, "is_enabled" | "status">): { tone: "ok" | "danger" | "neutral"; label: string } {
  if (!t.is_enabled) return { tone: "neutral", label: "Disabled" };
  if (t.status?.state === "online") return { tone: "ok", label: "Online" };
  if (t.status?.state === "offline") return { tone: "danger", label: "Offline" };
  return { tone: "neutral", label: "Unknown" };
}

/** "Mon–Fri" for consecutive days, otherwise "Mon, Wed, Fri". */
export function summarizeDays(days: Weekday[]): string {
  const idx = [...new Set(days.map((d) => WEEKDAYS.indexOf(d)).filter((i) => i >= 0))].sort((a, b) => a - b);
  const spans: number[][] = [];
  for (const i of idx) {
    const last = spans[spans.length - 1];
    if (last && last[last.length - 1] === i - 1) last.push(i);
    else spans.push([i]);
  }
  return spans
    .map((s) => {
      const first = WEEKDAYS[s[0]!]!;
      const end = WEEKDAYS[s[s.length - 1]!]!;
      return s.length === 1 ? WEEKDAY_LABELS[first] : `${WEEKDAY_LABELS[first]}–${WEEKDAY_LABELS[end]}`;
    })
    .join(", ");
}

/** e.g. "Mon–Fri 07:30–16:00; Sat 09:00–12:00". */
export function summarizeRanges(ranges: TimeRange[]): string {
  return ranges.map((r) => `${summarizeDays(r.days)} ${r.start}–${r.end}`).join("; ");
}

/** Return a copy of `items` with the element at `from` moved to `to`. */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return items;
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved as T);
  return next;
}

// ---------------------------------------------------------------- destinations (docs/VOICEMAIL_IVR.md §6)

export const DESTINATION_LABELS: Record<DestinationType, string> = {
  extension: "Extension",
  voicemail: "Voicemail of an extension",
  ivr: "IVR menu",
  hangup: "Hang up",
};

/** The editable form of a destination: one target field per kind. */
export interface DestinationDraft {
  type: DestinationType;
  extension_id: string;
  ivr_id: string;
}

export const EMPTY_DESTINATION: DestinationDraft = { type: "extension", extension_id: "", ivr_id: "" };
export const HANGUP: DestinationDraft = { type: "hangup", extension_id: "", ivr_id: "" };

export function destinationDraft(d: Destination | null | undefined, fallback: DestinationDraft = EMPTY_DESTINATION): DestinationDraft {
  if (!d || d.type === "missing") return fallback;
  return { type: d.type, extension_id: d.extension_id ?? "", ivr_id: d.ivr_id ?? "" };
}

/** Normalize a draft for the API: only the target of its kind is sent. */
export function destinationBody(d: DestinationDraft): DestinationInput {
  if (d.type === "hangup") return { type: "hangup", extension_id: null, ivr_id: null };
  if (d.type === "ivr") return { type: "ivr", extension_id: null, ivr_id: d.ivr_id || null };
  return { type: d.type, extension_id: d.extension_id || null, ivr_id: null };
}

/** A draft is complete when its kind has the target it needs. */
export function destinationComplete(d: DestinationDraft): boolean {
  if (d.type === "hangup") return true;
  if (d.type === "ivr") return d.ivr_id.length > 0;
  return d.extension_id.length > 0;
}

/** Keys an IVR menu can map, in keypad order. */
export const IVR_DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"] as const;

/** "0:12", "2:05" for prompt lengths. */
export function formatSeconds(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(seconds ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
