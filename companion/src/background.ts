// SPDX-License-Identifier: AGPL-3.0-or-later
/** Veyra Companion service worker (docs/COMPANION.md §5).
 *
 * Holds the bearer token, keeps the call-event WebSocket open, shows
 * notifications for ringing and missed calls, owns the "Call … with Veyra"
 * context menu and answers messages from the popup, the options page and the
 * content script.
 *
 * This file must stay a single bundle: it only imports modules that no
 * extension page imports at run time (the pages import types only). */

import { ApiError, SignedOut, VeyraClient, describeError, normalizeServerUrl } from "./lib/api";
import { isCallEvent, parseStreamEvent, type ListenerState } from "./lib/events";
import type {
  DialResult,
  DirectoryResult,
  LoginResult,
  Request,
  Response,
  SavePreferencesResult,
  StateResult,
} from "./lib/messages";
import { looksLikeNumber, normalizeNumber } from "./lib/numbers";
import {
  applyToRecent,
  missedNotificationId,
  notificationFor,
  notificationsToClear,
} from "./lib/notifications";
import { clearSignIn, getStored, getStoredKey, setStored, type StoredState } from "./lib/storage";
import {
  DEFAULT_PREFERENCES,
  type CompanionChallenge,
  type CompanionPreferences,
  type CompanionSession,
  type ConnectionState,
  type DirectoryOut,
  type MyExtension,
  type OriginateOut,
  type PreferencesOut,
  type TicketOut,
} from "./lib/types";

const MENU_ID = "veyra-call-selection";
const ALARM_NAME = "veyra-stream-check";
const TEL_SCRIPT_ID = "veyra-tel-links";
const BACKOFF_MS = [2000, 5000, 10000, 30000] as const;
const ICON = "icons/icon-128.png";
const MAX_CALLBACKS = 20;

// ------------------------------------------------------------------ helpers

function log(...parts: unknown[]): void {
  console.debug("[veyra]", ...parts);
}

async function hostPermissionGranted(origin: string): Promise<boolean> {
  return chrome.permissions.contains({ origins: [`${origin}/*`] });
}

async function ensureHostPermission(origin: string): Promise<boolean> {
  if (await hostPermissionGranted(origin)) {
    return true;
  }
  try {
    // Works when the message that triggered us carried a user gesture; the
    // popup also asks before sending, so this is the fallback.
    return await chrome.permissions.request({ origins: [`${origin}/*`] });
  } catch (error) {
    log("permissions.request failed", error);
    return false;
  }
}

async function signOutLocally(): Promise<void> {
  closeSocket();
  await clearSignIn();
  await setConnection("disabled");
}

/** A client for the stored server and token, or null when not signed in. */
async function clientFromStorage(): Promise<VeyraClient | null> {
  const stored = await getStored();
  if (!stored.serverUrl || !stored.token) {
    return null;
  }
  return new VeyraClient(stored.serverUrl, stored.token, signOutLocally);
}

function preferencesOf(stored: StoredState): CompanionPreferences {
  return { ...DEFAULT_PREFERENCES, ...(stored.preferences ?? {}) };
}

function chooseExtension(
  extensions: MyExtension[],
  preferences: CompanionPreferences,
  requested?: string,
): MyExtension | null {
  const enabled = extensions.filter((e) => e.is_enabled);
  if (requested) {
    return enabled.find((e) => e.id === requested) ?? null;
  }
  if (preferences.default_extension_id) {
    const preferred = enabled.find((e) => e.id === preferences.default_extension_id);
    if (preferred) {
      return preferred;
    }
  }
  return enabled[0] ?? null;
}

function isRequest(value: unknown): value is Request {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

function errorResult(error: unknown): { status: "error"; code: string; detail: string } {
  const { code, detail } = describeError(error);
  return { status: "error", code, detail };
}

function notify(id: string, options: chrome.notifications.NotificationCreateOptions): void {
  chrome.notifications.create(id, options, () => {
    if (chrome.runtime.lastError) {
      log("notification failed", chrome.runtime.lastError.message);
    }
  });
}

function toast(title: string, message: string): void {
  notify(`veyra-info-${Date.now()}`, {
    type: "basic",
    iconUrl: ICON,
    title,
    message,
    priority: 0,
  });
}

// ------------------------------------------------------------------ sign-in

async function completeSignIn(serverUrl: string, session: CompanionSession): Promise<void> {
  await setStored({
    serverUrl,
    token: session.token,
    tokenId: session.token_id,
    user: session.user,
    extensions: session.extensions,
    recent: [],
    callbacks: {},
  });
  const client = new VeyraClient(serverUrl, session.token, signOutLocally);
  try {
    const prefs = await client.get<PreferencesOut>("/api/v1/me/preferences");
    await setStored({ preferences: { ...DEFAULT_PREFERENCES, ...prefs.companion } });
    await syncTelLinks(prefs.companion.handle_tel_links);
  } catch (error) {
    log("preferences fetch failed", error);
    await setStored({ preferences: { ...DEFAULT_PREFERENCES } });
  }
  resetBackoff();
  void connectStream();
}

async function handleLogin(
  serverUrl: string,
  email: string,
  password: string,
  device: string,
): Promise<LoginResult> {
  const origin = normalizeServerUrl(serverUrl);
  if (origin === null) {
    return {
      status: "error",
      code: "bad_server_url",
      detail: "Enter the server address as https://host (HTTPS is required).",
    };
  }
  if (!(await ensureHostPermission(origin))) {
    return {
      status: "error",
      code: "permission_denied",
      detail:
        `Veyra Companion needs permission to contact ${origin}. ` +
        "Allow it when the browser asks, then sign in again.",
    };
  }
  await setStored({ serverUrl: origin });
  const client = new VeyraClient(origin, null);
  try {
    const result = await client.fetchResponse<CompanionSession | CompanionChallenge>(
      "/api/v1/auth/companion/login",
      { method: "POST", body: JSON.stringify({ email, password, device }) },
    );
    if (result.status === 202) {
      const challenge = result.body as CompanionChallenge;
      return {
        status: "mfa",
        challenge: challenge.challenge,
        methods: challenge.methods,
        enrol: challenge.enrol,
      };
    }
    await completeSignIn(origin, result.body as CompanionSession);
    return { status: "ok" };
  } catch (error) {
    return errorResult(error);
  }
}

async function handleVerify(challenge: string, code: string, device: string): Promise<LoginResult> {
  const serverUrl = await getStoredKey("serverUrl");
  if (!serverUrl) {
    return { status: "error", code: "no_server", detail: "Start the sign-in again." };
  }
  const client = new VeyraClient(serverUrl, null);
  try {
    const session = await client.post<CompanionSession>("/api/v1/auth/companion/verify", {
      challenge,
      code,
      device,
    });
    await completeSignIn(serverUrl, session);
    return { status: "ok" };
  } catch (error) {
    return errorResult(error);
  }
}

async function handleLogout(): Promise<{ status: "ok" }> {
  const client = await clientFromStorage();
  if (client) {
    try {
      await client.post<undefined>("/api/v1/auth/companion/logout");
    } catch (error) {
      log("logout request failed", error);
    }
  }
  await signOutLocally();
  return { status: "ok" };
}

// ------------------------------------------------------------------ dialling

async function handleDial(number: string, extensionId?: string): Promise<DialResult> {
  const stored = await getStored();
  if (!stored.serverUrl || !stored.token) {
    return { status: "error", code: "not_signed_in", detail: "Sign in to Veyra Companion first." };
  }
  const preferences = preferencesOf(stored);
  const extension = chooseExtension(stored.extensions ?? [], preferences, extensionId);
  if (extension === null) {
    return {
      status: "error",
      code: "no_extension",
      detail: "You have no enabled extension to dial from.",
    };
  }
  const dialable = normalizeNumber(number, { dialPrefix: preferences.dial_prefix });
  if (dialable === "") {
    return { status: "error", code: "empty_number", detail: "Enter a number to call." };
  }
  const client = new VeyraClient(stored.serverUrl, stored.token, signOutLocally);
  try {
    const out = await client.post<OriginateOut>("/api/v1/calls/originate", {
      extension_id: extension.id,
      number: dialable,
    });
    return { status: "ok", message: out.message };
  } catch (error) {
    return errorResult(error);
  }
}

/** Dial from a place without its own UI (context menu, notification). */
async function dialAndToast(number: string): Promise<void> {
  const result = await handleDial(number);
  if (result.status === "ok") {
    toast("Calling with Veyra", result.message);
  } else {
    toast("Veyra could not place the call", result.detail);
  }
}

// ------------------------------------------------------------------ data

async function handleDirectory(q: string): Promise<DirectoryResult> {
  const client = await clientFromStorage();
  if (!client) {
    return { status: "error", code: "not_signed_in", detail: "Sign in first." };
  }
  try {
    const out = await client.get<DirectoryOut>(
      `/api/v1/directory?q=${encodeURIComponent(q.trim().slice(0, 100))}`,
    );
    return { status: "ok", results: out.results };
  } catch (error) {
    return errorResult(error);
  }
}

async function handleSavePreferences(
  companion: CompanionPreferences,
): Promise<SavePreferencesResult> {
  const client = await clientFromStorage();
  if (!client) {
    return { status: "error", code: "not_signed_in", detail: "Sign in first." };
  }
  const body: CompanionPreferences = {
    speed_dials: companion.speed_dials.slice(0, 50).map((d) => ({
      label: d.label.trim().slice(0, 40),
      number: d.number.trim().slice(0, 32),
    })),
    dial_prefix: companion.dial_prefix.replace(/[^0-9]/g, "").slice(0, 8),
    default_extension_id: companion.default_extension_id || null,
    notify_incoming: companion.notify_incoming,
    notify_missed: companion.notify_missed,
    handle_tel_links: companion.handle_tel_links,
  };
  try {
    const out = await client.put<PreferencesOut>("/api/v1/me/preferences", { companion: body });
    const preferences = { ...DEFAULT_PREFERENCES, ...out.companion };
    await setStored({ preferences });
    await syncTelLinks(preferences.handle_tel_links);
    return { status: "ok", preferences };
  } catch (error) {
    return errorResult(error);
  }
}

async function handleState(): Promise<StateResult> {
  const stored = await getStored();
  const signedIn = Boolean(stored.serverUrl && stored.token);
  return {
    status: "ok",
    signedIn,
    serverUrl: stored.serverUrl ?? null,
    user: signedIn ? (stored.user ?? null) : null,
    extensions: signedIn ? (stored.extensions ?? []) : [],
    preferences: preferencesOf(stored),
    recent: signedIn ? (stored.recent ?? []) : [],
    connection: signedIn ? connectionState() : "disabled",
  };
}

async function refreshExtensions(client: VeyraClient): Promise<void> {
  try {
    const extensions = await client.get<MyExtension[]>("/api/v1/me/extensions");
    await setStored({ extensions });
  } catch (error) {
    log("extensions refresh failed", error);
  }
}

// ------------------------------------------------------------------ event stream

let socket: WebSocket | null = null;
let connecting = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let backoffIndex = 0;
let listenerState: ListenerState = "connected";
let lastConnection: ConnectionState | null = null;

function connectionState(): ConnectionState {
  if (socket !== null && socket.readyState === WebSocket.OPEN) {
    return listenerState === "connected" ? "connected" : listenerState;
  }
  return "reconnecting";
}

async function setConnection(state: ConnectionState): Promise<void> {
  if (state !== lastConnection) {
    lastConnection = state;
    await setStored({ connection: state });
  }
}

function resetBackoff(): void {
  backoffIndex = 0;
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function closeSocket(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  const s = socket;
  socket = null;
  if (s !== null) {
    s.onclose = null;
    s.onmessage = null;
    s.onerror = null;
    try {
      s.close(1000, "signed out");
    } catch {
      // already closed
    }
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer !== null) {
    return;
  }
  const delay = BACKOFF_MS[Math.min(backoffIndex, BACKOFF_MS.length - 1)] ?? 30000;
  backoffIndex += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectStream();
  }, delay);
}

async function connectStream(): Promise<void> {
  if (connecting) {
    return;
  }
  if (socket !== null && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const client = await clientFromStorage();
  if (client === null) {
    await setConnection("disabled");
    return;
  }
  connecting = true;
  await setConnection("reconnecting");
  let ticket: TicketOut;
  try {
    ticket = await client.post<TicketOut>("/api/v1/events/ticket");
  } catch (error) {
    connecting = false;
    if (error instanceof SignedOut) {
      return; // storage already cleared
    }
    if (error instanceof ApiError && error.status === 403) {
      // Token without the `me` scope: nothing to stream.
      await setConnection("disabled");
      return;
    }
    log("ticket failed", error);
    scheduleReconnect();
    return;
  }
  const wsUrl = new URL(ticket.url || "/api/v1/events/calls", client.baseUrl);
  wsUrl.protocol = wsUrl.protocol === "http:" ? "ws:" : "wss:";
  wsUrl.searchParams.set("ticket", ticket.ticket);
  let ws: WebSocket;
  try {
    ws = new WebSocket(wsUrl.toString());
  } catch (error) {
    connecting = false;
    log("websocket open failed", error);
    scheduleReconnect();
    return;
  }
  socket = ws;
  connecting = false;
  ws.onopen = () => {
    log("stream open");
  };
  ws.onmessage = (ev: MessageEvent) => {
    if (typeof ev.data !== "string") {
      return;
    }
    void handleFrame(ws, ev.data, client);
  };
  ws.onerror = () => {
    log("stream error");
  };
  ws.onclose = (ev: CloseEvent) => {
    if (socket === ws) {
      socket = null;
    }
    log("stream closed", ev.code, ev.reason);
    void (async () => {
      if (ev.code === 4401) {
        // Ticket or sign-in rejected: the next ticket request will tell us
        // whether the token is gone (401 clears storage) or it was a race.
        backoffIndex = Math.max(backoffIndex, 1);
      }
      const still = await clientFromStorage();
      if (still === null) {
        await setConnection("disabled");
        return;
      }
      await setConnection("reconnecting");
      scheduleReconnect();
    })();
  };
}

async function handleFrame(ws: WebSocket, text: string, client: VeyraClient): Promise<void> {
  const event = parseStreamEvent(text);
  if (event === null) {
    return;
  }
  if (event.type === "ping") {
    listenerState = event.listener;
    try {
      ws.send(JSON.stringify({ type: "pong" }));
    } catch (error) {
      log("pong failed", error);
    }
    await setConnection(connectionState());
    return;
  }
  if (event.type === "hello") {
    listenerState = event.listener;
    resetBackoff();
    await setConnection(connectionState());
    // The hello carries id/number/name; the full shape comes from /me/extensions.
    await refreshExtensions(client);
    const stored = await getStoredKey("extensions");
    if (!stored || stored.length === 0) {
      await setStored({
        extensions: event.extensions.map((e) => ({
          id: e.id,
          number: e.number,
          display_name: e.name,
          organization_id: "",
          organization_name: "",
          is_enabled: true,
          registration: null,
        })),
      });
    }
    return;
  }
  if (!isCallEvent(event)) {
    return;
  }
  const stored = await getStored();
  const preferences = preferencesOf(stored);
  const recent = applyToRecent(stored.recent ?? [], event);
  const callbacks = { ...(stored.callbacks ?? {}) };
  for (const id of notificationsToClear(event)) {
    chrome.notifications.clear(id);
  }
  const intent = notificationFor(event, preferences);
  if (intent !== null) {
    const options: chrome.notifications.NotificationCreateOptions = {
      type: "basic",
      iconUrl: ICON,
      title: intent.title,
      message: intent.message,
      priority: intent.kind === "incoming" ? 2 : 1,
      requireInteraction: intent.kind === "incoming",
    };
    if (intent.kind === "missed" && intent.callback !== null) {
      options.buttons = [{ title: "Call back" }];
      callbacks[intent.id] = intent.callback;
      const ids = Object.keys(callbacks);
      for (const old of ids.slice(0, Math.max(0, ids.length - MAX_CALLBACKS))) {
        delete callbacks[old];
      }
    }
    notify(intent.id, options);
  }
  await setStored({ recent, callbacks });
}

async function ensureConnected(): Promise<void> {
  const client = await clientFromStorage();
  if (client === null) {
    closeSocket();
    await setConnection("disabled");
    return;
  }
  if (socket !== null && socket.readyState === WebSocket.OPEN) {
    await setConnection(connectionState());
    return;
  }
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  await connectStream();
}

// ------------------------------------------------------------------ tel: links

function scriptingAvailable(): boolean {
  return typeof chrome.scripting !== "undefined" && chrome.scripting !== null;
}

/** Register or remove the tel: link content script to match the preference.
 * Registration needs the optional `scripting` permission and the
 * host permission for all HTTPS sites, both requested by the options page. */
async function syncTelLinks(enabled: boolean): Promise<void> {
  if (!scriptingAvailable()) {
    return;
  }
  const granted = await chrome.permissions.contains({
    permissions: ["scripting"],
    origins: ["https://*/*"],
  });
  if (!granted) {
    return;
  }
  try {
    const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [TEL_SCRIPT_ID] });
    if (enabled && existing.length === 0) {
      await chrome.scripting.registerContentScripts([
        {
          id: TEL_SCRIPT_ID,
          js: ["content.js"],
          matches: ["https://*/*"],
          runAt: "document_idle",
          persistAcrossSessions: true,
        },
      ]);
      log("tel: link handler registered");
    } else if (!enabled && existing.length > 0) {
      await chrome.scripting.unregisterContentScripts({ ids: [TEL_SCRIPT_ID] });
      log("tel: link handler removed");
    }
  } catch (error) {
    log("content script registration failed", error);
  }
}

// ------------------------------------------------------------------ menus, alarms

function ensureContextMenu(): void {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create(
      {
        id: MENU_ID,
        title: "Call \u201c%s\u201d with Veyra",
        contexts: ["selection"],
      },
      () => {
        if (chrome.runtime.lastError) {
          log("context menu", chrome.runtime.lastError.message);
        }
      },
    );
  });
}

async function ensureAlarm(): Promise<void> {
  const existing = await chrome.alarms.get(ALARM_NAME);
  if (!existing) {
    await chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  }
}

async function startup(): Promise<void> {
  ensureContextMenu();
  await ensureAlarm();
  const prefs = await getStoredKey("preferences");
  await syncTelLinks(prefs?.handle_tel_links ?? false);
  await ensureConnected();
}

chrome.runtime.onInstalled.addListener(() => {
  void startup();
});

chrome.runtime.onStartup.addListener(() => {
  void startup();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    void ensureConnected();
  }
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID) {
    return;
  }
  const text = info.selectionText ?? "";
  if (!looksLikeNumber(text)) {
    toast("Not a phone number", `\u201c${text.slice(0, 60)}\u201d does not look like a number.`);
    return;
  }
  void dialAndToast(text);
});

chrome.notifications.onButtonClicked.addListener((notificationId, buttonIndex) => {
  if (buttonIndex !== 0) {
    return;
  }
  void (async () => {
    const callbacks = (await getStoredKey("callbacks")) ?? {};
    const number = callbacks[notificationId];
    if (number === undefined) {
      return;
    }
    delete callbacks[notificationId];
    await setStored({ callbacks });
    chrome.notifications.clear(notificationId);
    await dialAndToast(number);
  })();
});

chrome.notifications.onClicked.addListener((notificationId) => {
  chrome.notifications.clear(notificationId);
});

chrome.notifications.onClosed.addListener((notificationId) => {
  if (!notificationId.startsWith(missedNotificationId(""))) {
    return;
  }
  void (async () => {
    const callbacks = (await getStoredKey("callbacks")) ?? {};
    if (notificationId in callbacks) {
      delete callbacks[notificationId];
      await setStored({ callbacks });
    }
  })();
});

// ------------------------------------------------------------------ messages

async function dispatch(request: Request): Promise<Response> {
  switch (request.type) {
    case "login":
      return handleLogin(request.serverUrl, request.email, request.password, request.device);
    case "verify":
      return handleVerify(request.challenge, request.code, request.device);
    case "logout":
      return handleLogout();
    case "dial":
      return handleDial(request.number, request.extensionId);
    case "directory":
      return handleDirectory(request.q);
    case "savePreferences":
      return handleSavePreferences(request.companion);
    case "state":
      return handleState();
  }
}

chrome.runtime.onMessage.addListener(
  (message: unknown, sender: chrome.runtime.MessageSender, sendResponse: (response: Response) => void) => {
    if (sender.id !== chrome.runtime.id || !isRequest(message)) {
      return false;
    }
    dispatch(message)
      .then(sendResponse)
      .catch((error: unknown) => {
        sendResponse(errorResult(error));
      });
    return true;
  },
);

// Service workers restart often: every start re-checks the stream.
void (async () => {
  await ensureAlarm();
  await ensureConnected();
})();
