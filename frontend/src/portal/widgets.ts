// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The portal's widget registry (docs/USER_PORTAL.md §10): what can be placed
 * on the canvas, with default and minimum sizes in grid units (12 columns,
 * 40 px rows). Modules may contribute entries in a later version.
 */
import type { Size } from "./layout";

export type WidgetNeeds = "extension" | "box" | null;

export interface WidgetManifest {
  key: string;
  title: string;
  description: string;
  icon: string;
  defaultSize: Size;
  minSize: Size;
  /** The data the widget shows one of; an instance per extension or box. */
  needs: WidgetNeeds;
  /** Administrators may want to force it onto every user's canvas. */
  lockable?: boolean;
}

export const WIDGETS: WidgetManifest[] = [
  { key: "phone", title: "My phone", description: "Registration, Do Not Disturb, forwards and follow-me of one extension.", icon: "phone", defaultSize: { w: 6, h: 9 }, minSize: { w: 4, h: 6 }, needs: "extension" },
  { key: "presence", title: "Presence", description: "Your state for colleagues, with automatic actions.", icon: "users", defaultSize: { w: 6, h: 6 }, minSize: { w: 4, h: 5 }, needs: "extension" },
  { key: "voicemail", title: "Voicemail", description: "Messages and greetings of one box.", icon: "voicemail", defaultSize: { w: 6, h: 10 }, minSize: { w: 4, h: 6 }, needs: "box" },
  { key: "calls", title: "Recent calls", description: "Your calls with call back and recordings.", icon: "history", defaultSize: { w: 6, h: 10 }, minSize: { w: 4, h: 6 }, needs: null },
  { key: "contacts", title: "Contacts", description: "Personal contacts and speed dials.", icon: "users", defaultSize: { w: 6, h: 10 }, minSize: { w: 4, h: 6 }, needs: null },
  { key: "colleagues", title: "Colleagues", description: "Who is available, on a call or away.", icon: "users", defaultSize: { w: 6, h: 10 }, minSize: { w: 4, h: 6 }, needs: null },
  { key: "keys", title: "Phone keys", description: "Your phones' keys: the locked ones and the slots you may set.", icon: "keypad", defaultSize: { w: 12, h: 8 }, minSize: { w: 6, h: 5 }, needs: null },
  { key: "codes", title: "Codes you can dial", description: "Feature codes available from your phone.", icon: "keypad", defaultSize: { w: 6, h: 6 }, minSize: { w: 4, h: 4 }, needs: null },
  { key: "announce", title: "Announcement", description: "A note from your administrators, shown to everyone (locked by the template).", icon: "megaphone", defaultSize: { w: 12, h: 3 }, minSize: { w: 4, h: 2 }, needs: null, lockable: true },
];

export const widgetByKey = (key: string): WidgetManifest | undefined => WIDGETS.find((w) => w.key === key);

/** The layout every user starts with: what My Phone showed before the canvas. */
export const DEFAULT_LAYOUT = {
  version: 1 as const,
  tabs: [
    {
      id: "home",
      name: "Home",
      widgets: [
        { key: "phone", instance: "first", x: 0, y: 0, w: 6, h: 9 },
        { key: "presence", instance: "first", x: 6, y: 0, w: 6, h: 6 },
        { key: "voicemail", instance: "first", x: 6, y: 6, w: 6, h: 10 },
        { key: "calls", instance: "default", x: 0, y: 9, w: 6, h: 10 },
        { key: "contacts", instance: "default", x: 0, y: 19, w: 6, h: 10 },
        { key: "colleagues", instance: "default", x: 6, y: 16, w: 6, h: 10 },
        { key: "keys", instance: "default", x: 0, y: 29, w: 12, h: 8 },
        { key: "codes", instance: "default", x: 0, y: 37, w: 6, h: 6 },
      ],
    },
  ],
};
