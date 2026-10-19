// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { favouritesFrom } from "./favourites";

describe("favouritesFrom", () => {
  it("orders by speed-dial slot, then name, and prefers the work number", () => {
    const out = favouritesFrom([
      { id: "1", name: "Zed", numbers: [{ label: "mobile", number: "5551" }], favourite: true, speed_dial: null },
      { id: "2", name: "Amy", numbers: [{ label: "home", number: "5552" }, { label: "work", number: "1002" }], favourite: true, speed_dial: null },
      { id: "3", name: "Nurse", numbers: [{ label: "work", number: "1003" }], favourite: true, speed_dial: 2 },
      { id: "4", name: "Not a favourite", numbers: [{ label: "work", number: "1004" }], favourite: false, speed_dial: 1 },
      { id: "5", name: "No number", numbers: [], favourite: true, speed_dial: 1 },
    ]);
    expect(out).toEqual([
      { label: "Nurse", number: "1003", slot: 2 },
      { label: "Amy", number: "1002", slot: null },
      { label: "Zed", number: "5551", slot: null },
    ]);
  });
});
