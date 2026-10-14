// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useId, useState } from "react";

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
  /** Draw as a filled area (first series only looks best). */
  area?: boolean;
}

export interface ChartPoint {
  at: string;
}

function valueOf(point: ChartPoint, key: string): number {
  return Number((point as unknown as Record<string, unknown>)[key] ?? 0);
}

/** Scale `value` into the drawing box; exported for tests. */
export function scaleY(value: number, max: number, height: number, pad = 4): number {
  if (max <= 0) return height - pad;
  return pad + (1 - value / max) * (height - 2 * pad);
}

/** A "nice" axis maximum: the smallest of 1, 2, 5 × 10ⁿ at or above `max` (at least `floor`). */
export function niceMax(max: number, floor = 4): number {
  const target = Math.max(max, floor);
  const power = Math.pow(10, Math.floor(Math.log10(target)));
  for (const m of [1, 2, 5, 10]) if (m * power >= target) return m * power;
  return 10 * power;
}

export function formatTick(at: string, rangeSeconds: number): string {
  const d = new Date(at);
  if (rangeSeconds > 2 * 86400) return d.toLocaleDateString(undefined, { weekday: "short", hour: "2-digit" });
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** A small SVG line/area chart with no dependencies (docs/INTERFACE_REWORK.md §2.3). */
export function Chart<T extends ChartPoint>({ points, series, rangeSeconds, height = 160, ariaLabel }: {
  points: T[];
  series: ChartSeries[];
  rangeSeconds: number;
  height?: number;
  ariaLabel: string;
}) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const width = 600;
  const padX = 8;
  const max = niceMax(Math.max(0, ...points.flatMap((p) => series.map((s) => valueOf(p, s.key)))));
  const n = points.length;
  const x = (i: number) => (n <= 1 ? width / 2 : padX + (i / (n - 1)) * (width - 2 * padX));
  const path = (key: string) => points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${scaleY(valueOf(p, key), max, height).toFixed(1)}`).join(" ");
  const ticks = [0, max / 2, max];
  const hovered = hover !== null ? points[hover] : undefined;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart__svg" role="img" aria-labelledby={`${id}-title`} preserveAspectRatio="none"
        onMouseMove={(e) => {
          if (!n) return;
          const rect = e.currentTarget.getBoundingClientRect();
          const rel = (e.clientX - rect.left) / rect.width;
          setHover(Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1)))));
        }}
        onMouseLeave={() => setHover(null)}>
        <title id={`${id}-title`}>{ariaLabel}</title>
        {ticks.map((t) => <line key={t} x1={0} x2={width} y1={scaleY(t, max, height)} y2={scaleY(t, max, height)} className="chart__grid" />)}
        {n ? series.map((s) => (
          <g key={s.key}>
            {s.area && n > 1 ? <path d={`${path(s.key)} L${x(n - 1).toFixed(1)},${height - 4} L${x(0).toFixed(1)},${height - 4} Z`} fill={s.color} opacity={0.12} /> : null}
            <path d={path(s.key)} fill="none" stroke={s.color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
          </g>
        )) : null}
        {hover !== null && n ? <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} className="chart__cursor" /> : null}
      </svg>
      <div className="chart__axis" aria-hidden="true">
        <span>{n ? formatTick(points[0]!.at, rangeSeconds) : ""}</span>
        <span className="chart__max">max {max}</span>
        <span>{n ? formatTick(points[n - 1]!.at, rangeSeconds) : ""}</span>
      </div>
      <div className="chart__legend" aria-hidden="true">
        {series.map((s) => (
          <span key={s.key} className="chart__legend-item"><span className="chart__swatch" style={{ background: s.color }} />{s.label}{hovered ? <strong> {valueOf(hovered, s.key)}</strong> : null}</span>
        ))}
        {hovered ? <span className="subtle">{new Date(hovered.at).toLocaleString()}</span> : null}
      </div>
      {n === 0 ? <p className="muted chart__empty">No samples in this range yet.</p> : null}
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <thead><tr><th>Time</th>{series.map((s) => <th key={s.key}>{s.label}</th>)}</tr></thead>
        <tbody>{points.map((p) => <tr key={p.at}><td>{new Date(p.at).toLocaleString()}</td>{series.map((s) => <td key={s.key}>{valueOf(p, s.key)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
