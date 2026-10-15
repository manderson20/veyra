// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { BrandIcon, BrandLogo } from "../Brand";
import { Icon } from "../ui";
import { activeLocation, buildNav, groupItems, isActive, type NavItem, type NavSection } from "@/lib/nav";
import { useSession } from "@/hooks/useSession";

const HOVER_OPEN_MS = 150;
const HOVER_CLOSE_MS = 250;

/**
 * The navigation rail: one row per category; a flyout panel lists the
 * category's pages (docs/INTERFACE_REWORK.md §1). In the mobile drawer the
 * category expands inline instead.
 */
export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, drawer }: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate: () => void;
  drawer: boolean;
}) {
  const { session, extensions } = useSession();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  // The open category is remembered with the route it was opened on, so a
  // navigation closes it without an effect.
  const navKey = `${pathname}?${search}`;
  const [openFor, setOpenFor] = useState<{ id: string; navKey: string } | null>(null);
  const open = openFor && openFor.navKey === navKey ? openFor.id : null;
  const setOpen = (value: string | null | ((o: string | null) => string | null)) =>
    setOpenFor((prev) => {
      const prevId = prev && prev.navKey === navKey ? prev.id : null;
      const next = typeof value === "function" ? value(prevId) : value;
      return next ? { id: next, navKey } : null;
    });
  const [hoverable, setHoverable] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  );
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);
  const flyoutRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLElement>(null);

  const sections = buildNav({
    permissions: session?.permissions ?? [],
    isPlatformAdmin: session?.is_platform_admin ?? false,
    extensions,
  });
  const current = activeLocation(sections, pathname, search);

  useEffect(() => {
    const mq = window.matchMedia("(hover: hover) and (pointer: fine)");
    const listener = (e: MediaQueryListEvent) => setHoverable(e.matches);
    mq.addEventListener("change", listener);
    return () => mq.removeEventListener("change", listener);
  }, []);

  // Close when clicking outside the rail and the flyout.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (railRef.current?.contains(t) || flyoutRef.current?.contains(t)) return;
      setOpenFor(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const clearTimers = () => {
    if (openTimer.current) window.clearTimeout(openTimer.current);
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    openTimer.current = closeTimer.current = null;
  };
  const hoverOpen = (id: string) => {
    if (!hoverable || drawer) return;
    clearTimers();
    openTimer.current = window.setTimeout(() => setOpen(id), HOVER_OPEN_MS);
  };
  const hoverClose = () => {
    if (!hoverable || drawer) return;
    clearTimers();
    closeTimer.current = window.setTimeout(() => setOpen(null), HOVER_CLOSE_MS);
  };
  const keepOpen = () => clearTimers();

  const toggle = (id: string) => {
    clearTimers();
    setOpen((o) => (o === id ? null : id));
  };
  const onRailKey = (e: KeyboardEvent<HTMLButtonElement>, id: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      clearTimers();
      setOpen(id);
      window.setTimeout(() => flyoutRef.current?.querySelector<HTMLElement>("a")?.focus(), 0);
    } else if (e.key === "Escape") {
      setOpen(null);
    }
  };
  const onFlyoutKey = (e: KeyboardEvent<HTMLDivElement>, id: string) => {
    const links = Array.from(flyoutRef.current?.querySelectorAll<HTMLElement>("a") ?? []);
    const i = links.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      links[Math.min(links.length - 1, i + 1)]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      links[Math.max(0, i - 1)]?.focus();
    } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      // Jump to the first page of the next or previous column.
      const groups = Array.from(flyoutRef.current?.querySelectorAll<HTMLElement>(".flyout__group") ?? []);
      const g = groups.findIndex((el) => el.contains(document.activeElement));
      const target = groups[e.key === "ArrowRight" ? Math.min(groups.length - 1, g + 1) : Math.max(0, g - 1)];
      if (target) {
        e.preventDefault();
        target.querySelector<HTMLElement>("a")?.focus();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(null);
      railRef.current?.querySelector<HTMLElement>(`[data-section="${id}"]`)?.focus();
    }
  };

  const renderLinks = (items: NavItem[]) =>
    items.map((item) => {
      const active = isActive(item.href, pathname, search);
      return (
        <li key={item.href} style={{ borderTop: 0 }}>
          <Link href={item.href} className={item.planned ? "flyout__link flyout__link--planned" : "flyout__link"} aria-current={active ? "page" : undefined} onClick={() => { setOpen(null); onNavigate(); }}>
            <Icon name={item.icon} size={18} />
            <span className="flyout__link-label">{item.label}</span>
            {item.planned ? <span className="sidebar__badge">{item.planned.milestone ? `M${item.planned.milestone}` : "Planned"}</span> : null}
          </Link>
        </li>
      );
    });

  // Drawer: one list with small group headings. Flyout: one column per group.
  const renderItems = (s: NavSection, inline: boolean) => {
    const groups = groupItems(s.items);
    const titled = groups.length > 1;
    if (inline) {
      return (
        <div className="rail__inline" id={`nav-${s.id}`}>
          {groups.map((g) => (
            <div key={g.label ?? "_"}>
              {titled && g.label ? <div className="rail__group-title">{g.label}</div> : null}
              <ul className="list-plain" role="list">{renderLinks(g.items)}</ul>
            </div>
          ))}
        </div>
      );
    }
    return (
      <div className="flyout__columns" id={`nav-${s.id}`}>
        {groups.map((g, i) => (
          <section key={g.label ?? "_"} className="flyout__group" data-group={i} aria-label={g.label ?? undefined}>
            {titled && g.label ? <h3 className="flyout__group-title">{g.label}</h3> : null}
            <ul className="flyout__list list-plain" role="list">{renderLinks(g.items)}</ul>
          </section>
        ))}
      </div>
    );
  };

  const openSection = sections.find((s) => s.id === open) ?? null;
  return (
    <>
      <aside className="sidebar sidebar--rail" id="sidebar" aria-label="Main navigation" ref={railRef as never} onMouseLeave={hoverClose} onMouseEnter={keepOpen}>
        <div className="sidebar__brand">
          <Link href="/" aria-label="Veyra dashboard" onClick={onNavigate}>
            <BrandLogo onDark height={26} />
            <BrandIcon />
          </Link>
          {session ? (
            <span className="sidebar__version" title={session.release ? `Release ${session.release}` : "Development build"}>v{session.version}</span>
          ) : null}
        </div>
        <nav className="rail" aria-label="Primary">
          <ul className="list-plain" role="list">
            {sections.map((s) => {
              const isCurrent = current?.section.id === s.id;
              const isOpen = open === s.id;
              const only = s.items.length === 1 ? s.items[0] : null;
              if (only) {
                // A category with one page (Overview → Dashboard) is a plain link.
                return (
                  <li key={s.id} style={{ borderTop: 0 }} onMouseEnter={() => { clearTimers(); setOpen(null); }}>
                    <Link href={only.href} className={`rail__button${isCurrent ? " rail__button--current" : ""}`} aria-current={isCurrent ? "page" : undefined}
                      title={collapsed ? s.label : undefined} onClick={() => { setOpen(null); onNavigate(); }}>
                      <Icon name={s.icon ?? only.icon} />
                      <span className="rail__label">{s.label}</span>
                    </Link>
                  </li>
                );
              }
              return (
                <li key={s.id} style={{ borderTop: 0 }} onMouseEnter={() => hoverOpen(s.id)}>
                  <button type="button" className={`rail__button${isCurrent ? " rail__button--current" : ""}${isOpen ? " rail__button--open" : ""}`}
                    data-section={s.id} aria-expanded={isOpen} aria-controls={`nav-${s.id}`} aria-haspopup="true" title={collapsed ? s.label : undefined}
                    onClick={() => toggle(s.id)} onKeyDown={(e) => onRailKey(e, s.id)}>
                    <Icon name={s.icon ?? "dashboard"} />
                    <span className="rail__label">{s.label}</span>
                    <Icon name={drawer ? (isOpen ? "chevronDown" : "chevronRight") : "chevronRight"} size={14} />
                  </button>
                  {drawer && isOpen ? renderItems(s, true) : null}
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="sidebar__footer">
          <button type="button" className="sidebar__collapse" onClick={onToggleCollapsed} aria-pressed={collapsed}>
            <Icon name={collapsed ? "chevronsRight" : "chevronsLeft"} />
            <span>{collapsed ? "Expand sidebar" : "Collapse sidebar"}</span>
            {collapsed ? <span className="sr-only">Expand sidebar</span> : null}
          </button>
        </div>
      </aside>
      {openSection && !drawer ? (
        <div className="flyout" ref={flyoutRef} style={{ ["--flyout-cols" as string]: Math.min(4, groupItems(openSection.items).length) }} role="region" aria-label={`${openSection.label} pages`} onMouseEnter={keepOpen} onMouseLeave={hoverClose} onKeyDown={(e) => onFlyoutKey(e, openSection.id)}>
          <div className="flyout__head">
            <span className="flyout__title">{openSection.label}</span>
            {openSection.description ? <span className="flyout__description">{openSection.description}</span> : null}
          </div>
          {renderItems(openSection, false)}
        </div>
      ) : null}
    </>
  );
}
