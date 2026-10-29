// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, SearchInput } from "@/components/ui";
import type { TemplateCatalog, TemplateVariable } from "@/lib/types";

interface Item {
  key: string;
  label: string;
  description: string;
  text: string;
  sensitive?: boolean;
}

interface Section {
  key: string;
  title: string;
  description: string;
  items: Item[];
  loop?: { label: string; text: string };
}

function sections(catalog: TemplateCatalog, variables: TemplateVariable[]): Section[] {
  const values: Section = {
    key: "values",
    title: "This template's values",
    description: "Variables set on the profile or device, with the template's defaults.",
    items: variables.map((v) => ({ key: `v:${v.name}`, label: v.name, description: v.description || `${v.type} value`, text: `{{ ${v.name} }}`, sensitive: v.sensitive })),
  };
  const facts: Section[] = catalog.groups.map((g) => ({
    key: g.key,
    title: g.title,
    description: g.description,
    items: g.facts.map((f) => ({ key: `${g.key}:${f.expr}`, label: f.expr, description: f.description, text: `{{ ${f.expr} }}`, sensitive: f.sensitive })),
    loop: g.loop ? { label: g.loop.split("\n")[0]!, text: g.loop.replace("{}", "") } : undefined,
  }));
  const snippets: Section = {
    key: "snippets",
    title: "Snippets",
    description: "Common Jinja patterns.",
    items: catalog.snippets.map((s) => ({ key: `s:${s.title}`, label: s.title, description: s.description, text: s.text })),
  };
  return [values, ...facts, snippets];
}

/** The template editor's "Insert a Veyra variable" panel: click an entry to
 *  insert it at the cursor (docs/DEVICE_PROVISIONING.md §7). */
export function InsertPanel({ catalog, variables, onInsert }: { catalog: TemplateCatalog; variables: TemplateVariable[]; onInsert: (text: string) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>("values");
  const q = query.trim().toLowerCase();
  const all = sections(catalog, variables);
  const shown = all
    .map((s) => ({ ...s, items: q ? s.items.filter((i) => `${i.label} ${i.description}`.toLowerCase().includes(q)) : s.items }))
    .filter((s) => !q || s.items.length > 0);

  return (
    <div className="insert-panel">
      <div className="insert-panel__head">
        <strong>Insert a Veyra variable</strong>
        <span className="subtle">Click to insert at the cursor.</span>
        <SearchInput value={query} onChange={setQuery} placeholder="Search variables" label="Search variables" />
      </div>
      <div className="insert-panel__body">
        {shown.length === 0 ? <p className="subtle" style={{ padding: "var(--space-3)" }}>Nothing matches “{query}”.</p> : null}
        {shown.map((s) => {
          const expanded = !!q || open === s.key;
          return (
            <section key={s.key} className="insert-panel__section">
              <button type="button" className="insert-panel__title" aria-expanded={expanded} onClick={() => setOpen(expanded && !q ? null : s.key)}>
                <span>{s.title}</span><span className="subtle">{s.items.length}</span>
              </button>
              {expanded ? (
                <div className="insert-panel__items">
                  <p className="subtle insert-panel__note">{s.description}</p>
                  {s.loop ? (
                    <button type="button" className="insert-panel__item" onClick={() => onInsert(s.loop!.text)}>
                      <span className="mono">{s.loop.label}</span>
                      <span className="subtle">Insert the loop; the entries below go inside it.</span>
                    </button>
                  ) : null}
                  {s.items.length === 0 ? <p className="subtle insert-panel__note">This template declares no values of its own.</p> : null}
                  {s.items.map((i) => (
                    <button type="button" key={i.key} className="insert-panel__item" title={i.text} onClick={() => onInsert(i.text)}>
                      <span className="mono">{i.label}{i.sensitive ? <> <Badge tone="warn">secret</Badge></> : null}</span>
                      <span className="subtle">{i.description}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
