// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from "react";
import { Icon } from "./Icon";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral" | "accent" | "outline";

export function Badge({ tone = "neutral", children, icon }: { tone?: Tone; children: ReactNode; icon?: string }) {
  return (
    <span className={`badge badge--${tone}`}>
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}

export type Status = "ok" | "degraded" | "failed" | "unknown" | "unavailable";

const STATUS_META: Record<Status, { tone: Tone; label: string; ring?: boolean }> = {
  ok: { tone: "ok", label: "Healthy" },
  degraded: { tone: "warn", label: "Degraded" },
  failed: { tone: "danger", label: "Failed" },
  unknown: { tone: "neutral", label: "Unknown", ring: true },
  unavailable: { tone: "neutral", label: "Not available", ring: true },
};

export function toStatus(value: string | null | undefined): Status {
  if (value === "ok" || value === "degraded" || value === "failed" || value === "unknown") return value;
  return "unavailable";
}

/** Status shown with colour AND text (never colour alone). */
export function StatusBadge({ status, label }: { status: Status; label?: string }) {
  const meta = STATUS_META[status];
  return (
    <span className={`badge badge--${meta.tone}`}>
      <span className={meta.ring ? "dot dot--ring" : "dot"} aria-hidden="true" />
      {label ?? meta.label}
    </span>
  );
}

export function StatusDot({ status, label }: { status: Status; label?: string }) {
  const meta = STATUS_META[status];
  const color = { ok: "var(--ok)", warn: "var(--warn)", danger: "var(--danger)" }[meta.tone as string] ?? "var(--neutral)";
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className={meta.ring ? "dot dot--ring" : "dot"} style={{ color }} aria-hidden="true" />
      <span>{label ?? meta.label}</span>
    </span>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok" | "neutral";
  title?: ReactNode;
  children: ReactNode;
}) {
  const icon = { info: "info", warn: "alert", danger: "error", ok: "checkCircle", neutral: "info" }[tone];
  return (
    <div className={`callout callout--${tone}`} role={tone === "danger" ? "alert" : undefined}>
      <Icon name={icon} />
      <div>
        {title ? <p className="callout__title">{title}</p> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}

/** Contextual help without tooltips: always-visible, readable guidance. */
export function InfoNote({ children }: { children: ReactNode }) {
  return <Callout tone="neutral">{children}</Callout>;
}

export function EmptyState({
  icon = "sparkle",
  title,
  children,
  action,
  compact = false,
}: {
  icon?: string;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "state state--compact" : "state"}>
      <div className="state__icon"><Icon name={icon} size={22} /></div>
      <p className="state__title">{title}</p>
      {children ? <div className="state__body">{children}</div> : null}
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function Skeleton({ width = "100%", height = 14 }: { width?: number | string; height?: number }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />;
}

export function ErrorState({
  title = "Something went wrong",
  error,
  onRetry,
  compact = false,
}: {
  title?: string;
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const e = error as { detail?: string; message?: string; requestId?: string } | null;
  const detail = e?.detail || e?.message || "An unexpected error occurred.";
  return (
    <div className={compact ? "state state--error state--compact" : "state state--error"} role="alert">
      <div className="state__icon"><Icon name="error" size={22} /></div>
      <p className="state__title">{title}</p>
      <div className="state__body">
        <p>{detail}</p>
        {e?.requestId ? <p className="subtle" style={{ marginTop: 6 }}>Request ID: <span className="mono">{e.requestId}</span></p> : null}
      </div>
      {onRetry ? (
        <button type="button" className="btn btn--secondary" onClick={onRetry}>
          <Icon name="refresh" size={16} /> Try again
        </button>
      ) : null}
    </div>
  );
}
