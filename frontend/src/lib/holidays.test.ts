// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { describeHoliday, formatHoliday, holidayComplete, parseHoliday } from "./holidays";

describe("holidays", () => {
  it("round-trips every stored form", () => {
    for (const v of ["12-25", "12-21..01-02", "2026-11-27", "2026-12-21..2027-01-02", "4-thu-11", "last-mon-05"]) {
      expect(formatHoliday(parseHoliday(v))).toBe(v);
    }
  });
  it("describes holidays in words", () => {
    expect(describeHoliday("12-25")).toBe("Every year, December 25");
    expect(describeHoliday("12-21..01-02")).toBe("Every year, December 21 to January 2");
    expect(describeHoliday("2026-12-21..2027-01-02")).toBe("December 21, 2026 to January 2, 2027");
    expect(describeHoliday("4-thu-11")).toBe("Fourth Thursday of November, every year");
    expect(describeHoliday("last-mon-05")).toBe("Last Monday of May, every year");
  });
  it("collapses a one-day range and checks completeness", () => {
    expect(formatHoliday({ kind: "once", date: "2026-11-27", until: "2026-11-27" })).toBe("2026-11-27");
    expect(holidayComplete({ kind: "once", date: "", until: "" })).toBe(false);
    expect(holidayComplete({ kind: "once", date: "2026-11-27", until: "2026-11-20" })).toBe(false);
  });
});
