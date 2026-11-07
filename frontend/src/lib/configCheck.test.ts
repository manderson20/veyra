// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { countFindings, groupFindings } from "./configCheck";
import type { ConfigFinding } from "./types";

function finding(over: Partial<ConfigFinding>): ConfigFinding {
  return {
    fingerprint: "cv1:a", severity: "error", rule: "enum.1", message: "4 is not a transport.", file: "{mac}.cfg",
    parameter: "account.1.sip_server.1.transport_type", pattern: "", value: "4", vendor: "yealink", family: "t4x",
    model: "T46U", firmware: "86", release: "86", note: "", source: "", provenance: "vendor-doc", filled_by: [],
    accepts: "0 UDP, 1 TCP", members: [], ...over,
  };
}

describe("configuration check findings", () => {
  it("shows one row for the same setting on several models", () => {
    const groups = groupFindings([
      finding({ fingerprint: "cv1:a", model: "T46U" }),
      finding({ fingerprint: "cv1:b", model: "T48U" }),
      finding({ fingerprint: "cv1:c", parameter: "account.2.label", rule: "type.string", severity: "warning" }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]!.models).toEqual(["T46U", "T48U"]);
    expect(groups[0]!.fingerprints).toEqual(["cv1:a", "cv1:b"]);
  });

  it("counts overridden errors apart, and notes as not checked", () => {
    const override = { id: "1", by: "A. Admin", at: "2026-11-07T00:00:00Z", reason: "ok", checker_wrong: false, scope_type: "profile" };
    const c = countFindings([
      finding({ fingerprint: "cv1:a", override }),
      finding({ fingerprint: "cv1:d", parameter: "x", value: "9" }),
      finding({ fingerprint: "cv1:e", severity: "info", rule: "param.not-in-catalog", parameter: "", members: ["a.b"] }),
    ]);
    expect(c.errors).toBe(1);
    expect(c.overridden).toBe(1);
    expect(c.warnings).toBe(0);
    expect(c.notes).toHaveLength(1);
  });

  it("keeps a group open while any model's finding is not overridden", () => {
    const override = { id: "1", by: "A", at: "2026-11-07T00:00:00Z", reason: "ok", checker_wrong: false, scope_type: "profile" };
    const [g] = groupFindings([finding({ fingerprint: "cv1:a", override }), finding({ fingerprint: "cv1:b", model: "T48U" })]);
    expect(g!.overridden).toBe(false);
  });
});
