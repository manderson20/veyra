// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Icon } from "../ui";
import { formatRelative } from "@/lib/format";
import type { DeployMode } from "@/lib/types";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useSession } from "@/hooks/useSession";

/**
 * Top-bar deploy control (the equivalent of "Apply Config" elsewhere): shown
 * while a change waits to be deployed. The drop-down picks between deploying
 * now and waiting until no call is active.
 */
export function ApplyChanges() {
  const { can } = useSession();
  const { engine, apply, applying } = useEngineStatus();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!engine) return null;
  if (engine.pending_revision !== null) {
    const waiting = engine.pending_mode === "when_idle" && (engine.pending_active_calls ?? 0) > 0;
    return (
      <Badge tone={waiting ? "warn" : "accent"} icon={waiting ? "clock" : "upload"}>
        {waiting
          ? `Waiting for ${engine.pending_active_calls} call${engine.pending_active_calls === 1 ? "" : "s"} to end (revision #${engine.pending_revision})`
          : `Deploying #${engine.pending_revision}`}
      </Badge>
    );
  }
  if (applying) return <Badge tone="accent" icon="upload">Deploying…</Badge>;
  if (!engine.changes_pending) return null;
  if (!can("config.deploy")) {
    return <Badge tone="warn" icon="alert">Changes pending deployment</Badge>;
  }
  const blocked = engine.state !== "running";
  const calls = engine.active_calls ?? 0;
  const go = (mode: DeployMode) => { setOpen(false); void apply(mode); };
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="deploy-split menu" ref={ref}>
        <Button variant="danger" icon="upload" className="topbar__deploy" onClick={() => go("now")} disabled={blocked}
          title={blocked ? "The telephony engine is not running." : engine.pending_by ? `Changes saved by ${engine.pending_by} ${formatRelative(engine.pending_since)} are waiting to be deployed` : "Generate a configuration revision and deploy it to the telephony engine"}>
          Deploy changes
        </Button>
        <Button variant="danger" className="topbar__deploy deploy-split__caret" aria-haspopup="menu" aria-expanded={open} aria-label="Deployment options" disabled={blocked} onClick={() => setOpen((o) => !o)}>
          <Icon name="chevronDown" size={14} />
        </Button>
        {open ? (
          <div className="menu__list" role="menu" aria-label="Deployment options">
            <button type="button" role="menuitem" className="menu__item" onClick={() => go("now")}>
              <Icon name="upload" size={16} />
              <span><span style={{ display: "block" }}>Deploy now</span><span className="subtle">Reloads only the affected modules. Calls in progress are not interrupted.</span></span>
            </button>
            <button type="button" role="menuitem" className="menu__item" onClick={() => go("when_idle")}>
              <Icon name="clock" size={16} />
              <span><span style={{ display: "block" }}>Deploy when no calls are active</span><span className="subtle">{calls ? `${calls} call${calls === 1 ? "" : "s"} up now. ` : ""}Waits up to the idle timeout, then deploys anyway. Suggested for SIP transport changes.</span></span>
            </button>
          </div>
        ) : null}
      </span>
      <Link href="/system/telephony/" className="subtle nowrap" title="Review the pending changes before deploying">Review</Link>
    </span>
  );
}
