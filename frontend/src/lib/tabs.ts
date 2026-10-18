// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tabs across the top of an object page, addressed by a `tab` query
 * parameter so a link lands on the right tab (issue #81). Pure helpers;
 * `useUrlTab` in hooks/ wires them to the router.
 */

/** The tab the URL names, or the fallback when it names none or an unknown one. */
export function resolveTab(param: string | null | undefined, ids: readonly string[], fallback: string): string {
  return param && ids.includes(param) ? param : fallback;
}

/**
 * The query string with `tab` set to `tab`; the parameter is dropped for the
 * fallback tab so the plain link stays canonical. Other parameters are kept.
 */
export function withTab(search: string, tab: string, fallback: string): string {
  const params = new URLSearchParams(search);
  if (tab === fallback) params.delete("tab");
  else params.set("tab", tab);
  return params.toString();
}
