// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { emergencyNotice, parseStreamEvent } from "./events";

describe("emergency alerts", () => {
  it("parses the alert and words the pop-up", () => {
    const e = parseStreamEvent(JSON.stringify({
      type: "emergency", test: false, number: "911", extension_number: "1001",
      extension_name: "Front Office", site: "Main Campus", location: "Room 101, first floor", at: "2026-10-20T09:00:00+00:00",
    }));
    expect(e?.type).toBe("emergency");
    if (e?.type !== "emergency") throw new Error("not parsed");
    expect(emergencyNotice(e)).toEqual({
      title: "EMERGENCY call to 911",
      message: "From Front Office (1001) at Main Campus: Room 101, first floor.",
    });
    expect(emergencyNotice({ ...e, test: true, extension_name: null, site: null }).title).toBe("TEST: EMERGENCY call to 911");
    expect(emergencyNotice({ ...e, extension_name: null, site: null }).message).toBe("From 1001: Room 101, first floor.");
  });
});
