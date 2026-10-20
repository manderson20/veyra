// SPDX-License-Identifier: AGPL-3.0-or-later
import type { MyDevice, UserKeyInput } from "./types";

/** The keys every open slot of a phone holds now, with one slot changed: the
 * API replaces the whole set, a slot left out is emptied. */
export function slotsWith(device: MyDevice, index: number, key: UserKeyInput | null): Record<string, UserKeyInput | null> {
  const keys: Record<string, UserKeyInput | null> = {};
  for (const s of device.slots) {
    if (s.kind !== "user" || !s.type || s.index === index) continue;
    keys[String(s.index)] = { type: s.type as UserKeyInput["type"], label: s.label, value: s.value ?? "" };
  }
  keys[String(index)] = key;
  return keys;
}
