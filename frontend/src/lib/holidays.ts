// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Weekday } from "./types";
import { WEEKDAYS } from "./routing";

/** One holiday of a time condition, as the editor holds it. The API stores a
 * string per holiday (backend veyra/telephony/routing.py):
 * `12-25`, `12-21..01-02` (every year), `2026-11-27`, `2026-12-21..2027-01-02`
 * (once), `4-thu-11`, `last-mon-05` (a weekday of a month, every year). */
export type Holiday =
  | { kind: "yearly"; month: number; day: number; untilMonth: number | null; untilDay: number | null }
  | { kind: "once"; date: string; until: string }
  | { kind: "nth"; nth: "1" | "2" | "3" | "4" | "last"; weekday: Weekday; month: number }
  | { kind: "raw"; value: string };

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
export const NTH_LABELS: Record<string, string> = { "1": "First", "2": "Second", "3": "Third", "4": "Fourth", last: "Last" };
const WEEKDAY_NAMES: Record<Weekday, string> = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };

const pad = (n: number) => String(n).padStart(2, "0");

export function parseHoliday(value: string): Holiday {
  let m = /^(\d{2})-(\d{2})(?:\.\.(\d{2})-(\d{2}))?$/.exec(value);
  if (m) return { kind: "yearly", month: Number(m[1]), day: Number(m[2]), untilMonth: m[3] ? Number(m[3]) : null, untilDay: m[4] ? Number(m[4]) : null };
  m = /^(\d{4}-\d{2}-\d{2})(?:\.\.(\d{4}-\d{2}-\d{2}))?$/.exec(value);
  if (m) return { kind: "once", date: m[1]!, until: m[2] ?? "" };
  m = /^(1|2|3|4|last)-(mon|tue|wed|thu|fri|sat|sun)-(\d{2})$/.exec(value);
  if (m) return { kind: "nth", nth: m[1] as "1", weekday: m[2] as Weekday, month: Number(m[3]) };
  return { kind: "raw", value };
}

export function formatHoliday(h: Holiday): string {
  switch (h.kind) {
    case "yearly": {
      const from = `${pad(h.month)}-${pad(h.day)}`;
      return h.untilMonth && h.untilDay ? `${from}..${pad(h.untilMonth)}-${pad(h.untilDay)}` : from;
    }
    case "once":
      return h.until && h.until !== h.date ? `${h.date}..${h.until}` : h.date;
    case "nth":
      return `${h.nth}-${h.weekday}-${pad(h.month)}`;
    default:
      return h.value.trim();
  }
}

const monthDay = (month: number, day: number) => `${MONTH_NAMES[month - 1]} ${day}`;
const longDate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return y && m && d ? `${monthDay(m, d)}, ${y}` : iso;
};

/** A sentence for the holiday: "Every year, December 21 to January 2". */
export function describeHoliday(value: string): string {
  const h = parseHoliday(value);
  switch (h.kind) {
    case "yearly":
      return h.untilMonth && h.untilDay ? `Every year, ${monthDay(h.month, h.day)} to ${monthDay(h.untilMonth, h.untilDay)}` : `Every year, ${monthDay(h.month, h.day)}`;
    case "once":
      return h.until && h.until !== h.date ? `${longDate(h.date)} to ${longDate(h.until)}` : longDate(h.date);
    case "nth":
      return `${NTH_LABELS[h.nth]} ${WEEKDAY_NAMES[h.weekday]} of ${MONTH_NAMES[h.month - 1]}, every year`;
    default:
      return h.value;
  }
}

export function newHoliday(kind: Holiday["kind"]): Holiday {
  if (kind === "once") return { kind, date: "", until: "" };
  if (kind === "nth") return { kind, nth: "4", weekday: "thu", month: 11 };
  if (kind === "raw") return { kind, value: "" };
  return { kind: "yearly", month: 12, day: 25, untilMonth: null, untilDay: null };
}

export function holidayComplete(h: Holiday): boolean {
  if (h.kind === "once") return /^\d{4}-\d{2}-\d{2}$/.test(h.date) && (!h.until || h.until >= h.date);
  if (h.kind === "raw") return h.value.trim().length > 0;
  return true;
}

export { WEEKDAYS };
export { WEEKDAY_NAMES };
