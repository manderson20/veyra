// SPDX-License-Identifier: AGPL-3.0-or-later
/** Small formatting helpers for the pages. */

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) {
    return "";
  }
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Normalise what the user typed into `https://host[:port]`; null when it is
 * not an HTTPS origin. Mirrors `normalizeServerUrl` in api.ts for the popup,
 * which must not share runtime modules with the service worker bundle. */
export function serverOrigin(input: string): string | null {
  let text = input.trim();
  if (text === "") return null;
  if (!/^[a-z]+:\/\//i.test(text)) text = `https://${text}`;
  try {
    const url = new URL(text);
    return url.protocol === "https:" && url.hostname !== "" ? url.origin : null;
  } catch {
    return null;
  }
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  children: (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child);
  }
  return node;
}

export function byId<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (node === null) {
    throw new Error(`Missing element #${id}`);
  }
  return node as T;
}
