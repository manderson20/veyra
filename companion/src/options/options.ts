// SPDX-License-Identifier: AGPL-3.0-or-later
/** The options page: dial prefix, default extension, notifications, tel:
 * links, and moving old speed dials to My Phone favourites. Everything is
 * saved to the server. */

import "./options.css";
import { byId, el } from "../lib/format";
import { sendRequest, type StateResult } from "../lib/messages";

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

  // Favourites live on My Phone (#128); old Companion speed dials can be moved there.
  const myPhone = state.serverUrl ? `${state.serverUrl.replace(/\/$/, "")}/my-phone/` : null;
  const favouritesInfo = el("p", { class: "muted" }, [
    "The popup shows your favourite contacts from My Phone",
    myPhone ? " (" : ".",
    ...(myPhone ? [el("a", { href: myPhone, target: "_blank", rel: "noopener", text: "open My Phone" }), ")."] : []),
    " Mark a contact with the star to add it.",
  ]);
  const legacy = prefs.speed_dials;
  const moveButton = el("button", { type: "button", text: `Move my ${legacy.length} speed dial${legacy.length === 1 ? "" : "s"} to My Phone` });
  const moveStatus = el("div");
  moveButton.addEventListener("click", () => {
    moveButton.disabled = true;
    moveStatus.replaceChildren(message("info", "Moving…"));
    void (async () => {
      const result = await sendRequest({ type: "moveSpeedDials" });
      if (result.status === "ok") {
        moveStatus.replaceChildren(message("info", `${result.moved} speed dial${result.moved === 1 ? "" : "s"} are now favourite contacts on My Phone.`));
        moveButton.remove();
      } else {
        moveButton.disabled = false;
        moveStatus.replaceChildren(message("error", result.detail));
      }
    })();
  });
  const favouritesSection = el("section", {}, [
    el("h2", { text: "Favourites" }),
    favouritesInfo,
    ...(legacy.length
      ? [el("p", { class: "muted small", text: `This Companion still has ${legacy.length} speed dial${legacy.length === 1 ? "" : "s"} of its own; the popup shows them until you have favourites on My Phone.` }), el("div", {}, [moveButton]), moveStatus]
      : []),
  ]);

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
    favouritesSection,
    status,
    el("div", { class: "actions" }, [
      save,
      el("span", { class: "muted small", text: state.serverUrl ?? "" }),
      signOut,
    ]),
  ]);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    save.disabled = true;
    status.replaceChildren(message("info", "Saving…"));
    void (async () => {
      const result = await sendRequest({
        type: "savePreferences",
        companion: {
          speed_dials: prefs.speed_dials,
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
