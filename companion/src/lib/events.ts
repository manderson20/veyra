// SPDX-License-Identifier: AGPL-3.0-or-later
/** Messages on `WS /api/v1/events/calls` (docs/COMPANION.md §4). The server
 * sends every call-event field on every call event (backend
 * veyra/core/callevents.py `CallEvent.payload`). */

export type ListenerState = "connected" | "reconnecting" | "disabled";

export interface HelloExtension {
  id: string;
  number: string;
  name: string;
}

export interface HelloEvent {
  type: "hello";
  extensions: HelloExtension[];
  listener: ListenerState;
  server_time: string;
}

export interface PingEvent {
  type: "ping";
  listener: ListenerState;
}

export interface CallEventFields {
  channel_id: string;
  extension_id: string;
  extension_number: string;
  direction: "in" | "out";
  remote_number: string | null;
  remote_name: string | null;
  at: string;
  answered: boolean;
  cause: string | null;
}

export interface CallRingingEvent extends CallEventFields {
  type: "call.ringing";
}

export interface CallDialingEvent extends CallEventFields {
  type: "call.dialing";
}

export interface CallAnsweredEvent extends CallEventFields {
  type: "call.answered";
}

export interface CallEndedEvent extends CallEventFields {
  type: "call.ended";
}

export type CallEvent = CallRingingEvent | CallDialingEvent | CallAnsweredEvent | CallEndedEvent;
export type StreamEvent = HelloEvent | PingEvent | CallEvent;

const CALL_TYPES = new Set(["call.ringing", "call.dialing", "call.answered", "call.ended"]);
const LISTENER_STATES = new Set<string>(["connected", "reconnecting", "disabled"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function nullableStr(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function listener(value: unknown): ListenerState {
  return typeof value === "string" && LISTENER_STATES.has(value)
    ? (value as ListenerState)
    : "connected";
}

export function isCallEvent(event: StreamEvent): event is CallEvent {
  return CALL_TYPES.has(event.type);
}

/** Parse one text frame. Unknown or malformed messages yield `null`. */
export function parseStreamEvent(text: string): StreamEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isRecord(data) || typeof data.type !== "string") {
    return null;
  }
  switch (data.type) {
    case "hello": {
      const extensions: HelloExtension[] = Array.isArray(data.extensions)
        ? data.extensions.filter(isRecord).map((e) => ({
            id: str(e.id),
            number: str(e.number),
            name: str(e.name),
          }))
        : [];
      return {
        type: "hello",
        extensions,
        listener: listener(data.listener),
        server_time: str(data.server_time),
      };
    }
    case "ping":
      return { type: "ping", listener: listener(data.listener) };
    case "call.ringing":
    case "call.dialing":
    case "call.answered":
    case "call.ended": {
      const type = data.type;
      const direction: "in" | "out" = data.direction === "out" ? "out" : "in";
      return {
        type,
        channel_id: str(data.channel_id),
        extension_id: str(data.extension_id),
        extension_number: str(data.extension_number),
        direction,
        remote_number: nullableStr(data.remote_number),
        remote_name: nullableStr(data.remote_name),
        at: str(data.at, new Date().toISOString()),
        answered: data.answered === true,
        cause: nullableStr(data.cause),
      };
    }
    default:
      return null;
  }
}
