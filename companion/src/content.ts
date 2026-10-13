// SPDX-License-Identifier: AGPL-3.0-or-later
/** Veyra Companion content script: registered at run time when the user
 * enables "Handle tel: links". Clicks on `tel:` links are dialled through
 * Veyra instead of being handed to the operating system. No imports: this
 * file is injected as a classic script. */

(() => {
  const FLAG = "__veyraTelLinks";
  const w = window as Window & { [FLAG]?: boolean };
  if (w[FLAG]) {
    return;
  }
  w[FLAG] = true;

  function telTarget(target: EventTarget | null): HTMLAnchorElement | null {
    if (!(target instanceof Element)) {
      return null;
    }
    const anchor = target.closest("a[href]");
    if (!(anchor instanceof HTMLAnchorElement)) {
      return null;
    }
    const href = anchor.getAttribute("href") ?? "";
    return /^tel:/i.test(href.trim()) ? anchor : null;
  }

  function numberFrom(href: string): string {
    let raw = href.trim().replace(/^tel:/i, "");
    try {
      raw = decodeURIComponent(raw);
    } catch {
      // keep as is
    }
    return raw.split(/[;?]/)[0] ?? "";
  }

  document.addEventListener(
    "click",
    (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      const anchor = telTarget(event.target);
      if (anchor === null) {
        return;
      }
      const href = anchor.href;
      const number = numberFrom(href);
      if (number === "") {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const request = { type: "dial", number };
      chrome.runtime.sendMessage(request, (response: unknown) => {
        if (chrome.runtime.lastError) {
          return;
        }
        const r = response as { status?: string; code?: string } | undefined;
        if (r && r.status === "error" && r.code === "not_signed_in") {
          // Nobody is signed in: let the operating system have the link.
          window.location.assign(href);
        }
      });
    },
    true,
  );
})();
