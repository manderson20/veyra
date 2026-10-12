// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { Callout } from "@/components/ui";
import type { EngineStatus } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

/**
 * Tells administrators when the database differs from the deployed engine
 * configuration (and when the installation key is missing). Hidden for
 * callers without config.read, who cannot deploy anyway.
 */
export function PendingChanges({ refreshKey }: { refreshKey?: unknown }) {
  const { can } = useSession();
  const engine = useApiData<EngineStatus>(can("config.read") ? "/telephony/engine" : null, { k: String(refreshKey ?? "") });
  const e = engine.data;
  if (!e) return null;
  return (
    <>
      {!e.installation_key_present ? (
        <Callout tone="danger" title="Installation key missing">
          SIP secrets cannot be stored or shown until the installation key exists. On the server run <span className="mono">sudo veyra installation-key check</span>.
        </Callout>
      ) : null}
      {e.changes_pending ? (
        <Callout tone="info" title="Changes not yet deployed">
          Extensions have changed since the last deployment. Phones will not see the change until a configuration revision is generated and deployed
          {can("config.deploy") ? <> under <Link href="/system/telephony/">System → Telephony Engine</Link>.</> : " by a platform administrator."}
        </Callout>
      ) : null}
    </>
  );
}
