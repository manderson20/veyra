// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The portal canvas's layout model (docs/USER_PORTAL.md §10): a 12-column
 * grid per tab, widgets placed by column/row with a size in grid units.
 * Pure functions, unit-tested; the canvas component only renders and calls
 * these.
 */

export const COLS = 12;
export const ROW_PX = 40;

export interface Placed {
  key: string;
  /** Distinguishes two widgets of the same kind (e.g. two voicemail boxes). */
  instance: string;
  x: number;
  y: number;
  w: number;
  h: number;
  settings?: Record<string, unknown>;
}

export interface LayoutTab {
  id: string;
  name: string;
  widgets: Placed[];
}

export interface Layout {
  version: 1;
  tabs: LayoutTab[];
}

export interface Size { w: number; h: number }

export const idOf = (p: Pick<Placed, "key" | "instance">): string => `${p.key}:${p.instance}`;

export function collides(a: Placed, b: Placed): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Clamp a widget into the grid: at least 1×1, no wider than the columns. */
export function clamp(p: Placed, cols = COLS, min: Size = { w: 1, h: 1 }): Placed {
  const w = Math.max(min.w, Math.min(cols, Math.round(p.w)));
  const h = Math.max(min.h, Math.round(p.h));
  const x = Math.max(0, Math.min(cols - w, Math.round(p.x)));
  const y = Math.max(0, Math.round(p.y));
  return { ...p, x, y, w, h };
}

/** Pull every widget up as far as it goes, in reading order (top-left first). */
export function compact(widgets: Placed[]): Placed[] {
  const sorted = [...widgets].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: Placed[] = [];
  for (const w of sorted) {
    let y = w.y;
    while (y > 0) {
      const probe = { ...w, y: y - 1 };
      if (out.some((o) => collides(o, probe))) break;
      y -= 1;
    }
    out.push({ ...w, y });
  }
  return out;
}

/** The first free spot for a widget of this size, scanning rows then columns. */
export function findSpot(widgets: Placed[], size: Size, cols = COLS): { x: number; y: number } {
  const w = Math.min(size.w, cols);
  for (let y = 0; y < 10000; y++) {
    for (let x = 0; x + w <= cols; x++) {
      const probe: Placed = { key: "", instance: "", x, y, w, h: size.h };
      if (!widgets.some((o) => collides(o, probe))) return { x, y };
    }
  }
  return { x: 0, y: 0 };
}

/** Move one widget; widgets it lands on are pushed down, then everything compacts. */
export function moveWidget(widgets: Placed[], id: string, x: number, y: number, cols = COLS): Placed[] {
  const me = widgets.find((p) => idOf(p) === id);
  if (!me) return widgets;
  const moved = clamp({ ...me, x, y }, cols, { w: 1, h: 1 });
  let others = widgets.filter((p) => idOf(p) !== id);
  // Push down anything we land on, repeatedly, until nothing overlaps.
  let changed = true;
  let guard = 0;
  while (changed && guard++ < 200) {
    changed = false;
    others = others.map((o) => {
      if (collides(o, moved)) {
        changed = true;
        return { ...o, y: moved.y + moved.h };
      }
      return o;
    });
    // Pushed widgets may now overlap each other: resolve pairwise in order.
    const sorted = [...others].sort((a, b) => a.y - b.y || a.x - b.x);
    const settled: Placed[] = [];
    for (const o of sorted) {
      let cur = o;
      for (const s of settled) {
        if (collides(s, cur)) { cur = { ...cur, y: s.y + s.h }; changed = true; }
      }
      settled.push(cur);
    }
    others = settled;
  }
  // Compact everything except the moved widget stays where it was dropped (then compacts too).
  return compact([moved, ...others]);
}

export function resizeWidget(widgets: Placed[], id: string, w: number, h: number, min: Size, cols = COLS): Placed[] {
  const me = widgets.find((p) => idOf(p) === id);
  if (!me) return widgets;
  const sized = clamp({ ...me, w, h }, cols, min);
  return moveWidget([sized, ...widgets.filter((p) => idOf(p) !== id)], id, sized.x, sized.y, cols);
}

export function addWidget(widgets: Placed[], key: string, instance: string, size: Size, cols = COLS): Placed[] {
  const spot = findSpot(widgets, size, cols);
  return compact([...widgets, { key, instance, x: spot.x, y: spot.y, w: Math.min(size.w, cols), h: size.h }]);
}

export function removeWidget(widgets: Placed[], id: string): Placed[] {
  return compact(widgets.filter((p) => idOf(p) !== id));
}

/** Columns for a canvas width: phones get a single column (widgets stack). */
export function columnsFor(widthPx: number): number {
  if (widthPx < 600) return 1;
  if (widthPx < 900) return 6;
  return COLS;
}

/** Re-express a 12-column layout for fewer columns: widths scale, one
 * column stacks everything in reading order. */
export function reflow(widgets: Placed[], cols: number): Placed[] {
  if (cols >= COLS) return widgets;
  if (cols === 1) {
    return [...widgets].sort((a, b) => a.y - b.y || a.x - b.x).map((p, i, arr) => ({
      ...p, x: 0, w: 1, y: arr.slice(0, i).reduce((acc, q) => acc + q.h, 0),
    }));
  }
  const scale = cols / COLS;
  return compact(
    widgets.map((p) => {
      const w = Math.max(1, Math.round(p.w * scale));
      const x = Math.min(cols - w, Math.round(p.x * scale));
      return { ...p, x, w };
    }),
  );
}

export function heightOf(widgets: Placed[]): number {
  return widgets.reduce((m, p) => Math.max(m, p.y + p.h), 0);
}

/** A user's saved layout layered over the template they resolve to: the
 * user's tabs and positions win; widgets the template locks are put back
 * on the first tab if the user removed them. */
export function applyTemplate(user: Layout | null, template: Layout | null, locked: string[]): Layout {
  const base: Layout = user ?? template ?? { version: 1, tabs: [{ id: "home", name: "Home", widgets: [] }] };
  const out: Layout = { version: 1, tabs: base.tabs.map((t) => ({ ...t, widgets: [...t.widgets] })) };
  if (out.tabs.length === 0) out.tabs.push({ id: "home", name: "Home", widgets: [] });
  const present = new Set(out.tabs.flatMap((t) => t.widgets.map((w) => w.key)));
  for (const key of locked) {
    if (present.has(key)) continue;
    const fromTemplate = template?.tabs.flatMap((t) => t.widgets).find((w) => w.key === key);
    const size = fromTemplate ? { w: fromTemplate.w, h: fromTemplate.h } : { w: 6, h: 6 };
    const first = out.tabs[0];
    if (first) first.widgets = addWidget(first.widgets, key, fromTemplate?.instance ?? "default", size);
  }
  return out;
}

export function newTabId(tabs: LayoutTab[]): string {
  let n = tabs.length + 1;
  while (tabs.some((t) => t.id === `tab-${n}`)) n++;
  return `tab-${n}`;
}
