// SPDX-License-Identifier: AGPL-3.0-or-later
/** Single sign-on through Veyra's identity providers (docs/INTEGRATIONS.md
 * §1.6): the browser's own web-auth flow, a PKCE pair the extension keeps, and
 * a one-time code exchanged for the usual Companion token. */

export interface SsoProvider {
  id: string;
  kind: "google" | "microsoft" | "oidc";
  name: string;
}

function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function newVerifier(): string {
  const bytes = new Uint8Array(48);
  crypto.getRandomValues(bytes);
  return b64url(bytes);
}

export async function challengeOf(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return b64url(new Uint8Array(digest));
}

export function startUrl(
  origin: string,
  providerId: string,
  redirectUri: string,
  challenge: string,
  silent: boolean,
): string {
  const q = new URLSearchParams({ client: "companion", redirect_uri: redirectUri, code_challenge: challenge });
  if (silent) q.set("silent", "true");
  return `${origin}/api/v1/auth/sso/${encodeURIComponent(providerId)}/start?${q.toString()}`;
}

export type SsoRedirect = { code: string } | { error: string; message: string };

/** What the server put on the chromiumapp.org address. */
export function parseRedirect(url: string, expectedPrefix: string): SsoRedirect {
  if (!url.startsWith(expectedPrefix)) {
    return { error: "bad_redirect", message: "The sign-in returned to an unexpected address." };
  }
  const q = new URL(url).searchParams;
  const code = q.get("code");
  if (code) return { code };
  return { error: q.get("error") ?? "failed", message: q.get("message") ?? "Sign-in did not complete." };
}

/** Errors that only mean "the person has to click": the button stays. */
export function needsInteraction(error: string): boolean {
  return ["login_required", "interaction_required", "consent_required", "account_selection_required", "cancelled"].includes(error);
}
