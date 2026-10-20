// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/**
 * Push instead of polling for live views (issue #111): a WebSocket to
 * `/api/v1/events/staff` that says "changed" whenever a call event touches an
 * extension the user may see. Returns whether the stream is connected, so
 * the page can poll slowly as a fallback while it is and quickly while not.
 */
export function useLiveChanges(onChange: () => void): boolean {
  const [connected, setConnected] = useState(false);
  const callback = useRef(onChange);
  useEffect(() => { callback.current = onChange; }, [onChange]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry: number | undefined;
    let delay = 2000;
    const open = async () => {
      try {
        const t = await api.post<{ ticket: string }>("/events/ticket", undefined, { noRedirect: true });
        if (stopped) return;
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/events/staff?ticket=${encodeURIComponent(t.ticket)}`);
        socket.onopen = () => { setConnected(true); delay = 2000; };
        socket.onmessage = (m) => {
          try {
            if ((JSON.parse(String(m.data)) as { type?: string }).type === "changed") callback.current();
          } catch { /* ignore malformed frames */ }
        };
        socket.onclose = (e) => {
          setConnected(false);
          if (!stopped && e.code !== 4403) retry = window.setTimeout(() => void open(), delay = Math.min(delay * 2, 60000));
        };
      } catch {
        if (!stopped) retry = window.setTimeout(() => void open(), delay = Math.min(delay * 2, 60000));
      }
    };
    void open();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, []);
  return connected;
}
