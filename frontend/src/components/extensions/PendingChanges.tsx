// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { Callout } from "@/components/ui";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

/**
 * Tells administrators when the database differs from the deployed engine
 * configuration (and when the installation key is missing). Reads the shared
 * engine status; `refreshKey` asks for a fresh read after a local change.
 */
export function PendingChanges({ refreshKey }: { refreshKey?: unknown }) {
  const { can } = useSession();
  const { engine, reload } = useEngineStatus();
  useOnChange(refreshKey, () => reload());
  if (!engine) return null;
  return (
    <>
      {!engine.installation_key_present ? (
        <Callout tone="danger" title="Installation key missing">
          SIP secrets cannot be stored or shown until the installation key exists. On the server run <span className="mono">sudo veyra installation-key check</span>.
        </Callout>
      ) : null}
      {engine.changes_pending ? (
        <Callout tone="info" title="Changes not yet deployed">
          Extensions have changed since the last deployment. Phones will not see the change until the configuration is applied
          {can("config.deploy") ? <>: use <strong>Deploy changes</strong> in the top bar, or review first under <Link href="/system/telephony/">System → Telephony Engine</Link>.</> : " by a platform administrator."}
        </Callout>
      ) : null}
    </>
  );
}
