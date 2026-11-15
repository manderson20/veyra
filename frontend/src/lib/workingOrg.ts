// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The organization this browser tab works in (docs/MULTI_TENANCY_MSP.md §10a).
 *
 * Kept per tab (sessionStorage), so client A can be open in one tab and
 * client B in another. A link carries it as ``?org=<short name>``; a new tab
 * starts in the user's last choice (localStorage). Empty means "System (all
 * organizations)". The API client sends it as ``X-Veyra-Organization`` and
 * the server narrows the request to that organization.
 */

export const ORG_HEADER = "X-Veyra-Organization";
const TAB_KEY = "veyra.org";
const LAST_KEY = "veyra.lastOrg";
const SYSTEM = "-";

interface Stores {
  tab: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  last: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null;
  search: () => string;
}

function browserStores(): Stores {
  const safe = (get: () => Storage) => {
    try {
      return get();
    } catch {
      return null;
    }
  };
  return {
    tab: typeof window === "undefined" ? null : safe(() => window.sessionStorage),
    last: typeof window === "undefined" ? null : safe(() => window.localStorage),
    search: () => (typeof window === "undefined" ? "" : window.location.search),
  };
}

function read(store: Stores["tab"], key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(store: Stores["tab"], key: string, value: string | null): void {
  try {
    if (value === null) store?.removeItem(key);
    else store?.setItem(key, value);
  } catch {
    /* storage blocked: the choice lasts until the page reloads */
  }
}

/** The short name of the organization this tab works in; "" = System. */
export function workingOrg(stores: Stores = browserStores()): string {
  const fromLink = new URLSearchParams(stores.search()).get("org");
  if (fromLink !== null) {
    const v = fromLink.trim().toLowerCase();
    write(stores.tab, TAB_KEY, v || SYSTEM);
    return v;
  }
  let v = read(stores.tab, TAB_KEY);
  if (v === null) {
    v = read(stores.last, LAST_KEY) ?? SYSTEM;
    write(stores.tab, TAB_KEY, v);
  }
  return v === SYSTEM ? "" : v;
}

/** Choose the organization for this tab ("" = System); new tabs start there too. */
export function setWorkingOrg(slug: string, stores: Stores = browserStores()): void {
  const v = slug.trim().toLowerCase() || SYSTEM;
  write(stores.tab, TAB_KEY, v);
  write(stores.last, LAST_KEY, v);
}

/** Forget the choice (the organization is no longer available to the user). */
export function clearWorkingOrg(stores: Stores = browserStores()): void {
  write(stores.tab, TAB_KEY, SYSTEM);
  write(stores.last, LAST_KEY, null);
}

/** Where to go after switching: the same page in the new organization; an
 * open object (a ``/view/`` page) goes back to its list. */
export function pathAfterSwitch(pathname: string, slug: string): string {
  const base = pathname.replace(/\/view\/?$/, "/");
  return slug ? `${base}?org=${encodeURIComponent(slug)}` : `${base}?org=`;
}
