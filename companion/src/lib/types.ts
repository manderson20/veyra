// SPDX-License-Identifier: AGPL-3.0-or-later
/** Server-side shapes the extension consumes (docs/COMPANION.md §3–§4,
 * field names from backend/veyra/api/v1/{auth_companion,me,directory,calls}.py). */

export interface CompanionUser {
  id: string;
  email: string;
  display_name: string;
}

export interface RegistrationState {
  registered: boolean;
  channels: number;
}

/** `GET /me/extensions` row, also embedded in the login response. */
export interface MyExtension {
  id: string;
  number: string;
  display_name: string;
  organization_id: string;
  organization_name: string;
  is_enabled: boolean;
  registration: RegistrationState | null;
}

export interface SpeedDial {
  label: string;
  number: string;
}

/** The `companion` section of `GET /me/preferences`. */
export interface CompanionPreferences {
  speed_dials: SpeedDial[];
  dial_prefix: string;
  default_extension_id: string | null;
  notify_incoming: boolean;
  notify_missed: boolean;
  handle_tel_links: boolean;
}

export const DEFAULT_PREFERENCES: CompanionPreferences = {
  speed_dials: [],
  dial_prefix: "",
  default_extension_id: null,
  notify_incoming: true,
  notify_missed: true,
  handle_tel_links: false,
};

export interface PreferencesOut {
  companion: CompanionPreferences;
  updated_at: string | null;
}

/** `POST /auth/companion/login` 200 body. */
export interface CompanionSession {
  token: string;
  token_id: string;
  expires_at: string;
  user: CompanionUser;
  permissions: string[];
  extensions: MyExtension[];
  installation_name: string;
  version: string;
}

/** `POST /auth/companion/login` 202 body. */
export interface CompanionChallenge {
  challenge: string;
  enrol: boolean;
  methods: number;
  expires_at: string;
}

export interface DirectoryEntry {
  type: "extension";
  id: string;
  number: string;
  name: string;
  organization: string;
  user_display_name: string | null;
  user_email: string | null;
  registered: boolean | null;
}

export interface DirectoryOut {
  results: DirectoryEntry[];
  total: number;
}

export interface TicketOut {
  ticket: string;
  expires_in: number;
  url: string;
}

export interface OriginateOut {
  channel_id: string;
  extension_number: string;
  number: string;
  message: string;
}

/** One line of the "recent calls" list, derived from the event stream. */
export interface RecentCall {
  channel_id: string;
  number: string | null;
  name: string | null;
  direction: "in" | "out";
  answered: boolean;
  at: string;
  extension_number: string;
}

/** What the popup shows next to the user's name. */
export type ConnectionState = "connected" | "reconnecting" | "disabled";
