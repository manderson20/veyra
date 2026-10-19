// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Icon } from "@/components/ui";
import { COLS, ROW_PX, columnsFor, heightOf, idOf, moveWidget, reflow, resizeWidget, type Placed, type Size } from "@/portal/layout";
import { widgetByKey } from "@/portal/widgets";

/**
 * The portal canvas (docs/USER_PORTAL.md §10): a 12-column grid of widgets.
 * In arrange mode a widget is dragged by its header and resized by its
 * corner handle (pointer events; no library); the header menu offers the
 * same moves from the keyboard. Below 600 px the widgets stack in reading
 * order and arranging is off.
 */
export function Canvas({ widgets, render, arranging, locked, onChange, onRemove }: {
  widgets: Placed[];
  render: (p: Placed) => ReactNode;
  arranging: boolean;
  /** Widget keys the user may not remove. */
  locked: Set<string>;
  onChange: (widgets: Placed[]) => void;
  onRemove: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1200);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => { for (const e of entries) setWidth(e.contentRect.width); });
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  const cols = columnsFor(width);
  const shown = reflow(widgets, cols);
  const canArrange = arranging && cols === COLS;
  const colPx = width / cols;
  const [drag, setDrag] = useState<{ id: string; mode: "move" | "resize"; startX: number; startY: number; origin: Placed; ghost: Placed } | null>(null);

  const onPointerDown = (e: React.PointerEvent, p: Placed, mode: "move" | "resize") => {
    if (!canArrange) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    setDrag({ id: idOf(p), mode, startX: e.clientX, startY: e.clientY, origin: p, ghost: p });
  };
  const onPointerMove = useCallback((e: PointerEvent) => {
    if (!drag) return;
    const dx = Math.round((e.clientX - drag.startX) / colPx);
    const dy = Math.round((e.clientY - drag.startY) / ROW_PX);
    const min = widgetByKey(drag.origin.key)?.minSize ?? { w: 1, h: 1 };
    const ghost = drag.mode === "move"
      ? { ...drag.origin, x: Math.max(0, Math.min(COLS - drag.origin.w, drag.origin.x + dx)), y: Math.max(0, drag.origin.y + dy) }
      : { ...drag.origin, w: Math.max(min.w, Math.min(COLS - drag.origin.x, drag.origin.w + dx)), h: Math.max(min.h, drag.origin.h + dy) };
    setDrag((d) => (d ? { ...d, ghost } : d));
  }, [drag, colPx]);
  const onPointerUp = useCallback(() => {
    if (!drag) return;
    const g = drag.ghost;
    const min = widgetByKey(drag.origin.key)?.minSize ?? { w: 1, h: 1 };
    onChange(drag.mode === "move" ? moveWidget(widgets, drag.id, g.x, g.y) : resizeWidget(widgets, drag.id, g.w, g.h, min));
    setDrag(null);
  }, [drag, widgets, onChange]);
  useEffect(() => {
    if (!drag) return;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, [drag, onPointerMove, onPointerUp]);

  const nudge = (p: Placed, dx: number, dy: number) => onChange(moveWidget(widgets, idOf(p), p.x + dx, p.y + dy));
  const grow = (p: Placed, dw: number, dh: number) => {
    const min = widgetByKey(p.key)?.minSize ?? { w: 1, h: 1 };
    onChange(resizeWidget(widgets, idOf(p), p.w + dw, p.h + dh, min));
  };
  const rows = Math.max(heightOf(drag ? shown.map((p) => (idOf(p) === drag.id ? drag.ghost : p)) : shown), 4) + (canArrange ? 6 : 0);

  return (
    <div ref={ref} className={`canvas${canArrange ? " canvas--arranging" : ""}`} style={{ position: "relative", height: rows * ROW_PX, minHeight: 160 }}>
      {shown.map((p) => {
        const id = idOf(p);
        const pos = drag && drag.id === id ? drag.ghost : p;
        const style: React.CSSProperties = {
          position: "absolute",
          left: `${(pos.x / cols) * 100}%`,
          top: pos.y * ROW_PX,
          width: `calc(${(pos.w / cols) * 100}% - 12px)`,
          height: pos.h * ROW_PX - 12,
          transition: drag ? undefined : "left .15s, top .15s, width .15s, height .15s",
          zIndex: drag && drag.id === id ? 5 : 1,
        };
        const manifest = widgetByKey(p.key);
        return (
          <div key={id} className="canvas__item" style={style} role="group" aria-label={manifest?.title ?? p.key}>
            {canArrange ? (
              <div className="canvas__handle row" style={{ justifyContent: "space-between", cursor: "grab", touchAction: "none" }} onPointerDown={(e) => onPointerDown(e, p, "move")}>
                <span><Icon name="menu" size={14} /> {manifest?.title ?? p.key}{locked.has(p.key) ? <> <Icon name="lock" size={12} aria-label="Required by your administrators" /></> : null}</span>
                <span className="row" onPointerDown={(e) => e.stopPropagation()}>
                  <Button size="sm" variant="ghost" icon="chevronLeft" aria-label="Move left" onClick={() => nudge(p, -1, 0)} />
                  <Button size="sm" variant="ghost" icon="chevronRight" aria-label="Move right" onClick={() => nudge(p, 1, 0)} />
                  <Button size="sm" variant="ghost" icon="chevronUp" aria-label="Move up" onClick={() => nudge(p, 0, -1)} />
                  <Button size="sm" variant="ghost" icon="chevronDown" aria-label="Move down" onClick={() => nudge(p, 0, 1)} />
                  <Button size="sm" variant="ghost" aria-label="Narrower" onClick={() => grow(p, -1, 0)}>−W</Button>
                  <Button size="sm" variant="ghost" aria-label="Wider" onClick={() => grow(p, 1, 0)}>+W</Button>
                  <Button size="sm" variant="ghost" aria-label="Shorter" onClick={() => grow(p, 0, -1)}>−H</Button>
                  <Button size="sm" variant="ghost" aria-label="Taller" onClick={() => grow(p, 0, 1)}>+H</Button>
                  {!locked.has(p.key) ? <Button size="sm" variant="ghost" icon="x" aria-label="Remove from this tab" onClick={() => onRemove(id)} /> : null}
                </span>
              </div>
            ) : null}
            <div className="canvas__body" style={{ height: canArrange ? "calc(100% - 34px)" : "100%", overflow: "auto", pointerEvents: canArrange ? "none" : undefined, opacity: canArrange ? 0.85 : 1 }}>
              {render(p)}
            </div>
            {canArrange ? <div className="canvas__resize" aria-hidden="true" style={{ position: "absolute", right: 2, bottom: 2, width: 16, height: 16, cursor: "nwse-resize", touchAction: "none", borderRight: "3px solid var(--border-strong)", borderBottom: "3px solid var(--border-strong)" }} onPointerDown={(e) => onPointerDown(e, p, "resize")} /> : null}
          </div>
        );
      })}
    </div>
  );
}

export type { Placed, Size };
