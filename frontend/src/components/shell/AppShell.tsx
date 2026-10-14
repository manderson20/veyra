// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ThemeToggle } from "../ThemeToggle";
import { ErrorState, IconButton, LoadingState } from "../ui";
import { api } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";
import { activeLocation, buildNav } from "@/lib/nav";
import { useBrowserStore } from "@/hooks/useBrowserStore";
import { EngineStatusProvider } from "@/hooks/useEngineStatus";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";
import { ApplyChanges } from "./ApplyChanges";
import { GlobalSearch } from "./GlobalSearch";
import { MfaNag } from "./MfaNag";
import { Sidebar } from "./Sidebar";
import { UserMenu } from "./UserMenu";

const COLLAPSE_KEY = "veyra.sidebar.collapsed";

export function AppShell({ children }: { children: ReactNode }) {
  const { session, loading, error, refresh, extensions } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const [collapsedRaw, setCollapsedRaw] = useBrowserStore(COLLAPSE_KEY, "0");
  const collapsed = collapsedRaw === "1";
  const [drawer, setDrawer] = useState(false);
  useOnChange(pathname, () => setDrawer(false));

  // A temporary password must be replaced before anything else is usable.
  const forcedChange = Boolean(session?.must_change_password) && !pathname.startsWith("/account");
  useEffect(() => {
    if (forcedChange) router.replace("/account/?reason=signin");
  }, [forcedChange, router]);

  useEffect(() => {
    if (loading || session || error) return;
    // Not signed in: go to setup if this installation has never been set up.
    api
      .get<SetupStatus>("/setup/status", undefined, { noRedirect: true })
      .then((s) => router.replace(s.setup_required ? "/setup/" : `/login/?next=${encodeURIComponent(pathname)}`))
      .catch(() => router.replace("/login/"));
  }, [loading, session, error, router, pathname]);

  if (error) {
    return (
      <div className="fullscreen-center">
        <ErrorState title="Cannot load Veyra" error={error} onRetry={() => void refresh()} />
      </div>
    );
  }
  if (loading || !session || forcedChange) {
    return (
      <div className="fullscreen-center">
        <LoadingState label="Loading Veyra…" />
      </div>
    );
  }

  const toggleCollapsed = () => setCollapsedRaw(collapsed ? "0" : "1");
  const location = activeLocation(
    buildNav({ permissions: session.permissions, isPlatformAdmin: session.is_platform_admin, extensions }),
    pathname,
    search,
  );

  const cls = ["shell", collapsed && "shell--collapsed", drawer && "shell--drawer-open"].filter(Boolean).join(" ");
  return (
    <EngineStatusProvider>
    <div className={cls}>
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} onNavigate={() => setDrawer(false)} drawer={drawer} />
      <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />
      <div className="main">
        <header className="topbar">
          <IconButton
            className="topbar__menu"
            icon="menu"
            label={drawer ? "Close navigation" : "Open navigation"}
            aria-expanded={drawer}
            aria-controls="sidebar"
            onClick={() => setDrawer((d) => !d)}
          />
          {location ? (
            <nav className="breadcrumb" aria-label="Breadcrumb">
              <span>{location.section.label}</span>
              <span aria-hidden="true">›</span>
              <strong>{location.item.label}</strong>
            </nav>
          ) : null}
          <GlobalSearch />
          <div className="topbar__spacer" />
          <ApplyChanges />
          <ThemeToggle />
          <UserMenu />
        </header>
        <MfaNag />
        <main id="main" className="content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
    </EngineStatusProvider>
  );
}
