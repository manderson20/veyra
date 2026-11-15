// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { clearWorkingOrg, pathAfterSwitch, setWorkingOrg, workingOrg } from "./workingOrg";

function mem() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
}

describe("working organization", () => {
  it("starts in System, then follows the choice", () => {
    const s = { tab: mem(), last: mem(), search: () => "" };
    expect(workingOrg(s)).toBe("");
    setWorkingOrg("acme", s);
    expect(workingOrg(s)).toBe("acme");
  });
  it("a new tab starts in the last choice; a tab keeps its own", () => {
    const last = mem();
    const a = { tab: mem(), last, search: () => "" };
    setWorkingOrg("acme", a);
    const b = { tab: mem(), last, search: () => "" };
    expect(workingOrg(b)).toBe("acme");
    setWorkingOrg("beta", b);
    expect(workingOrg(a)).toBe("acme");
  });
  it("a link sets the tab's organization; ?org= is System", () => {
    const s = { tab: mem(), last: mem(), search: () => "?org=Beta" };
    expect(workingOrg(s)).toBe("beta");
    expect(workingOrg({ ...s, search: () => "?org=" })).toBe("");
  });
  it("clearing returns to System", () => {
    const s = { tab: mem(), last: mem(), search: () => "" };
    setWorkingOrg("acme", s);
    clearWorkingOrg(s);
    expect(workingOrg(s)).toBe("");
  });
  it("switching closes an open object", () => {
    expect(pathAfterSwitch("/extensions/view/", "beta")).toBe("/extensions/?org=beta");
    expect(pathAfterSwitch("/extensions/", "")).toBe("/extensions/?org=");
  });
});
