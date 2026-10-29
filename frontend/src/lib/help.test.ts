// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { canSeeAdminGuides, GUIDES, guidesForPath, searchGuides, visibleGuides } from "./help";

describe("help guides", () => {
  it("finds the guide for a page and the pages below it", () => {
    expect(guidesForPath("/system/companion/", true).map((g) => g.slug)).toContain("companion-rollout");
    expect(guidesForPath("/system/sign-in/setup/", true).map((g) => g.slug)).toEqual(["single-sign-on"]);
    expect(guidesForPath("/nowhere/", true)).toEqual([]);
  });

  it("shows administrators' guides only to people who can manage something", () => {
    expect(canSeeAdminGuides({ is_platform_admin: false, permissions: ["calls.read"] })).toBe(false);
    expect(canSeeAdminGuides({ is_platform_admin: false, permissions: ["extensions.write"] })).toBe(true);
    expect(visibleGuides(false).every((g) => g.audience === "user")).toBe(true);
    expect(guidesForPath("/system/companion/", false)).toEqual([]);
    expect(visibleGuides(true)).toHaveLength(GUIDES.length);
  });

  it("searches titles first, then the text", () => {
    const found = searchGuides(GUIDES, "intune");
    expect(found.map((g) => g.slug)).toContain("companion-rollout");
    expect(searchGuides(GUIDES, "")).toHaveLength(GUIDES.length);
  });
});
