// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { formatTick, niceMax, scaleY } from "./Chart";

describe("chart scales", () => {
  it("rounds the axis maximum to a readable value with a floor", () => {
    expect(niceMax(0)).toBe(5);
    expect(niceMax(3)).toBe(5);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(13)).toBe(20);
    expect(niceMax(140)).toBe(200);
    expect(niceMax(500)).toBe(500);
  });
  it("maps values into the drawing box top-down", () => {
    expect(scaleY(0, 10, 100)).toBe(96);
    expect(scaleY(10, 10, 100)).toBe(4);
    expect(scaleY(5, 10, 100)).toBe(50);
    expect(scaleY(1, 0, 100)).toBe(96);
  });
  it("labels ticks with the time for short ranges and the day for long ones", () => {
    expect(formatTick("2026-10-14T15:30:00Z", 3600)).toMatch(/\d/);
    expect(formatTick("2026-10-14T15:30:00Z", 7 * 86400)).toMatch(/[A-Za-z]/);
  });
});
