// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Values an administrator preloads through browser policy (Google Admin Console
 * "Policy for extensions", Windows/macOS Chrome policies). Read from
 * chrome.storage.managed; absent when the extension is not managed.
 */
export interface ManagedConfig {
  serverUrl: string | null;
  dialPrefix: string | null;
  /** A sign-in provider id: sign in through it, silently when possible. */
  ssoProvider: string | null;
}

export async function readManaged(): Promise<ManagedConfig> {
  try {
    const got = (await chrome.storage.managed.get(["serverUrl", "dialPrefix", "ssoProvider"])) as Record<
      string,
      unknown
    >;
    const serverUrl = typeof got.serverUrl === "string" && got.serverUrl.trim() ? got.serverUrl.trim() : null;
    const dialPrefix =
      typeof got.dialPrefix === "string" && /^[0-9]{0,8}$/.test(got.dialPrefix.trim()) ? got.dialPrefix.trim() : null;
    const ssoProvider =
      typeof got.ssoProvider === "string" && /^[0-9a-f-]{36}$/i.test(got.ssoProvider.trim())
        ? got.ssoProvider.trim()
        : null;
    return { serverUrl, dialPrefix, ssoProvider };
  } catch {
    return { serverUrl: null, dialPrefix: null, ssoProvider: null };
  }
}
