import { describe, expect, it } from "vitest";
import { buildNav, canSee, isActive, moduleNavItems } from "./nav";
import type { UiExtension } from "./types";

const ext: UiExtension = {
  module_id: "veyra.example-notes",
  module_name: "Example: Notes",
  api_base: "/api/v1/ext/example-notes",
  nav: [{ label: "Notes", view: "notes", icon: "note", permission: "example_notes.read" }],
  views: [],
};

describe("navigation filtering", () => {
  it("shows everything to platform administrators", () => {
    const nav = buildNav({ permissions: [], isPlatformAdmin: true });
    expect(nav.map((s) => s.id)).toContain("system");
    expect(nav.flatMap((s) => s.items).some((i) => i.href === "/modules/")).toBe(true);
  });

  it("hides items without permission and drops empty sections", () => {
    const nav = buildNav({ permissions: ["users.read"], isPlatformAdmin: false });
    const hrefs = nav.flatMap((s) => s.items.map((i) => i.href));
    expect(hrefs).toContain("/users/");
    expect(hrefs).not.toContain("/organizations/");
    expect(hrefs).not.toContain("/modules/");
    expect(nav.find((s) => s.id === "provisioning")).toBeUndefined();
    // Planned features and Settings need no permission
    expect(hrefs).toContain("/settings/");
    expect(hrefs.some((h) => h.startsWith("/planned/"))).toBe(true);
  });

  it("adds module navigation only with the module permission", () => {
    expect(moduleNavItems([ext])[0]?.href).toBe("/modules/view/?module=veyra.example-notes&view=notes");
    const without = buildNav({ permissions: [], isPlatformAdmin: false, extensions: [ext] });
    expect(without.find((s) => s.id === "modules")).toBeUndefined();
    const withPerm = buildNav({ permissions: ["example_notes.read"], isPlatformAdmin: false, extensions: [ext] });
    expect(withPerm.find((s) => s.id === "modules")?.items[0]?.label).toBe("Notes");
  });

  it("platformOnly items require platform admin", () => {
    expect(canSee({ label: "x", href: "/x", icon: "x", platformOnly: true }, { permissions: ["*"], isPlatformAdmin: false })).toBe(false);
  });
});

describe("isActive", () => {
  it("matches paths with and without query parameters", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/", "/users/")).toBe(false);
    expect(isActive("/users/", "/users/view/")).toBe(true);
    expect(isActive("/planned/?feature=ivr", "/planned/", "feature=ivr")).toBe(true);
    expect(isActive("/planned/?feature=ivr", "/planned/", "feature=paging")).toBe(false);
  });
});
