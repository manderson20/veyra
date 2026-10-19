// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { addWidget, applyTemplate, collides, columnsFor, compact, findSpot, heightOf, idOf, moveWidget, reflow, removeWidget, resizeWidget, type Layout, type Placed } from "./layout";

const p = (key: string, x: number, y: number, w: number, h: number): Placed => ({ key, instance: "d", x, y, w, h });

describe("portal canvas layout", () => {
  it("detects overlap and compacts upwards", () => {
    expect(collides(p("a", 0, 0, 6, 4), p("b", 5, 3, 6, 4))).toBe(true);
    expect(collides(p("a", 0, 0, 6, 4), p("b", 6, 0, 6, 4))).toBe(false);
    const out = compact([p("a", 0, 5, 6, 4), p("b", 0, 0, 6, 2), p("c", 6, 9, 6, 2)]);
    expect(out.map((w) => [w.key, w.y])).toEqual([["b", 0], ["a", 2], ["c", 0]]);
  });

  it("finds the first free spot and adds there", () => {
    const widgets = [p("a", 0, 0, 6, 4), p("b", 6, 0, 6, 2)];
    expect(findSpot(widgets, { w: 6, h: 2 })).toEqual({ x: 6, y: 2 });
    expect(findSpot(widgets, { w: 12, h: 1 })).toEqual({ x: 0, y: 4 });
    const added = addWidget(widgets, "c", "x", { w: 6, h: 2 });
    expect(added.find((w) => w.key === "c")).toMatchObject({ x: 6, y: 2 });
    expect(heightOf(added)).toBe(4);
  });

  it("moves a widget, pushing what it lands on down, and keeps the grid bounds", () => {
    const widgets = [p("a", 0, 0, 6, 4), p("b", 6, 0, 6, 4)];
    const out = moveWidget(widgets, idOf(widgets[0]!), 6, 0);
    const a = out.find((w) => w.key === "a")!;
    const b = out.find((w) => w.key === "b")!;
    expect([a.x, a.y]).toEqual([6, 0]);
    expect([b.x, b.y]).toEqual([6, 4]);
    expect(moveWidget(widgets, idOf(widgets[0]!), 11, 0).find((w) => w.key === "a")).toMatchObject({ x: 6 });
    expect(moveWidget(widgets, "nope:d", 1, 1)).toBe(widgets);
  });

  it("resizes within limits and removes with compaction", () => {
    const widgets = [p("a", 0, 0, 6, 4), p("b", 0, 4, 6, 2)];
    const grown = resizeWidget(widgets, idOf(widgets[0]!), 20, 1, { w: 2, h: 3 });
    expect(grown.find((w) => w.key === "a")).toMatchObject({ w: 12, h: 3 });
    expect(grown.find((w) => w.key === "b")).toMatchObject({ y: 3 });
    const gone = removeWidget(widgets, idOf(widgets[0]!));
    expect(gone).toEqual([{ ...widgets[1]!, y: 0 }]);
  });

  it("reflows for narrower screens", () => {
    expect([columnsFor(400), columnsFor(800), columnsFor(1400)]).toEqual([1, 6, 12]);
    const widgets = [p("a", 0, 0, 6, 4), p("b", 6, 0, 6, 2)];
    expect(reflow(widgets, 6).map((w) => [w.x, w.w])).toEqual([[0, 3], [3, 3]]);
    const one = reflow(widgets, 1);
    expect(one.map((w) => [w.x, w.w, w.y])).toEqual([[0, 1, 0], [0, 1, 4]]);
  });

  it("layers the user's layout over the template and restores locked widgets", () => {
    const template: Layout = { version: 1, tabs: [{ id: "home", name: "Home", widgets: [p("phone", 0, 0, 6, 4), p("announce", 6, 0, 6, 2)] }] };
    const user: Layout = { version: 1, tabs: [{ id: "home", name: "Mine", widgets: [p("phone", 0, 0, 12, 4)] }, { id: "tab-2", name: "Calls", widgets: [] }] };
    const out = applyTemplate(user, template, ["announce"]);
    expect(out.tabs.map((t) => t.name)).toEqual(["Mine", "Calls"]);
    expect(out.tabs[0]!.widgets.map((w) => w.key)).toEqual(["phone", "announce"]);
    expect(out.tabs[0]!.widgets[1]).toMatchObject({ w: 6, h: 2, y: 4 });
    expect(applyTemplate(null, null, []).tabs[0]!.name).toBe("Home");
    expect(applyTemplate(null, template, ["announce"]).tabs[0]!.widgets).toHaveLength(2);
  });
});
