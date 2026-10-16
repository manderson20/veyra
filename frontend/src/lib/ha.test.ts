// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { isStandby, lagLabel, nodeStatus, operationProgress, overallStatus, replicationLabel, stepLabel } from "./ha";
import type { HaOperation } from "./types";

describe("ha helpers", () => {
  it("maps node states to badges", () => {
    expect(nodeStatus({ state: "online", stale: false })).toBe("ok");
    expect(nodeStatus({ state: "online", stale: true })).toBe("unknown");
    expect(nodeStatus({ state: "isolated" })).toBe("failed");
    expect(nodeStatus({ state: "rejoining" })).toBe("degraded");
  });

  it("formats lag and replication", () => {
    expect(lagLabel(null)).toBe("—");
    expect(lagLabel({ lag_bytes: 512 })).toBe("512 B");
    expect(lagLabel({ lag_bytes: 4096 })).toBe("4 KB");
    expect(lagLabel({ lag_bytes: 3 * 1024 * 1024, lag_seconds: 0.25 })).toBe("3.0 MB · 0.3 s");
    expect(replicationLabel({ db_role: "primary", state: "streaming", synchronous: true })).toBe("Streaming (synchronous)");
    expect(replicationLabel({ db_role: "primary", state: null })).toBe("No standby connected");
    expect(replicationLabel({ db_role: "standby", receiver: "stopped" })).toBe("Not receiving");
    expect(replicationLabel({ db_role: "down" })).toBe("Database down");
  });

  it("summarises the cluster and operations", () => {
    expect(overallStatus({ ha_enabled: false })).toBe("unavailable");
    expect(overallStatus({ ha_enabled: true, summary: "healthy" })).toBe("ok");
    expect(overallStatus({ ha_enabled: true, summary: "isolated" })).toBe("failed");
    const op: HaOperation = {
      kind: "switchover", target: "dev2", actor: "admin", status: "running", started_at: "", finished_at: null, error: "",
      steps: [
        { name: "freeze", status: "ok", started_at: "", finished_at: "", detail: "", seconds: 0.2 },
        { name: "catch-up", status: "running", started_at: "", finished_at: null, detail: "", seconds: null },
      ],
    };
    expect(operationProgress(op)).toEqual({ done: 1, total: 2, current: "catch-up" });
    expect(operationProgress(null).total).toBe(0);
    expect(stepLabel("catch-up")).toBe("Standby catches up");
    expect(stepLabel("mystery")).toBe("mystery");
    expect(isStandby({ local: { role: "secondary" } } as never)).toBe(true);
    expect(isStandby(undefined)).toBe(false);
  });
});
