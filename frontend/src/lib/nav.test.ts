// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { buildNav, canSee, groupItems, isActive, moduleNavItems } from "./nav";
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
    // Settings needs no permission; every planned page has been built (M10).
    expect(hrefs).toContain("/settings/");
    expect(hrefs.some((h) => h.startsWith("/planned/"))).toBe(false);
    // Extensions is a real page now and needs its permission
    expect(hrefs).not.toContain("/extensions/");
    const withExt = buildNav({ permissions: ["extensions.read"], isPlatformAdmin: false });
    expect(withExt.find((s) => s.id === "telephony")?.items[0]?.href).toBe("/extensions/");
  });

  it("shows trunks and routing pages with their permissions, in evaluation order after Active Calls", () => {
    const all = buildNav({ permissions: [], isPlatformAdmin: true });
    const telephony = all.find((s) => s.id === "telephony")!.items.map((i) => i.href);
    expect(telephony.slice(0, 6)).toEqual(["/extensions/", "/calls/", "/trunks/", "/routing/inbound/", "/routing/outbound/", "/routing/time-conditions/"]);
    expect(telephony.some((h) => h.includes("feature=trunks") || h.includes("feature=inbound-routing") || h.includes("feature=outbound-routing"))).toBe(false);

    const routingOnly = buildNav({ permissions: ["routing.read"], isPlatformAdmin: false });
    const hrefs = routingOnly.flatMap((s) => s.items.map((i) => i.href));
    expect(hrefs).toContain("/routing/inbound/");
    expect(hrefs).toContain("/routing/outbound/");
    expect(hrefs).toContain("/routing/time-conditions/");
    expect(hrefs).not.toContain("/trunks/");
    const trunksOnly = buildNav({ permissions: ["trunks.read"], isPlatformAdmin: false });
    const trunkHrefs = trunksOnly.flatMap((s) => s.items.map((i) => i.href));
    expect(trunkHrefs).toContain("/trunks/");
    expect(trunkHrefs).not.toContain("/routing/inbound/");
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

describe("activeLocation and rail metadata", () => {
  it("finds the category and page of the current path, preferring the longest match", async () => {
    const { NAV, activeLocation, buildNav } = await import("./nav");
    const sections = buildNav({ permissions: [], isPlatformAdmin: true });
    const loc = activeLocation(sections, "/routing/inbound/", "");
    expect(loc?.section.id).toBe("telephony");
    expect(loc?.item.label).toBe("Inbound Routes");
    expect(activeLocation(sections, "/", "")?.item.label).toBe("Dashboard");
    expect(activeLocation(sections, "/nowhere/", "")).toBeNull();
    for (const s of NAV) expect(s.icon, `${s.id} has an icon`).toBeTruthy();
  });
});

describe("flyout columns", () => {
  it("groups items in first-appearance order and gives every core page a group", () => {
    const all = buildNav({ permissions: [], isPlatformAdmin: true });
    const telephony = all.find((s) => s.id === "telephony")!;
    const groups = groupItems(telephony.items);
    expect(groups.map((g) => g.label)).toEqual([
      "Phones and calls", "Routing", "Call handling", "Audio", "Paging and bells", "History and reports",
    ]);
    expect(groups.flatMap((g) => g.items)).toHaveLength(telephony.items.length);
    // Single-page categories are direct links in the rail and need no column.
    for (const s of all.filter((x) => x.items.length > 1)) for (const i of s.items) expect(i.group, i.href).toBeTruthy();
  });

  it("keeps ungrouped items (module pages) in one untitled column", () => {
    const groups = groupItems([{ label: "A", href: "/a/", icon: "x" }, { label: "B", href: "/b/", icon: "x" }]);
    expect(groups).toEqual([{ label: null, items: expect.any(Array) }]);
    expect(groups[0]!.items).toHaveLength(2);
  });
});
