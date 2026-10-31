// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { PhoneBrand, SessionInfo, UiExtension } from "@/lib/types";

interface SessionState {
  session: SessionInfo | null;
  extensions: UiExtension[];
  brands: string[];
  loading: boolean;
  error: unknown;
  refresh: () => Promise<void>;
  can: (permission: string) => boolean;
}

const SessionContext = createContext<SessionState | null>(null);

interface Loaded {
  session: SessionInfo | null;
  extensions: UiExtension[];
  brands: string[];
  error: unknown;
}

async function loadSession(): Promise<Loaded> {
  try {
    const session = await api.get<SessionInfo>("/auth/session", undefined, { noRedirect: true });
    let extensions: UiExtension[] = [];
    try {
      extensions = await api.get<UiExtension[]>("/modules/ui-extensions", undefined, { noRedirect: true });
    } catch {
      /* navigation from modules is optional */
    }
    let brands: string[] = [];
    if (session.is_platform_admin || session.permissions.includes("devices.read") || session.permissions.includes("*")) {
      try {
        brands = (await api.get<PhoneBrand[]>("/device-profiles/brands", undefined, { noRedirect: true })).map((b) => b.name);
      } catch {
        /* the brand entries of the menu are optional */
      }
    }
    return { session, extensions, brands, error: null };
  } catch (e) {
    // 401 means "not signed in"; a pending second factor (403 mfa_required)
    // is handled by the sign-in page; anything else is a real error.
    const signedOut = e instanceof ApiError && (e.status === 401 || e.code === "mfa_required");
    return { session: null, extensions: [], brands: [], error: signedOut ? null : e };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [extensions, setExtensions] = useState<UiExtension[]>([]);
  const [brands, setBrands] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const apply = useCallback((r: Loaded) => {
    setSession(r.session);
    setExtensions(r.extensions);
    setBrands(r.brands);
    setError(r.error);
    setLoading(false);
  }, []);

  const refresh = useCallback(async () => apply(await loadSession()), [apply]);

  useEffect(() => {
    let cancelled = false;
    loadSession().then((r) => {
      if (!cancelled) apply(r);
    });
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const value = useMemo<SessionState>(() => {
    const perms = new Set(session?.permissions ?? []);
    return {
      session,
      extensions,
      brands,
      loading,
      error,
      refresh,
      can: (p: string) => Boolean(session?.is_platform_admin || perms.has(p) || perms.has("*")),
    };
  }, [session, extensions, brands, loading, error, refresh]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
