// SPDX-License-Identifier: AGPL-3.0-or-later
/** The toolbar popup: sign-in, dial, speed dials, directory, recent calls. */

import "./popup.css";
import { deviceLabel } from "../lib/device";
import { byId, el, relativeTime, serverOrigin } from "../lib/format";
import { sendRequest, type StateResult } from "../lib/messages";
import type { DirectoryEntry, RecentCall } from "../lib/types";

const app = byId<HTMLElement>("app");
const device = deviceLabel();

let state: StateResult | null = null;
let pendingChallenge: { challenge: string; methods: number; enrol: boolean } | null = null;
let lastDirectory: DirectoryEntry[] = [];
let searchTimer: ReturnType<typeof setTimeout> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

// ------------------------------------------------------------------ helpers

function message(kind: "error" | "info", text: string): HTMLParagraphElement {
  return el("p", { class: `msg ${kind}`, role: kind === "error" ? "alert" : "status", text });
}

function setMessage(container: HTMLElement, kind: "error" | "info", text: string): void {
  container.replaceChildren(text ? message(kind, text) : "");
}

async function refreshState(): Promise<void> {
  state = await sendRequest({ type: "state" });
}

function clear(): void {
  app.replaceChildren();
}

// ------------------------------------------------------------------ sign-in

function renderSignIn(prefill: { serverUrl: string | null; error?: string }): void {
  clear();
  const status = el("div");
  const server = el("input", {
    id: "server",
    type: "url",
    placeholder: "https://pbx.example.org",
    autocomplete: "url",
    required: "",
    value: prefill.serverUrl ?? "",
  });
  const email = el("input", { id: "email", type: "email", autocomplete: "username", required: "" });
  const password = el("input", {
    id: "password",
    type: "password",
    autocomplete: "current-password",
    required: "",
  });
  const submit = el("button", { type: "submit", class: "primary", text: "Sign in" });
  const form = el("form", {}, [
    el("label", {}, ["Server address", server]),
    el("label", {}, ["Email", email]),
    el("label", {}, ["Password", password]),
    status,
    submit,
    el("p", { class: "muted small", text: `This browser will be listed as “${device}”.` }),
  ]);
  if (prefill.error) {
    setMessage(status, "error", prefill.error);
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const origin = serverOrigin(server.value);
    if (origin === null) {
      setMessage(status, "error", "Enter the server address as https://host (HTTPS is required).");
      return;
    }
    submit.disabled = true;
    setMessage(status, "info", "Signing in…");
    // The permission prompt needs the click's user gesture, so it is asked
    // for here, synchronously after submit, before anything is awaited.
    const permission = chrome.permissions
      .contains({ origins: [`${origin}/*`] })
      .then((has) => (has ? true : chrome.permissions.request({ origins: [`${origin}/*`] })));
    void (async () => {
      let granted = false;
      try {
        granted = await permission;
      } catch {
        granted = false;
      }
      if (!granted) {
        submit.disabled = false;
        setMessage(
          status,
          "error",
          `Veyra Companion needs permission to contact ${origin}. Allow it when the browser asks.`,
        );
        return;
      }
      const result = await sendRequest({
        type: "login",
        serverUrl: origin,
        email: email.value.trim(),
        password: password.value,
        device,
      });
      submit.disabled = false;
      if (result.status === "ok") {
        await refreshState();
        render();
      } else if (result.status === "mfa") {
        pendingChallenge = { challenge: result.challenge, methods: result.methods, enrol: result.enrol };
        renderMfa();
      } else {
        setMessage(status, "error", result.detail);
      }
    })();
  });
  app.append(el("h1", { text: "Sign in to Veyra" }), form);
  (prefill.serverUrl ? email : server).focus();
}

function renderMfa(): void {
  clear();
  const status = el("div");
  const code = el("input", {
    id: "code",
    type: "text",
    inputmode: "numeric",
    autocomplete: "one-time-code",
    placeholder: "123456",
    required: "",
  });
  const submit = el("button", { type: "submit", class: "primary", text: "Verify" });
  const back = el("button", { type: "button", class: "link", text: "Start over" });
  const form = el("form", {}, [
    el("p", { class: "muted", text: "Enter an authenticator or recovery code." }),
    el("label", {}, ["Code", code]),
    status,
    submit,
    back,
  ]);
  back.addEventListener("click", () => {
    pendingChallenge = null;
    renderSignIn({ serverUrl: state?.serverUrl ?? null });
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (pendingChallenge === null) {
      return;
    }
    submit.disabled = true;
    setMessage(status, "info", "Checking…");
    void (async () => {
      const result = await sendRequest({
        type: "verify",
        challenge: pendingChallenge?.challenge ?? "",
        code: code.value.trim(),
        device,
      });
      submit.disabled = false;
      if (result.status === "ok") {
        pendingChallenge = null;
        await refreshState();
        render();
      } else if (result.status === "mfa") {
        setMessage(status, "error", "Try again.");
      } else {
        setMessage(status, "error", result.detail);
        if (result.code === "challenge_expired") {
          pendingChallenge = null;
          setTimeout(() => renderSignIn({ serverUrl: state?.serverUrl ?? null, error: result.detail }), 1200);
        }
      }
    })();
  });
  app.append(el("h1", { text: "Second factor" }), form);
  code.focus();
}

// ------------------------------------------------------------------ signed in

function connectionTitle(connection: StateResult["connection"]): string {
  switch (connection) {
    case "connected":
      return "Connected: call events are live";
    case "reconnecting":
      return "Reconnecting to the call-event stream";
    case "disabled":
      return "Call events are not available";
  }
}

function recentArrow(call: RecentCall): HTMLElement {
  const missed = call.direction === "in" && !call.answered;
  const glyph = call.direction === "in" ? "↙" : "↗";
  return el("span", {
    class: `arrow ${missed ? "missed" : call.direction}`,
    title: missed ? "Missed" : call.direction === "in" ? "Incoming" : "Outgoing",
    text: glyph,
  });
}

function renderSignedIn(s: StateResult): void {
  clear();
  const status = el("div");
  const extensions = s.extensions.filter((e) => e.is_enabled);
  const defaultId =
    extensions.find((e) => e.id === s.preferences.default_extension_id)?.id ?? extensions[0]?.id ?? "";

  // Header
  const dot = el("span", {
    class: `dot ${s.connection}`,
    title: connectionTitle(s.connection),
    role: "img",
    "aria-label": connectionTitle(s.connection),
  });
  const header = el("div", { class: "header" }, [
    el("div", { class: "who" }, [
      dot,
      el("span", { class: "name", text: s.user?.display_name ?? s.user?.email ?? "Signed in" }),
    ]),
    el("span", { class: "muted small", text: s.serverUrl ? new URL(s.serverUrl).host : "" }),
  ]);

  // Dial row
  const number = el("input", {
    id: "number",
    type: "tel",
    placeholder: "Number to call",
    autocomplete: "off",
  });
  const select = el("select", { id: "extension", title: "Dial from" });
  for (const ext of extensions) {
    const option = el("option", { value: ext.id, text: ext.number });
    option.title = ext.display_name;
    if (ext.id === defaultId) option.selected = true;
    select.append(option);
  }
  const call = el("button", { type: "button", class: "primary", text: "Call" });
  const dial = el("div", { class: "dial" }, [number, ...(extensions.length > 1 ? [select] : []), call]);

  const dialNumber = (value: string): void => {
    if (value.trim() === "") {
      setMessage(status, "error", "Enter a number to call.");
      number.focus();
      return;
    }
    call.disabled = true;
    setMessage(status, "info", "Calling…");
    void (async () => {
      const result = await sendRequest({
        type: "dial",
        number: value,
        ...(select.value ? { extensionId: select.value } : {}),
      });
      call.disabled = false;
      if (result.status === "ok") {
        setMessage(status, "info", result.message);
        number.value = "";
      } else {
        setMessage(status, "error", result.detail);
        if (result.code === "signed_out" || result.code === "not_signed_in") {
          await refreshState();
          render();
        }
      }
    })();
  };
  call.addEventListener("click", () => dialNumber(number.value));
  number.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      dialNumber(number.value);
    }
  });

  // Speed dials
  const sections: HTMLElement[] = [];
  if (s.preferences.speed_dials.length > 0) {
    const chips = el("div", { class: "chips" });
    for (const sd of s.preferences.speed_dials) {
      const chip = el("button", { type: "button", text: sd.label, title: sd.number });
      chip.addEventListener("click", () => dialNumber(sd.number));
      chips.append(chip);
    }
    sections.push(el("section", {}, [el("h2", { text: "Speed dials" }), chips]));
  }

  // Directory
  const search = el("input", {
    id: "search",
    type: "search",
    placeholder: "Search the directory",
    autocomplete: "off",
  });
  const results = el("ul", { class: "list", id: "directory" });
  const renderDirectory = (entries: DirectoryEntry[]): void => {
    results.replaceChildren();
    for (const entry of entries) {
      const who = entry.user_display_name && entry.user_display_name !== entry.name
        ? `${entry.name} · ${entry.user_display_name}`
        : entry.name;
      const item = el("li", { title: `Call ${entry.number}` }, [
        el("span", { class: `reg ${entry.registered ? "on" : ""}`, title: entry.registered ? "Registered" : "Not registered" }),
        el("div", { class: "main" }, [
          el("div", { class: "primary-text", text: who }),
          el("div", { class: "secondary", text: `${entry.number} · ${entry.organization}` }),
        ]),
      ]);
      item.addEventListener("click", () => dialNumber(entry.number));
      results.append(item);
    }
    if (entries.length === 0 && search.value.trim() !== "") {
      results.append(el("li", { class: "muted", text: "No matches." }));
    }
  };
  renderDirectory(lastDirectory);
  const runSearch = (): void => {
    const q = search.value.trim();
    if (q === "") {
      lastDirectory = [];
      renderDirectory([]);
      return;
    }
    void (async () => {
      const result = await sendRequest({ type: "directory", q });
      if (search.value.trim() !== q) {
        return;
      }
      if (result.status === "ok") {
        lastDirectory = result.results;
        renderDirectory(result.results);
      } else {
        setMessage(status, "error", result.detail);
      }
    })();
  };
  search.addEventListener("input", () => {
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 250);
  });
  sections.push(el("section", {}, [el("h2", { text: "Directory" }), search, results]));

  // Recent
  const recentList = el("ul", { class: "list" });
  for (const callEntry of s.recent.slice(0, 10)) {
    const label = callEntry.name && callEntry.name !== callEntry.number ? callEntry.name : callEntry.number ?? "Unknown";
    const item = el("li", { title: callEntry.number ? `Call ${callEntry.number}` : "" }, [
      recentArrow(callEntry),
      el("div", { class: "main" }, [
        el("div", { class: "primary-text", text: label }),
        el("div", {
          class: "secondary",
          text: `${callEntry.number ?? ""}${callEntry.number ? " · " : ""}ext. ${callEntry.extension_number}`,
        }),
      ]),
      el("span", { class: "time", text: relativeTime(callEntry.at) }),
    ]);
    if (callEntry.number) {
      const n = callEntry.number;
      item.addEventListener("click", () => dialNumber(n));
    }
    recentList.append(item);
  }
  if (s.recent.length === 0) {
    recentList.append(el("li", { class: "muted", text: "No calls yet." }));
  }
  sections.push(el("section", {}, [el("h2", { text: "Recent" }), recentList]));

  // Footer
  const options = el("button", { type: "button", class: "link", text: "Options" });
  options.addEventListener("click", () => {
    void chrome.runtime.openOptionsPage();
  });
  const signOut = el("button", { type: "button", class: "link", text: "Sign out" });
  signOut.addEventListener("click", () => {
    signOut.disabled = true;
    void (async () => {
      await sendRequest({ type: "logout" });
      lastDirectory = [];
      await refreshState();
      render();
    })();
  });
  const footer = el("div", { class: "footer" }, [options, signOut]);

  if (extensions.length === 0) {
    setMessage(status, "error", "You have no enabled extension; dialling is not possible.");
  }
  app.append(header, dial, status, ...sections, footer);
  if (document.activeElement === document.body || document.activeElement === null) {
    number.focus();
  }
}

// ------------------------------------------------------------------ render

function render(): void {
  if (pendingChallenge !== null) {
    renderMfa();
    return;
  }
  if (state === null) {
    return;
  }
  if (!state.signedIn) {
    renderSignIn({ serverUrl: state.serverUrl });
    return;
  }
  renderSignedIn(state);
}

/** Re-render on storage changes from the service worker, keeping the user's
 * typing: only when nothing in the dial or search fields has focus. */
function scheduleRefresh(): void {
  if (refreshTimer !== null) return;
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void (async () => {
      const active = document.activeElement;
      const typing = active instanceof HTMLInputElement && active.value !== "";
      if (typing || pendingChallenge !== null) {
        return;
      }
      await refreshState();
      render();
    })();
  }, 200);
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if ("recent" in changes || "connection" in changes || "extensions" in changes || "token" in changes || "preferences" in changes) {
    scheduleRefresh();
  }
});

void (async () => {
  try {
    await refreshState();
    render();
  } catch (error) {
    clear();
    app.append(message("error", error instanceof Error ? error.message : String(error)));
  }
})();
