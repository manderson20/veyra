// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { formatAllow, parseAllow, parseList, policyDocument, policyForm, policySummary, resultTone } from "./central";

describe("central helpers", () => {
  it("parses address lists", () => {
    expect(parseList("a@x.org, b@x.org\n\n c@x.org ;")).toEqual(["a@x.org", "b@x.org", "c@x.org"]);
    expect(parseList("  ")).toEqual([]);
  });

  it("parses and formats allow lists", () => {
    const entries = parseAllow("10.0.0.0/8 District WAN\n\n192.0.2.7\n198.51.100.0/24 # vendor");
    expect(entries).toEqual([
      { cidr: "10.0.0.0/8", comment: "District WAN" },
      { cidr: "192.0.2.7", comment: null },
      { cidr: "198.51.100.0/24", comment: "vendor" },
    ]);
    expect(formatAllow(entries)).toBe("10.0.0.0/8 District WAN\n192.0.2.7\n198.51.100.0/24 vendor");
  });

  it("round-trips a policy document", () => {
    const doc = {
      updates: { policy: { mode: "download_approve", auto_download: true, maintenance_window: null, auto_install_categories: [] }, source_url: null, recipients: ["it@x.org"] },
      firewall_allow: [{ cidr: "10.0.0.0/8", comment: null }],
      notice: "Managed by the district",
    };
    const form = policyForm(doc);
    expect(form.alerts).toBe(false);
    expect(policyDocument(form)).toEqual(doc);
  });

  it("leaves unset sections out and clears categories outside automatic mode", () => {
    const form = { ...policyForm({}), updates: true, mode: "notify" as const, categories: ["security"] };
    const doc = policyDocument(form);
    expect(Object.keys(doc)).toEqual(["updates"]);
    expect(doc.updates?.policy).toMatchObject({ mode: "notify", auto_download: false, auto_install_categories: [] });
    expect(doc.updates?.recipients).toBeNull();
  });

  it("summarises and colours results", () => {
    expect(policySummary({ alert_recipients: ["a"], notice: "" })).toEqual(["Alert recipients: 1", "No notice"]);
    expect(resultTone("applied")).toBe("ok");
    expect(resultTone("refused")).toBe("warn");
    expect(resultTone("error: boom")).toBe("danger");
    expect(resultTone("not set")).toBe("neutral");
  });
});
