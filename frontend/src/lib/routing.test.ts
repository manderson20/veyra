// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { moveItem, parseList, summarizeDays, summarizeRanges, trunkStatus } from "./routing";

describe("routing helpers", () => {
  it("parses comma and newline separated lists", () => {
    expect(parseList("203.0.113.5, 203.0.113.6\n\n203.0.113.5 ")).toEqual(["203.0.113.5", "203.0.113.6"]);
    expect(parseList("")).toEqual([]);
  });

  it("summarizes day spans", () => {
    expect(summarizeDays(["mon", "tue", "wed", "thu", "fri"])).toBe("Mon–Fri");
    expect(summarizeDays(["fri", "mon", "wed"])).toBe("Mon, Wed, Fri");
    expect(summarizeDays(["sat", "sun"])).toBe("Sat–Sun");
    expect(summarizeDays(["mon", "tue", "thu", "fri"])).toBe("Mon–Tue, Thu–Fri");
  });

  it("summarizes ranges", () => {
    expect(summarizeRanges([
      { days: ["mon", "tue", "wed", "thu", "fri"], start: "07:30", end: "16:00" },
      { days: ["sat"], start: "09:00", end: "12:00" },
    ])).toBe("Mon–Fri 07:30–16:00; Sat 09:00–12:00");
  });

  it("moves items", () => {
    expect(moveItem(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveItem(["a", "b"], 1, 5)).toEqual(["a", "b"]);
  });

  it("maps trunk status to a badge", () => {
    expect(trunkStatus({ is_enabled: false, status: { state: "online", reachable: true } }).label).toBe("Disabled");
    expect(trunkStatus({ is_enabled: true, status: { state: "online", reachable: true } })).toEqual({ tone: "ok", label: "Online" });
    expect(trunkStatus({ is_enabled: true, status: { state: "offline", reachable: false } }).tone).toBe("danger");
    expect(trunkStatus({ is_enabled: true, status: null }).label).toBe("Unknown");
  });
});
