// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";
import { resolveTab, withTab } from "@/lib/tabs";

const LEAVE_PROMPT = "This tab has unsaved changes. Switch tabs and lose them?";

/**
 * The active tab of an object page, kept in the `tab` query parameter so a
 * link lands on the right tab (issue #81). While `dirty` is true a tab switch
 * asks first and leaving the page warns (the browser's own dialog).
 */
export function useUrlTab(ids: readonly string[], fallback: string, dirty = false): [string, (next: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = resolveTab(params.get("tab"), ids, fallback);
  const search = params.toString();
  const setTab = useCallback(
    (next: string) => {
      if (next === tab) return;
      if (dirty && !window.confirm(LEAVE_PROMPT)) return;
      const query = withTab(search, next, fallback);
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [tab, dirty, search, fallback, pathname, router],
  );
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return [tab, setTab];
}
