// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { cleanNumber, looksLikeNumber, normalizeNumber } from "./numbers";

const prefix9 = { dialPrefix: "9" };

describe("normalizeNumber", () => {
  it("leaves extensions alone", () => {
    expect(normalizeNumber("1001", prefix9)).toBe("1001");
    expect(normalizeNumber(" 1001 ", prefix9)).toBe("1001");
  });

  it("prepends the dial prefix to external numbers", () => {
    expect(normalizeNumber("573-555-0100", prefix9)).toBe("95735550100");
    expect(normalizeNumber("(573) 555.0100", prefix9)).toBe("95735550100");
  });

  it("turns +1 into prefix + 1 + ten digits", () => {
    expect(normalizeNumber("+1 573 555 0100", prefix9)).toBe("915735550100");
  });

  it("drops the plus on other international numbers", () => {
    expect(normalizeNumber("+44 20 7123 4567", prefix9)).toBe("9442071234567");
  });

  it("does not double the prefix", () => {
    expect(normalizeNumber("95735550100", prefix9)).toBe("95735550100");
  });

  it("keeps feature codes", () => {
    expect(normalizeNumber("*43", prefix9)).toBe("*43");
    expect(normalizeNumber("*43", { dialPrefix: "" })).toBe("*43");
    expect(normalizeNumber("#31#", prefix9)).toBe("#31#");
  });

  it("works without a prefix", () => {
    expect(normalizeNumber("573-555-0100", { dialPrefix: "" })).toBe("5735550100");
    expect(normalizeNumber("+1 573 555 0100", { dialPrefix: "" })).toBe("15735550100");
  });

  it("honours a different extension length", () => {
    expect(normalizeNumber("22214", { dialPrefix: "9", extensionLength: 5 })).toBe("22214");
    expect(normalizeNumber("22214", { dialPrefix: "9", extensionLength: 4 })).toBe("922214");
  });

  it("returns an empty string for nothing dialable", () => {
    expect(normalizeNumber("", prefix9)).toBe("");
    expect(normalizeNumber("+", prefix9)).toBe("");
    expect(normalizeNumber("call me", prefix9)).toBe("");
  });
});

describe("cleanNumber", () => {
  it("keeps digits, * and # and a leading plus", () => {
    expect(cleanNumber("+1 (573) 555-0100")).toBe("+15735550100");
    expect(cleanNumber("*72 1001")).toBe("*721001");
    expect(cleanNumber("12+34")).toBe("1234");
  });
});

describe("looksLikeNumber", () => {
  it("accepts phone-number-like selections", () => {
    expect(looksLikeNumber("573-555-0100")).toBe(true);
    expect(looksLikeNumber("+1 (573) 555-0100")).toBe(true);
    expect(looksLikeNumber("1001")).toBe(true);
    expect(looksLikeNumber("*43")).toBe(false);
    expect(looksLikeNumber("100")).toBe(true);
  });

  it("rejects text and too-short selections", () => {
    expect(looksLikeNumber("call me")).toBe(false);
    expect(looksLikeNumber("Room 12")).toBe(false);
    expect(looksLikeNumber("12")).toBe(false);
    expect(looksLikeNumber("")).toBe(false);
    expect(looksLikeNumber("1".repeat(40))).toBe(false);
  });
});
