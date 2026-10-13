// SPDX-License-Identifier: AGPL-3.0-or-later
/** The options page: dial prefix, default extension, notifications, tel:
 * links and the speed-dial editor. Everything is saved to the server. */

import "./options.css";
import { byId, el } from "../lib/format";
import { sendRequest, type StateResult } from "../lib/messages";
import type { SpeedDial } from "../lib/types";

const MAX_SPEED_DIALS = 50;
const TEL_PERMISSIONS: chrome.permissions.Permissions = {
  permissions: ["scripting"],
  origins: ["https://*/*"],
};

const app = byId<HTMLElement>("app");

function message(kind: "error" | "info", text: string): HTMLParagraphElement {
  return el("p", { class: `msg ${kind}`, role: kind === "error" ? "alert" : "status", text });
}

function renderSignedOut(serverUrl: string | null): void {
  app.replaceChildren(
    el("h1", { text: "Veyra Companion" }),
    el("p", { class: "muted" }, [
      "You are not signed in. Open the Veyra Companion popup from the toolbar to sign in",
      serverUrl ? ` to ${serverUrl}.` : ".",
    ]),
  );
}

function speedDialRow(dial: SpeedDial, onRemove: () => void): HTMLDivElement {
  const label = el("input", {
    type: "text",
    class: "label",
    placeholder: "Label",
    maxlength: "40",
    value: dial.label,
    "aria-label": "Speed dial label",
  });
  const number = el("input", {
    type: "tel",
    placeholder: "Number",
    maxlength: "32",
    value: dial.number,
    "aria-label": "Speed dial number",
  });
  const remove = el("button", { type: "button", class: "remove", title: "Remove", "aria-label": "Remove speed dial", text: "✕" });
  const row = el("div", { class: "row speed-dial" }, [label, number, remove]);
  remove.addEventListener("click", () => {
    row.remove();
    onRemove();
  });
  return row;
}

function readSpeedDials(container: HTMLElement): SpeedDial[] {
  const out: SpeedDial[] = [];
  for (const row of container.querySelectorAll<HTMLElement>(".speed-dial")) {
    const inputs = row.querySelectorAll("input");
    const label = inputs[0]?.value.trim() ?? "";
    const number = inputs[1]?.value.trim() ?? "";
    if (label === "" && number === "") {
      continue;
    }
    out.push({ label, number });
  }
  return out;
}

async function telPermissionGranted(): Promise<boolean> {
  try {
    return await chrome.permissions.contains(TEL_PERMISSIONS);
  } catch {
    return false;
  }
}

function renderOptions(state: StateResult, telGranted: boolean): void {
  const prefs = state.preferences;
  const status = el("div");

  const prefix = el("input", {
    id: "dial_prefix",
    type: "text",
    inputmode: "numeric",
    pattern: "[0-9]*",
    maxlength: "8",
    placeholder: "none",
    value: prefs.dial_prefix,
  });
  prefix.addEventListener("input", () => {
    prefix.value = prefix.value.replace(/[^0-9]/g, "").slice(0, 8);
  });

  const extension = el("select", { id: "default_extension" });
  extension.append(el("option", { value: "", text: "First enabled extension" }));
  for (const ext of state.extensions) {
    const option = el("option", {
      value: ext.id,
      text: `${ext.number} · ${ext.display_name}${ext.is_enabled ? "" : " (disabled)"}`,
    });
    if (ext.id === prefs.default_extension_id) option.selected = true;
    extension.append(option);
  }

  const notifyIncoming = el("input", { type: "checkbox", id: "notify_incoming" });
  notifyIncoming.checked = prefs.notify_incoming;
  const notifyMissed = el("input", { type: "checkbox", id: "notify_missed" });
  notifyMissed.checked = prefs.notify_missed;
  const telLinks = el("input", { type: "checkbox", id: "handle_tel_links" });
  telLinks.checked = prefs.handle_tel_links;
  const telHint = el("p", { class: "hint" });
  const updateTelHint = (granted: boolean): void => {
    telHint.textContent = telLinks.checked && !granted
      ? "The permission to read and change data on websites was not granted in this browser, so tel: links are not intercepted here."
      : "Clicks on tel: links on HTTPS pages ring your phone through Veyra instead of opening another application.";
  };
  updateTelHint(telGranted);
  telLinks.addEventListener("change", () => {
    if (!telLinks.checked) {
      updateTelHint(telGranted);
      return;
    }
    // Must run inside the click's user gesture: no awaits before request().
    const request = telGranted ? Promise.resolve(true) : chrome.permissions.request(TEL_PERMISSIONS);
    void request
      .then((granted) => {
        telGranted = granted;
        if (!granted) {
          telLinks.checked = false;
          status.replaceChildren(
            message("error", "Without that permission the extension cannot see tel: links; the setting stays off."),
          );
        }
        updateTelHint(granted);
      })
      .catch((error: unknown) => {
        telLinks.checked = false;
        status.replaceChildren(message("error", error instanceof Error ? error.message : String(error)));
      });
  });

  const speedDials = el("div", { class: "speed-dials" });
  const addButton = el("button", { type: "button", text: "Add speed dial" });
  const updateAdd = (): void => {
    addButton.disabled = speedDials.querySelectorAll(".speed-dial").length >= MAX_SPEED_DIALS;
  };
  const addRow = (dial: SpeedDial): void => {
    speedDials.append(speedDialRow(dial, updateAdd));
    updateAdd();
  };
  for (const dial of prefs.speed_dials) addRow(dial);
  addButton.addEventListener("click", () => {
    addRow({ label: "", number: "" });
    const rows = speedDials.querySelectorAll<HTMLInputElement>(".speed-dial input");
    rows[rows.length - 2]?.focus();
  });

  const save = el("button", { type: "submit", class: "primary", text: "Save" });
  const signOut = el("button", { type: "button", class: "danger", text: "Sign out" });
  signOut.addEventListener("click", () => {
    signOut.disabled = true;
    void (async () => {
      await sendRequest({ type: "logout" });
      renderSignedOut(state.serverUrl);
    })();
  });

  const form = el("form", {}, [
    el("section", {}, [
      el("h2", { text: "Dialling" }),
      el("label", { class: "field" }, [
        "Dial prefix for external numbers",
        prefix,
        el("span", { class: "muted small", text: "Digits only, at most 8. Prepended to numbers longer than an extension." }),
      ]),
      el("label", { class: "field" }, ["Default extension", extension]),
    ]),
    el("section", {}, [
      el("h2", { text: "Notifications" }),
      el("label", { class: "check" }, [notifyIncoming, "Show incoming calls"]),
      el("label", { class: "check" }, [notifyMissed, "Show missed calls with a Call back button"]),
    ]),
    el("section", {}, [
      el("h2", { text: "Websites" }),
      el("label", { class: "check" }, [telLinks, "Handle tel: links"]),
      telHint,
    ]),
    el("section", {}, [
      el("h2", { text: `Speed dials (up to ${MAX_SPEED_DIALS})` }),
      speedDials,
      el("div", {}, [addButton]),
    ]),
    status,
    el("div", { class: "actions" }, [
      save,
      el("span", { class: "muted small", text: state.serverUrl ?? "" }),
      signOut,
    ]),
  ]);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const dials = readSpeedDials(speedDials);
    const incomplete = dials.find((d) => d.label === "" || d.number === "");
    if (incomplete) {
      status.replaceChildren(message("error", "Every speed dial needs both a label and a number."));
      return;
    }
    save.disabled = true;
    status.replaceChildren(message("info", "Saving…"));
    void (async () => {
      const result = await sendRequest({
        type: "savePreferences",
        companion: {
          speed_dials: dials,
          dial_prefix: prefix.value,
          default_extension_id: extension.value || null,
          notify_incoming: notifyIncoming.checked,
          notify_missed: notifyMissed.checked,
          handle_tel_links: telLinks.checked,
        },
      });
      save.disabled = false;
      if (result.status === "ok") {
        status.replaceChildren(message("info", "Saved."));
        setTimeout(() => {
          if (status.textContent === "Saved.") status.replaceChildren();
        }, 2500);
      } else {
        status.replaceChildren(message("error", result.detail));
        if (result.code === "signed_out" || result.code === "not_signed_in") {
          renderSignedOut(state.serverUrl);
        }
      }
    })();
  });

  app.replaceChildren(
    el("div", {}, [
      el("h1", { text: "Veyra Companion" }),
      el("p", { class: "muted small", text: `Signed in as ${state.user?.display_name ?? state.user?.email ?? ""}. Settings are stored on the server and follow you to other browsers.` }),
    ]),
    form,
  );
}

void (async () => {
  try {
    const state = await sendRequest({ type: "state" });
    if (!state.signedIn) {
      renderSignedOut(state.serverUrl);
      return;
    }
    renderOptions(state, await telPermissionGranted());
  } catch (error) {
    app.replaceChildren(message("error", error instanceof Error ? error.message : String(error)));
  }
})();
