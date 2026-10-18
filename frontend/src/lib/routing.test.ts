// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { destinationBody, destinationComplete, destinationDraft, EMPTY_DESTINATION, formatSeconds, HANGUP, moveItem, parseList, summarizeDays, summarizeRanges, trunkStatus, type DestinationDraft } from "./routing";

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
    expect(trunkStatus({ is_enabled: true, status: { state: "rejected", reachable: true, registration: "Rejected" } })).toEqual({ tone: "danger", label: "Registration rejected" });
    expect(trunkStatus({ is_enabled: true, status: { state: "registering", reachable: null } }).tone).toBe("warn");
  });

  it("normalizes destinations for the API", () => {
    const none = { ring_group_id: null, queue_id: null, voicemail_box_id: null };
    const d = (over: Partial<DestinationDraft>): DestinationDraft => ({ ...EMPTY_DESTINATION, ...over });
    expect(destinationBody(d({ type: "extension", extension_id: "e1", ivr_id: "m1" }))).toEqual({ type: "extension", extension_id: "e1", ivr_id: null, ...none });
    expect(destinationBody(d({ type: "voicemail", extension_id: "e1" }))).toEqual({ type: "voicemail", extension_id: "e1", ivr_id: null, ...none });
    expect(destinationBody(d({ type: "ivr", extension_id: "e1", ivr_id: "m1" }))).toEqual({ type: "ivr", extension_id: null, ivr_id: "m1", ...none });
    expect(destinationBody(d({ type: "ring_group", extension_id: "e1", ring_group_id: "g1" }))).toEqual({ type: "ring_group", extension_id: null, ivr_id: null, ring_group_id: "g1", queue_id: null, voicemail_box_id: null });
    expect(destinationBody(d({ type: "queue", queue_id: "q1", ring_group_id: "g1" }))).toEqual({ type: "queue", extension_id: null, ivr_id: null, ring_group_id: null, queue_id: "q1", voicemail_box_id: null });
    expect(destinationBody(d({ type: "voicemail_box", voicemail_box_id: "b1", extension_id: "e1" }))).toEqual({ type: "voicemail_box", extension_id: null, ivr_id: null, ring_group_id: null, queue_id: null, voicemail_box_id: "b1" });
    expect(destinationBody(d({ type: "hangup", extension_id: "e1", ivr_id: "m1" }))).toEqual({ type: "hangup", extension_id: null, ivr_id: null, ...none });
    expect(destinationComplete(d({ type: "ivr", extension_id: "e1" }))).toBe(false);
    expect(destinationComplete(d({ type: "hangup" }))).toBe(true);
    expect(destinationComplete(d({ type: "voicemail", extension_id: "e1" }))).toBe(true);
    expect(destinationComplete(d({ type: "queue" }))).toBe(false);
    expect(destinationComplete(d({ type: "ring_group", ring_group_id: "g1" }))).toBe(true);
    const missing = { type: "missing" as const, extension_id: "e9", ivr_id: null, label: null, missing: true };
    expect(destinationDraft(missing)).toEqual(EMPTY_DESTINATION);
    expect(destinationDraft({ type: "ivr", extension_id: null, ivr_id: "m1", label: "Menu: Main", missing: false })).toEqual(d({ type: "ivr", ivr_id: "m1" }));
    expect(destinationDraft({ type: "queue", extension_id: null, ivr_id: null, queue_id: "q1", label: "Queue: Support (2400)", missing: false })).toEqual(d({ type: "queue", queue_id: "q1" }));
    expect(destinationDraft(null, HANGUP).type).toBe("hangup");
  });

  it("formats prompt lengths", () => {
    expect(formatSeconds(0)).toBe("0:00");
    expect(formatSeconds(12.4)).toBe("0:12");
    expect(formatSeconds(125)).toBe("2:05");
    expect(formatSeconds(null)).toBe("0:00");
  });
});

