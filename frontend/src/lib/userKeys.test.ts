// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import type { MyDevice } from "./types";
import { slotsWith } from "./userKeys";

describe("slotsWith", () => {
  it("keeps the other filled slots when one changes", () => {
    const device = {
      slots: [
        { index: 1, kind: "locked", type: "line", label: null, value: "1" },
        { index: 3, kind: "user", type: "blf", label: "Office", value: "1002" },
        { index: 4, kind: "user", type: null, label: null, value: null },
      ],
    } as unknown as MyDevice;
    expect(slotsWith(device, 4, { type: "speed_dial", label: "Bus", value: "5551234" })).toEqual({
      "3": { type: "blf", label: "Office", value: "1002" },
      "4": { type: "speed_dial", label: "Bus", value: "5551234" },
    });
    expect(slotsWith(device, 3, null)).toEqual({ "3": null });
  });
});
