// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Callout } from "@/components/ui";
import type { HaStatus } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

/** "Standby node: manage the system at <service>" (docs/HIGH_AVAILABILITY.md §9). */
export function StandbyBanner() {
  const { can, session } = useSession();
  const status = useApiData<HaStatus>(session?.is_platform_admin && can("ha.read") ? "/ha/status" : null);
  const s = status.data;
  if (!s?.ha_enabled || s.local.role !== "secondary") return null;
  const target = s.service.name || s.peer?.node_name || "";
  return (
    <div style={{ padding: "0 var(--space-6)", paddingTop: "var(--space-4)", maxWidth: "var(--content-max)", margin: "0 auto", width: "100%" }}>
      <Callout tone="warn" title="Standby node">
        This node is the standby; it answers read-only. Manage the system at <a href={`https://${target}/`}>{target}</a>. Use System → High availability here to fail over when the primary is down.
      </Callout>
    </div>
  );
}
