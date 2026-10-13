// SPDX-License-Identifier: AGPL-3.0-or-later
/** Pure mapping from stream events to what the service worker shows and
 * remembers. Kept free of `chrome.*` so it can be unit-tested. */

import type { CallEvent, StreamEvent } from "./events";
import type { CompanionPreferences, RecentCall } from "./types";

export type NotificationKind = "incoming" | "missed";

export interface NotificationIntent {
  kind: NotificationKind;
  /** Stable id so a ringing notification can be cleared when the call ends. */
  id: string;
  title: string;
  message: string;
  /** Number offered for "Call back" (missed calls only). */
  callback: string | null;
}

export type NotificationPrefs = Pick<CompanionPreferences, "notify_incoming" | "notify_missed">;

export const MAX_RECENT = 20;

export function incomingNotificationId(channelId: string): string {
  return `veyra-call-${channelId}`;
}

export function missedNotificationId(channelId: string): string {
  return `veyra-missed-${channelId}`;
}

export function remoteLabel(name: string | null, number: string | null): string {
  const n = (name ?? "").trim();
  const d = (number ?? "").trim();
  if (n && d && n !== d) {
    return `${n} ${d}`;
  }
  return n || d || "Unknown number";
}

/** Which notification, if any, does this event call for? */
export function notificationFor(
  event: StreamEvent,
  prefs: NotificationPrefs,
): NotificationIntent | null {
  if (event.type === "call.ringing") {
    if (!prefs.notify_incoming || event.direction !== "in") {
      return null;
    }
    return {
      kind: "incoming",
      id: incomingNotificationId(event.channel_id),
      title: `Incoming call on ${event.extension_number}`,
      message: remoteLabel(event.remote_name, event.remote_number),
      callback: null,
    };
  }
  if (event.type === "call.ended") {
    if (!prefs.notify_missed || event.direction !== "in" || event.answered) {
      return null;
    }
    return {
      kind: "missed",
      id: missedNotificationId(event.channel_id),
      title: `Missed call on ${event.extension_number}`,
      message: remoteLabel(event.remote_name, event.remote_number),
      callback: event.remote_number && event.remote_number.trim() !== "" ? event.remote_number : null,
    };
  }
  return null;
}

/** Notification ids that this event makes obsolete (the call was picked up
 * or is over, so the "incoming" toast must go). */
export function notificationsToClear(event: StreamEvent): string[] {
  if (event.type === "call.answered" || event.type === "call.ended") {
    return [incomingNotificationId(event.channel_id)];
  }
  return [];
}

/** Fold a call event into the recent-calls list (newest first, at most
 * MAX_RECENT entries). Ringing and dialing open an entry; answered and
 * ended update it. */
export function applyToRecent(recent: readonly RecentCall[], event: CallEvent): RecentCall[] {
  const index = recent.findIndex((r) => r.channel_id === event.channel_id);
  if (event.type === "call.ringing" || event.type === "call.dialing") {
    const entry: RecentCall = {
      channel_id: event.channel_id,
      number: event.remote_number,
      name: event.remote_name,
      direction: event.direction,
      answered: event.answered,
      at: event.at,
      extension_number: event.extension_number,
    };
    const rest = index >= 0 ? recent.filter((_, i) => i !== index) : [...recent];
    return [entry, ...rest].slice(0, MAX_RECENT);
  }
  if (index < 0) {
    // We missed the start of this call (reconnect); record what we know.
    if (event.type === "call.ended") {
      const entry: RecentCall = {
        channel_id: event.channel_id,
        number: event.remote_number,
        name: event.remote_name,
        direction: event.direction,
        answered: event.answered,
        at: event.at,
        extension_number: event.extension_number,
      };
      return [entry, ...recent].slice(0, MAX_RECENT);
    }
    return [...recent];
  }
  const current = recent[index];
  if (current === undefined) {
    return [...recent];
  }
  const updated: RecentCall = {
    ...current,
    answered: event.type === "call.answered" ? true : event.answered || current.answered,
    number: current.number ?? event.remote_number,
    name: current.name ?? event.remote_name,
  };
  return recent.map((r, i) => (i === index ? updated : r));
}
