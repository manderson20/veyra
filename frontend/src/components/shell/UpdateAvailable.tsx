// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "../ui";
import type { AvailableUpdate } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const DISMISS_KEY = "veyra.update-dismissed";

function dismissed(): string | null {
  try { return window.localStorage.getItem(DISMISS_KEY); } catch { return null; }
}

/**
 * Top-bar notice that a newer Veyra release is available (issue #89), like
 * the pending-deployment control: links to System → Updates; dismissed per
 * version in this browser.
 */
export function UpdateAvailable() {
  const { can } = useSession();
  const allowed = can("updates.read");
  const list = useApiData<AvailableUpdate[]>(allowed ? "/updates/available" : null);
  // Read once; the notice renders only after the list loads, so the server
  // render (no window) and the first client render agree.
  const [hidden, setHidden] = useState<string | null>(() => (typeof window === "undefined" ? null : dismissed()));
  const reload = list.reload;
  useEffect(() => {
    if (!allowed) return;
    const t = window.setInterval(reload, 5 * 60 * 1000);
    return () => window.clearInterval(t);
  }, [allowed, reload]);
  const newest = (list.data ?? []).find((u) => u.component === "veyra_core" && ["available", "downloaded", "approved", "installing"].includes(u.state));
  if (!newest || hidden === newest.version) return null;
  const installing = newest.state === "installing" || newest.state === "approved";
  const dismiss = () => {
    try { window.localStorage.setItem(DISMISS_KEY, newest.version); } catch { /* per-browser convenience only */ }
    setHidden(newest.version);
  };
  // One pill: the link and its hide button share the badge (owner's control-shape rule).
  return (
    <span className="badge badge--info update-notice">
      <Link href="/updates/" className="update-notice__link nowrap" title={installing ? "An installation is approved or running" : "Review the release notes and install it"}>
        <Icon name="update" size={14} /> {installing ? `Installing Veyra ${newest.version}` : `Veyra ${newest.version} is available`}
      </Link>
      {installing ? null : (
        <button type="button" className="update-notice__hide" aria-label={`Hide the notice for ${newest.version}`} title="Hide until the next release" onClick={dismiss}>
          <Icon name="x" size={12} />
        </button>
      )}
    </span>
  );
}
