"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "../ui";
import { api } from "@/lib/api";
import { buildNav } from "@/lib/nav";
import type { SearchResult } from "@/lib/types";
import { useSession } from "@/hooks/useSession";

const NO_RESULTS: SearchResult[] = [];

interface Item {
  group: string;
  title: string;
  subtitle?: string;
  href: string;
  icon: string;
}

/** Global search: pages the user can open plus organizations and users from the API. */
export function GlobalSearch() {
  const router = useRouter();
  const { session, extensions } = useSession();
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  // Results are tagged with the term they belong to, so stale results are never shown.
  const [remote, setRemote] = useState<{ term: string; results: SearchResult[] }>({ term: "", results: [] });
  const [activeRaw, setActive] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const term = q.trim();
  useEffect(() => {
    if (term.length < 2) return;
    const ctrl = new AbortController();
    const t = window.setTimeout(() => {
      api
        .get<{ results: SearchResult[] }>("/search", { q: term }, { signal: ctrl.signal })
        .then((r) => setRemote({ term, results: r.results }))
        .catch((e: unknown) => {
          if (!(e instanceof DOMException && e.name === "AbortError")) setRemote({ term, results: [] });
        });
    }, 200);
    return () => {
      ctrl.abort();
      window.clearTimeout(t);
    };
  }, [term]);
  const loading = term.length >= 2 && remote.term !== term;
  const remoteResults = useMemo(() => (remote.term === term ? remote.results : NO_RESULTS), [remote, term]);

  const items = useMemo<Item[]>(() => {
    const needle = term.toLowerCase();
    if (!needle) return [];
    const pages = buildNav({
      permissions: session?.permissions ?? [],
      isPlatformAdmin: session?.is_platform_admin ?? false,
      extensions,
    })
      .flatMap((s) => s.items)
      .filter((i) => i.label.toLowerCase().includes(needle))
      .slice(0, 6)
      .map((i) => ({ group: "Pages", title: i.label, subtitle: i.planned ? "Coming later" : undefined, href: i.href, icon: i.icon }));
    const records = remoteResults.map((r) => ({
      group: r.type === "user" ? "Users" : "Organizations",
      title: r.title,
      subtitle: r.subtitle,
      href: r.href,
      icon: r.type === "user" ? "users" : "building",
    }));
    return [...pages, ...records];
  }, [term, remoteResults, session, extensions]);
  const active = Math.min(activeRaw, Math.max(items.length - 1, 0));

  const go = (item: Item | undefined) => {
    if (!item) return;
    setOpen(false);
    setQ("");
    router.push(item.href);
  };

  const showList = open && q.trim().length > 0;
  let lastGroup = "";
  return (
    <div className="global-search" role="search">
      <div className="search">
        <span className="search__icon"><Icon name="search" size={16} /></span>
        <label htmlFor={`${listId}-input`} className="sr-only">Search Veyra</label>
        <input
          ref={inputRef}
          id={`${listId}-input`}
          className="input"
          type="text"
          placeholder="Search pages, organizations, users…"
          value={q}
          autoComplete="off"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && items[active] ? `${listId}-opt-${active}` : undefined}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, items.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              go(items[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
              (e.target as HTMLInputElement).blur();
            }
          }}
        />
        {!q ? <kbd className="search__kbd">/</kbd> : null}
      </div>
      {showList ? (
        <ul className="global-search__results" id={listId} role="listbox" aria-label="Search results">
          {items.length === 0 ? (
            <li className="global-search__empty" role="presentation">
              {loading ? "Searching…" : term.length < 2 ? "Keep typing to search records." : "No results."}
            </li>
          ) : (
            items.map((item, i) => {
              const header = item.group !== lastGroup ? item.group : null;
              lastGroup = item.group;
              return (
                <li key={`${item.group}-${item.href}`} role="presentation">
                  {header ? <div className="global-search__group" aria-hidden="true">{header}</div> : null}
                  <div
                    id={`${listId}-opt-${i}`}
                    role="option"
                    aria-selected={i === active}
                    className="global-search__item"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      go(item);
                    }}
                    onMouseEnter={() => setActive(i)}
                  >
                    <Icon name={item.icon} size={16} />
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: "block" }}>{item.title}</span>
                      {item.subtitle ? <span className="subtle">{item.subtitle}</span> : null}
                    </span>
                  </div>
                </li>
              );
            })
          )}
        </ul>
      ) : null}
    </div>
  );
}
