"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Icon } from "./Icon";

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  label = "Search",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  label?: string;
}) {
  const id = useId();
  return (
    <div className="search" role="search">
      <label htmlFor={id} className="sr-only">{label}</label>
      <span className="search__icon"><Icon name="search" size={16} /></span>
      <input
        id={id}
        className="input"
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{ minWidth: 240 }}
      />
    </div>
  );
}

export interface TabDef {
  id: string;
  label: ReactNode;
}

/** WAI-ARIA tabs with arrow-key navigation. Render panels with TabPanel. */
export function Tabs({ tabs, active, onChange, idBase }: { tabs: TabDef[]; active: string; onChange: (id: string) => void; idBase: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, index: number) => {
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    const tab = tabs[next];
    if (tab) {
      onChange(tab.id);
      refs.current[next]?.focus();
    }
  };
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          id={`${idBase}-tab-${t.id}`}
          aria-controls={`${idBase}-panel-${t.id}`}
          aria-selected={active === t.id}
          tabIndex={active === t.id ? 0 : -1}
          className="tab"
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ idBase, id, active, children }: { idBase: string; id: string; active: string; children: ReactNode }) {
  if (active !== id) return null;
  return (
    <div role="tabpanel" id={`${idBase}-panel-${id}`} aria-labelledby={`${idBase}-tab-${id}`}>
      {children}
    </div>
  );
}

export interface StepDef {
  key: string;
  title: string;
  available: boolean;
  note?: string;
}

export function Stepper({ steps, current, completed }: { steps: StepDef[]; current: string; completed: Set<string> }) {
  let n = 0;
  return (
    <ol className="stepper" aria-label="Setup steps">
      {steps.map((s) => {
        if (s.available) n++;
        const done = completed.has(s.key);
        const cls = ["stepper__item", done && "stepper__item--done", !s.available && "stepper__item--later"].filter(Boolean).join(" ");
        return (
          <li key={s.key} className={cls} aria-current={current === s.key ? "step" : undefined}>
            <span className="stepper__marker" aria-hidden="true">
              {done ? <Icon name="check" size={12} strokeWidth={3} /> : s.available ? n : ""}
            </span>
            <span>
              {s.title}
              {!s.available ? <span className="subtle" style={{ display: "block" }}>{s.note ?? "Coming later"}</span> : null}
              {done ? <span className="sr-only"> (completed)</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
