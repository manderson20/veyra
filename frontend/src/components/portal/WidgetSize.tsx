// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { COLS, ROW_PX } from "@/portal/layout";

/** The size a widget was placed at (docs/USER_PORTAL.md §10): widgets adapt
 * their content to it instead of being cropped. Outside the canvas a widget
 * is as large as it likes. */
export interface WidgetSize {
  /** Grid columns and rows of the placement. */
  w: number;
  h: number;
  /** Pixels available for content below the card header. */
  heightPx: number;
  /** Short widget: forms fold behind a button, secondary rows go. */
  compact: boolean;
  /** Narrow widget (under half the canvas): secondary text is hidden. */
  narrow: boolean;
  /** Rows of a list (about 56 px each) that fit, after `reserve` px. */
  rowsFor: (reserve?: number) => number;
}

// Card header and body padding.
const FRAME_PX = 100;
const ROW_HEIGHT_PX = 56;

const unbounded: WidgetSize = {
  w: COLS,
  h: 999,
  heightPx: Number.POSITIVE_INFINITY,
  compact: false,
  narrow: false,
  rowsFor: () => Number.POSITIVE_INFINITY,
};

const WidgetSizeContext = createContext<WidgetSize>(unbounded);

export function WidgetSizeProvider({ w, h, cols, children }: { w: number; h: number; cols: number; children: ReactNode }) {
  const heightPx = Math.max(0, h * ROW_PX - FRAME_PX);
  const value: WidgetSize = {
    w,
    h,
    heightPx,
    compact: h < 8,
    narrow: cols > 1 && w / cols < 0.45,
    rowsFor: (reserve = 0) => Math.max(2, Math.floor((heightPx - reserve) / ROW_HEIGHT_PX)),
  };
  return <WidgetSizeContext.Provider value={value}>{children}</WidgetSizeContext.Provider>;
}

export function useWidgetSize(): WidgetSize {
  return useContext(WidgetSizeContext);
}

export interface RowLimit {
  limit: number;
  hidden: number;
  all: boolean;
  canToggle: boolean;
  toggle: () => void;
}

/** How many rows of a list to show in this widget, with a "show all" toggle;
 * `reserve` is the height of what sits above the list (search, filters). */
export function useRowLimit(total: number, reserve = 0): RowLimit {
  const size = useWidgetSize();
  const [all, setAll] = useState(false);
  const fit = size.rowsFor(reserve);
  const canToggle = Number.isFinite(fit) && total > fit;
  const limit = all || !canToggle ? total : fit;
  return { limit, hidden: total - limit, all, canToggle, toggle: () => setAll((v) => !v) };
}

export function MoreRows({ hidden, all, canToggle, toggle }: RowLimit) {
  if (!canToggle) return null;
  return (
    <div>
      <button type="button" className="btn btn--ghost btn--sm" onClick={toggle}>
        {all ? "Show fewer" : `Show all (${hidden} more)`}
      </button>
    </div>
  );
}
