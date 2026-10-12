// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { BrandIcon, BrandLogo } from "../Brand";
import { Icon } from "../ui";
import { buildNav, isActive, type NavSection } from "@/lib/nav";
import { useBrowserStore } from "@/hooks/useBrowserStore";
import { useSession } from "@/hooks/useSession";

const PLANNED_KEY = "veyra.nav.planned-open";

export function Sidebar({ collapsed, onToggleCollapsed, onNavigate }: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate: () => void;
}) {
  const { session, extensions } = useSession();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const [plannedRaw, setPlannedRaw] = useBrowserStore(PLANNED_KEY, "0");
  const plannedOpen = plannedRaw === "1";

  const sections = buildNav({
    permissions: session?.permissions ?? [],
    isPlatformAdmin: session?.is_platform_admin ?? false,
    extensions,
  });
  const onPlannedPage = pathname.startsWith("/planned");

  const togglePlanned = () => setPlannedRaw(plannedOpen ? "0" : "1");

  const renderSection = (s: NavSection) => {
    const planned = s.items.every((i) => i.planned);
    const open = !planned || plannedOpen || onPlannedPage || collapsed;
    const listId = `nav-${s.id}`;
    return (
      <div className="sidebar__section" key={s.id}>
        {planned ? (
          <button type="button" className="sidebar__heading" aria-expanded={open} aria-controls={listId} onClick={togglePlanned}>
            <span className="sidebar__heading-text">{s.label} · coming later</span>
            <span className="sidebar__heading-text"><Icon name={open ? "chevronDown" : "chevronRight"} size={14} /></span>
          </button>
        ) : (
          <p className="sidebar__heading"><span className="sidebar__heading-text">{s.label}</span></p>
        )}
        <ul className="list-plain" id={listId} hidden={!open} style={{ borderTop: 0 }}>
          {s.items.map((item) => {
            const active = isActive(item.href, pathname, search);
            return (
              <li key={item.href} style={{ borderTop: 0 }}>
                <Link
                  href={item.href}
                  className={item.planned ? "sidebar__link sidebar__link--planned" : "sidebar__link"}
                  aria-current={active ? "page" : undefined}
                  title={collapsed ? item.label : undefined}
                  onClick={onNavigate}
                >
                  <Icon name={item.icon} />
                  <span className="sidebar__link-label">{item.label}</span>
                  {item.planned ? (
                    <span className="sidebar__badge">{item.planned.milestone ? `M${item.planned.milestone}` : "Planned"}</span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    );
  };

  return (
    <aside className="sidebar" id="sidebar" aria-label="Main navigation">
      <div className="sidebar__brand">
        <Link href="/" aria-label="Veyra dashboard" onClick={onNavigate}>
          <BrandLogo onDark height={26} />
          <BrandIcon />
        </Link>
        {session ? (
          <span className="sidebar__version" title={session.release ? `Release ${session.release}` : "Development build"}>
            v{session.version}
          </span>
        ) : null}
      </div>
      <nav className="sidebar__nav" aria-label="Primary">
        {sections.map(renderSection)}
      </nav>
      <div className="sidebar__footer">
        <button type="button" className="sidebar__collapse" onClick={onToggleCollapsed} aria-pressed={collapsed}>
          <Icon name={collapsed ? "chevronsRight" : "chevronsLeft"} />
          <span>{collapsed ? "Expand sidebar" : "Collapse sidebar"}</span>
          {collapsed ? <span className="sr-only">Expand sidebar</span> : null}
        </button>
      </div>
    </aside>
  );
}
