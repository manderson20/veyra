// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type ReactNode } from "react";

/* Report charts (docs/REPORTING.md §5.1). Colors are the validated --viz-*
   tokens in fixed order; every chart has hover details and a table view. */

export interface StackSeries {
  key: string;
  label: string;
  color: string;
}

function TableToggle({ children, caption }: { children: ReactNode; caption: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "Hide table" : "Show table"}
      </button>
      {open ? (
        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table className="table"><caption className="sr-only">{caption}</caption>{children}</table>
        </div>
      ) : null}
    </div>
  );
}

/** Stacked bars over days (one bar per row of `data`). */
export function StackedBars<T extends Record<string, number | string>>({ data, series, xKey, xLabel, caption, height = 180, unit = "", xHeader = "Day" }: {
  data: T[];
  series: StackSeries[];
  xKey: keyof T & string;
  xLabel: (x: string) => string;
  caption: string;
  height?: number;
  /** After "max N" on the axis, e.g. " per day". */
  unit?: string;
  xHeader?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { top: 8, bottom: 4 };
  const totals = data.map((d) => series.reduce((sum, s) => sum + Number(d[s.key] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const slot = width / Math.max(1, data.length);
  const bar = Math.max(2, Math.min(28, slot * 0.7));
  const plotH = height - pad.top - pad.bottom;
  const gap = 2;
  const hovered = hover !== null ? data[hover] : null;
  // Recessive gridlines at round values.
  const step = Math.max(1, Math.ceil(max / 4 / 5) * 5);
  const grid = Array.from({ length: Math.floor(max / step) }, (_, i) => (i + 1) * step);
  return (
    <div className="chart">
      <div style={{ position: "relative" }}>
        <svg viewBox={`0 0 ${width} ${height}`} className="chart__svg" style={{ height }} role="img" aria-label={caption} preserveAspectRatio="none"
          onMouseLeave={() => setHover(null)}>
          {grid.map((g) => {
            const y = pad.top + plotH - (g / max) * plotH;
            return <line key={g} x1={0} x2={width} y1={y} y2={y} className="chart__grid" />;
          })}
          {data.map((d, i) => {
            const x = i * slot + (slot - bar) / 2;
            let y = pad.top + plotH;
            const parts = series.map((s) => ({ s, v: Number(d[s.key] ?? 0) })).filter((p) => p.v > 0);
            return (
              <g key={String(d[xKey])}>
                {parts.map((p, j) => {
                  const h = (p.v / max) * plotH;
                  y -= h;
                  const top = j === parts.length - 1;
                  const segH = Math.max(1, h - (top ? 0 : gap));
                  const r = top ? Math.min(4, bar / 2, segH) : 0;
                  const yy = y + (top ? 0 : gap);
                  // The top of the stack has rounded corners; the baseline stays square.
                  const path = r
                    ? `M${x},${yy + segH} V${yy + r} Q${x},${yy} ${x + r},${yy} H${x + bar - r} Q${x + bar},${yy} ${x + bar},${yy + r} V${yy + segH} Z`
                    : `M${x},${yy} h${bar} v${segH} h${-bar} Z`;
                  return <path key={p.s.key} d={path} fill={p.s.color} opacity={hover === null || hover === i ? 1 : 0.45} />;
                })}
                {/* Hit target wider than the bar. */}
                <rect x={i * slot} y={0} width={slot} height={height} fill="transparent" onMouseEnter={() => setHover(i)} />
              </g>
            );
          })}
        </svg>
        {hovered ? (
          <div className="chart-tip" style={{ left: `${Math.min(80, Math.max(0, ((hover! + 0.5) / data.length) * 100))}%` }} role="status">
            <strong>{xLabel(String(hovered[xKey]))}</strong>
            {series.map((s) => (
              <span key={s.key} className="chart__legend-item"><span className="chart__swatch" style={{ background: s.color }} />{s.label} <strong>{Number(hovered[s.key] ?? 0)}</strong></span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="chart__axis" aria-hidden="true">
        <span>{data.length ? xLabel(String(data[0]![xKey])) : ""}</span>
        <span>max {max}{unit}</span>
        <span>{data.length ? xLabel(String(data[data.length - 1]![xKey])) : ""}</span>
      </div>
      <div className="chart__legend">
        {series.map((s) => <span key={s.key} className="chart__legend-item"><span className="chart__swatch" style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <TableToggle caption={caption}>
        <thead><tr><th scope="col">{xHeader}</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}<th scope="col">Total</th></tr></thead>
        <tbody>{data.map((d, i) => <tr key={String(d[xKey])}><td>{xLabel(String(d[xKey]))}</td>{series.map((s) => <td key={s.key}>{Number(d[s.key] ?? 0)}</td>)}<td>{totals[i]}</td></tr>)}</tbody>
      </TableToggle>
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Weekday × hour grid, one hue from light (few calls) to dark (many). */
export function HourGrid({ grid, caption }: { grid: number[][]; caption: string }) {
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null);
  const max = Math.max(1, ...grid.flat());
  const shade = (n: number) => (n === 0 ? "var(--surface-2, transparent)" : `color-mix(in oklab, var(--viz-seq) ${Math.round(18 + (n / max) * 82)}%, var(--surface))`);
  return (
    <div className="chart">
      <div className="hourgrid" role="img" aria-label={caption} onMouseLeave={() => setHover(null)}>
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="hourgrid__hour" aria-hidden="true">{h % 3 === 0 ? h : ""}</span>)}
        {grid.map((row, d) => (
          <div key={d} style={{ display: "contents" }}>
            <span className="hourgrid__day" aria-hidden="true">{WEEKDAYS[d]}</span>
            {row.map((n, h) => (
              <span key={h} className="hourgrid__cell" style={{ background: shade(n), outline: hover?.d === d && hover?.h === h ? "2px solid var(--text)" : undefined }}
                onMouseEnter={() => setHover({ d, h })} />
            ))}
          </div>
        ))}
      </div>
      <p className="subtle" style={{ margin: 0, minHeight: "1.4em" }} role="status">
        {hover ? <>{WEEKDAYS[hover.d]} {String(hover.h).padStart(2, "0")}:00–{String(hover.h).padStart(2, "0")}:59 · <strong>{grid[hover.d]![hover.h]}</strong> calls</> : `Darker is busier (most: ${max} calls in one hour slot).`}
      </p>
      <TableToggle caption={caption}>
        <thead><tr><th scope="col">Day</th>{Array.from({ length: 24 }, (_, h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{grid.map((row, d) => <tr key={d}><th scope="row">{WEEKDAYS[d]}</th>{row.map((n, h) => <td key={h}>{n || ""}</td>)}</tr>)}</tbody>
      </TableToggle>
    </div>
  );
}

/** Lines over categories (one line per series); same rules as StackedBars. */
export function LineChart<T extends Record<string, number | string>>({ data, series, xKey, xLabel, caption, height = 180 }: {
  data: T[];
  series: StackSeries[];
  xKey: keyof T & string;
  xLabel: (x: string) => string;
  caption: string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { top: 10, bottom: 6, side: 8 };
  const max = Math.max(1, ...data.flatMap((d) => series.map((s) => Number(d[s.key] ?? 0))));
  const plotH = height - pad.top - pad.bottom;
  const x = (i: number) => (data.length <= 1 ? width / 2 : pad.side + (i * (width - 2 * pad.side)) / (data.length - 1));
  const y = (v: number) => pad.top + plotH - (v / max) * plotH;
  const hovered = hover !== null ? data[hover] : null;
  return (
    <div className="chart">
      <div style={{ position: "relative" }}>
        <svg viewBox={`0 0 ${width} ${height}`} className="chart__svg" style={{ height }} role="img" aria-label={caption} preserveAspectRatio="none"
          onMouseLeave={() => setHover(null)}>
          {[0.25, 0.5, 0.75, 1].map((f) => <line key={f} x1={0} x2={width} y1={y(max * f)} y2={y(max * f)} className="chart__grid" />)}
          {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={height - pad.bottom} className="chart__cursor" /> : null}
          {series.map((s) => (
            <g key={s.key}>
              <polyline fill="none" stroke={s.color} strokeWidth={2} vectorEffect="non-scaling-stroke"
                points={data.map((d, i) => `${x(i)},${y(Number(d[s.key] ?? 0))}`).join(" ")} />
              {hover !== null ? <circle cx={x(hover)} cy={y(Number(data[hover]![s.key] ?? 0))} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null}
            </g>
          ))}
          {data.map((d, i) => (
            <rect key={String(d[xKey])} x={x(i) - width / Math.max(2, data.length) / 2} y={0} width={width / Math.max(2, data.length)} height={height}
              fill="transparent" onMouseEnter={() => setHover(i)} />
          ))}
        </svg>
        {hovered ? (
          <div className="chart-tip" style={{ left: `${Math.min(80, Math.max(0, (x(hover!) / width) * 100))}%` }} role="status">
            <strong>{xLabel(String(hovered[xKey]))}</strong>
            {series.map((s) => (
              <span key={s.key} className="chart__legend-item"><span className="chart__swatch" style={{ background: s.color }} />{s.label} <strong>{Number(hovered[s.key] ?? 0)}</strong></span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="chart__axis" aria-hidden="true">
        <span>{data.length ? xLabel(String(data[0]![xKey])) : ""}</span>
        <span>max {max}</span>
        <span>{data.length ? xLabel(String(data[data.length - 1]![xKey])) : ""}</span>
      </div>
      {series.length > 1 ? (
        <div className="chart__legend">
          {series.map((s) => <span key={s.key} className="chart__legend-item"><span className="chart__swatch" style={{ background: s.color }} />{s.label}</span>)}
        </div>
      ) : null}
      <TableToggle caption={caption}>
        <thead><tr><th scope="col">{" "}</th>{series.map((s) => <th key={s.key} scope="col">{s.label}</th>)}</tr></thead>
        <tbody>{data.map((d) => <tr key={String(d[xKey])}><td>{xLabel(String(d[xKey]))}</td>{series.map((s) => <td key={s.key}>{Number(d[s.key] ?? 0)}</td>)}</tr>)}</tbody>
      </TableToggle>
    </div>
  );
}
