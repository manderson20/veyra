import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, formatPercent, formatRelative, humanize, initials, slugify } from "./format";

describe("formatting", () => {
  it("formats bytes", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(8 * 1024 ** 3)).toBe("8.0 GB");
    expect(formatBytes(250 * 1024 ** 3)).toBe("250 GB");
  });

  it("formats durations", () => {
    expect(formatDuration(undefined)).toBe("—");
    expect(formatDuration(42)).toBe("42s");
    expect(formatDuration(3 * 60)).toBe("3m");
    expect(formatDuration(2 * 3600 + 5 * 60)).toBe("2h 5m");
    expect(formatDuration(3 * 86400 + 4 * 3600)).toBe("3d 4h");
  });

  it("formats percentages", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(4.25)).toBe("4.3%");
    expect(formatPercent(42.4)).toBe("42%");
  });

  it("formats relative times", () => {
    const now = new Date("2026-10-12T12:00:00Z");
    expect(formatRelative(null, now)).toBe("never");
    expect(formatRelative("2026-10-12T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-12T11:30:00Z", now)).toBe("30 min ago");
    expect(formatRelative("2026-10-12T09:00:00Z", now)).toBe("3 h ago");
    expect(formatRelative("2026-10-10T12:00:00Z", now)).toBe("2 d ago");
  });

  it("derives initials, slugs and labels", () => {
    expect(initials("Morgan Anderson")).toBe("MA");
    expect(initials("  admin ")).toBe("A");
    expect(initials("")).toBe("?");
    expect(slugify("Brookfield R-III Schools!")).toBe("brookfield-r-iii-schools");
    expect(slugify("Écoles Publiques")).toBe("ecoles-publiques");
    expect(humanize("system.health_read")).toBe("System health read");
  });
});

describe("isLockedOut", async () => {
  const { isLockedOut } = await import("./users");
  it("is true only while the lockout is in the future", () => {
    const now = new Date("2026-10-12T12:00:00Z");
    expect(isLockedOut({ locked_until: null }, now)).toBe(false);
    expect(isLockedOut({ locked_until: "2026-10-12T11:00:00Z" }, now)).toBe(false);
    expect(isLockedOut({ locked_until: "2026-10-12T12:10:00Z" }, now)).toBe(true);
    expect(isLockedOut({ locked_until: "garbage" }, now)).toBe(false);
  });
});
