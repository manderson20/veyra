// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { Badge, Button } from "../ui";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useSession } from "@/hooks/useSession";

/**
 * Top-bar "apply" control (the equivalent of FreePBX's Apply Config): shown
 * only while the database differs from the deployed engine configuration.
 */
export function ApplyChanges() {
  const { can } = useSession();
  const { engine, apply, applying } = useEngineStatus();
  if (!engine) return null;
  if (engine.pending_revision !== null || applying) {
    return <Badge tone="accent" icon="upload">{applying ? "Deploying…" : `Deploying #${engine.pending_revision}`}</Badge>;
  }
  if (!engine.changes_pending) return null;
  if (!can("config.deploy")) {
    return <Badge tone="warn" icon="alert">Changes pending deployment</Badge>;
  }
  const blocked = engine.state !== "running";
  return (
    <span className="row" style={{ gap: 8 }}>
      <Button variant="danger" icon="upload" className="topbar__deploy" onClick={() => void apply()} disabled={blocked}
        title={blocked ? "The telephony engine is not running." : engine.pending_by ? `Changes saved by ${engine.pending_by} are waiting to be deployed` : "Generate a configuration revision and deploy it to the telephony engine"}>
        Deploy changes
      </Button>
      <Link href="/system/telephony/" className="subtle nowrap" title="Review the pending changes before deploying">Review</Link>
    </span>
  );
}
