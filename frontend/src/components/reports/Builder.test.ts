// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { chartData, formatMeasure } from "./Builder";
import type { ReportResult } from "@/lib/types";

const cols = (groups: string[]) => [
  ...groups.map((g) => ({ key: g, label: g, kind: "group" as const })),
  { key: "calls", label: "Calls", kind: "measure" as const, unit: "count" as const },
];
const row = (labels: string[], calls: number) => ({ group: labels.map((l) => ({ key: l, label: l })), calls });

describe("report builder chart data", () => {
  it("plots one series for one grouping", () => {
    const r: ReportResult = { columns: cols(["day"]), rows: [row(["Mon"], 3), row(["Tue"], 5)], totals: { calls: 8 }, truncated: false,
      period: { from: "", to: "", label: "", timezone: "UTC" } };
    const { data, series } = chartData(r, "calls");
    expect(series).toHaveLength(1);
    expect(data).toEqual([{ x: "Mon", v: 3 }, { x: "Tue", v: 5 }]);
  });

  it("keeps the three largest second groups and folds the rest into Other", () => {
    const rows = [row(["Mon", "A"], 9), row(["Mon", "B"], 5), row(["Mon", "C"], 4), row(["Mon", "D"], 1), row(["Tue", "A"], 1), row(["Tue", "E"], 2)];
    const r: ReportResult = { columns: cols(["day", "who"]), rows, totals: { calls: 22 }, truncated: false,
      period: { from: "", to: "", label: "", timezone: "UTC" } };
    const { data, series } = chartData(r, "calls");
    expect(series.map((s) => s.label)).toEqual(["A", "B", "C", "Other"]);
    expect(data[0]).toEqual({ x: "Mon", s0: 9, s1: 5, s2: 4, other: 1 });
    expect(data[1]).toEqual({ x: "Tue", s0: 1, other: 2 });
  });

  it("formats measures by unit", () => {
    expect(formatMeasure(65, "seconds")).toBe("1:05");
    expect(formatMeasure(87.5, "percent")).toBe("87.5%");
    expect(formatMeasure(4, "count")).toBe("4");
  });
});
