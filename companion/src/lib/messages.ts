// SPDX-License-Identifier: AGPL-3.0-or-later
/** The message protocol between the popup, options page, content script and
 * the service worker. Type-only for the service worker; the pages use
 * `sendRequest`. */

import type {
  CompanionPreferences,
  CompanionUser,
  ConnectionState,
  DirectoryEntry,
  MyExtension,
  RecentCall,
  VoicemailItem,
} from "./types";
import type { Favourite } from "./favourites";
import type { SsoProvider } from "./sso";

export interface ErrorResult {
  status: "error";
  code: string;
  detail: string;
}

export type LoginRequest = {
  type: "login";
  serverUrl: string;
  email: string;
  password: string;
  device: string;
};
export type SsoLoginRequest = {
  type: "ssoLogin";
  serverUrl: string;
  providerId: string;
  device: string;
};
export type VerifyRequest = { type: "verify"; challenge: string; code: string; device: string };
export type LogoutRequest = { type: "logout" };
export type DialRequest = { type: "dial"; number: string; extensionId?: string };
export type DirectoryRequest = { type: "directory"; q: string };
export type SavePreferencesRequest = { type: "savePreferences"; companion: CompanionPreferences };
export type StateRequest = { type: "state" };
/** Copy the Companion's own speed dials to favourite contacts on My Phone. */
export type MoveSpeedDialsRequest = { type: "moveSpeedDials" };
/** New voicemail of the user's boxes; a message's audio; call me to play (#136). */
export type VoicemailRequest = { type: "voicemail" };
export type VoicemailAudioRequest = { type: "voicemailAudio"; boxId: string; number: number; folder: string };
export type VoicemailCallRequest = { type: "voicemailCall"; boxId: string; number: number; folder: string; msgId: string };

export type Request =
  | LoginRequest
  | SsoLoginRequest
  | VerifyRequest
  | LogoutRequest
  | DialRequest
  | DirectoryRequest
  | SavePreferencesRequest
  | StateRequest
  | MoveSpeedDialsRequest
  | VoicemailRequest
  | VoicemailAudioRequest
  | VoicemailCallRequest;

export type LoginResult =
  | { status: "ok" }
  | { status: "mfa"; challenge: string; methods: number; enrol: boolean }
  | ErrorResult;

export type LogoutResult = { status: "ok" };
export type DialResult = { status: "ok"; message: string } | ErrorResult;
export type DirectoryResult = { status: "ok"; results: DirectoryEntry[] } | ErrorResult;
export type VoicemailResult = { status: "ok"; messages: VoicemailItem[] } | ErrorResult;
export type VoicemailAudioResult = { status: "ok"; dataUrl: string } | ErrorResult;
export type VoicemailCallResult = { status: "ok"; message: string } | ErrorResult;
export type MoveSpeedDialsResult =
  | { status: "ok"; moved: number; preferences: CompanionPreferences }
  | ErrorResult;
export type SavePreferencesResult =
  | { status: "ok"; preferences: CompanionPreferences }
  | ErrorResult;

export interface StateResult {
  status: "ok";
  signedIn: boolean;
  serverUrl: string | null;
  /** Set when an administrator preloaded the server through browser policy. */
  managedServerUrl: string | null;
  /** Sign-in providers of the server, shown as buttons while signed out. */
  providers: SsoProvider[];
  user: CompanionUser | null;
  extensions: MyExtension[];
  preferences: CompanionPreferences;
  /** Favourite contacts from My Phone; the popup falls back to the old
   * `preferences.speed_dials` while there are none. */
  favourites: Favourite[];
  recent: RecentCall[];
  connection: ConnectionState;
}

export type ResponseFor<R extends Request> = R extends LoginRequest | VerifyRequest | SsoLoginRequest
  ? LoginResult
  : R extends LogoutRequest
    ? LogoutResult
    : R extends DialRequest
      ? DialResult
      : R extends DirectoryRequest
        ? DirectoryResult
        : R extends SavePreferencesRequest
          ? SavePreferencesResult
          : R extends StateRequest
            ? StateResult
            : R extends MoveSpeedDialsRequest
              ? MoveSpeedDialsResult
              : R extends VoicemailRequest
                ? VoicemailResult
                : R extends VoicemailAudioRequest
                  ? VoicemailAudioResult
                  : R extends VoicemailCallRequest
                    ? VoicemailCallResult
                    : never;

export type Response =
  | LoginResult
  | LogoutResult
  | DialResult
  | DirectoryResult
  | SavePreferencesResult
  | MoveSpeedDialsResult
  | VoicemailResult
  | VoicemailAudioResult
  | VoicemailCallResult
  | StateResult;

export function isRequest(value: unknown): value is Request {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** Send a typed request to the service worker and wait for its answer. */
export async function sendRequest<R extends Request>(request: R): Promise<ResponseFor<R>> {
  const response: unknown = await chrome.runtime.sendMessage(request);
  if (response === undefined || response === null) {
    throw new Error("The extension's background worker did not answer.");
  }
  return response as ResponseFor<R>;
}
