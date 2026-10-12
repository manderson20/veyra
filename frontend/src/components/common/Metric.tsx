import type { ReactNode } from "react";
import { Icon } from "../ui";

export function Meter({ percent, label }: { percent: number | null; label: string }) {
  if (percent === null) return null;
  const tone = percent >= 90 ? "meter__bar meter__bar--danger" : percent >= 75 ? "meter__bar meter__bar--warn" : "meter__bar";
  return (
    <div className="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}>
      <div className={tone} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
    </div>
  );
}

export function MetricCard({ icon, label, value, hint, children }: {
  icon: string;
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="card metric">
      <span className="metric__label"><Icon name={icon} size={16} /> {label}</span>
      <span className="metric__value">{value}</span>
      {children}
      {hint ? <span className="metric__hint">{hint}</span> : null}
    </div>
  );
}
