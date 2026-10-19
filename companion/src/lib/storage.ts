// SPDX-License-Identifier: AGPL-3.0-or-later
/** Typed wrapper over `chrome.storage.local`. Everything the extension keeps
 * on this machine lives here; personal settings live on the server. */

import type {
  CompanionPreferences,
  CompanionUser,
  ConnectionState,
  MyExtension,
  RecentCall,
} from "./types";
import type { Favourite } from "./favourites";

export interface StoredState {
  serverUrl?: string;
  token?: string;
  tokenId?: string;
  user?: CompanionUser;
  extensions?: MyExtension[];
  preferences?: CompanionPreferences;
  recent?: RecentCall[];
  /** Mirrored by the service worker so the popup can show the dot. */
  connection?: ConnectionState;
  /** Missed-call notifications waiting for a "Call back" click: id -> number. */
  callbacks?: Record<string, string>;
  /** Favourite contacts from My Phone, cached for the popup when offline. */
  favourites?: Favourite[];
}

export type StoredKey = keyof StoredState;

export const STORED_KEYS: readonly StoredKey[] = [
  "serverUrl",
  "token",
  "tokenId",
  "user",
  "extensions",
  "preferences",
  "recent",
  "connection",
  "callbacks",
  "favourites",
];

export async function getStored(): Promise<StoredState> {
  const raw = await chrome.storage.local.get([...STORED_KEYS]);
  return raw as StoredState;
}

export async function getStoredKey<K extends StoredKey>(key: K): Promise<StoredState[K]> {
  const raw = (await chrome.storage.local.get(key)) as StoredState;
  return raw[key];
}

export async function setStored(patch: Partial<StoredState>): Promise<void> {
  await chrome.storage.local.set(patch);
}

export async function removeStored(keys: StoredKey[]): Promise<void> {
  await chrome.storage.local.remove(keys);
}

/** Forget the sign-in but keep the server address (it is typed rarely). */
export async function clearSignIn(): Promise<void> {
  await chrome.storage.local.remove([
    "token",
    "tokenId",
    "user",
    "extensions",
    "preferences",
    "recent",
    "callbacks",
  ]);
}
