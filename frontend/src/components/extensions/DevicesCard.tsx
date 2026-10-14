// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { Badge, Card } from "@/components/ui";
import type { Device, Extension, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The phones that register this extension (line 1 or an extra line). */
export function DevicesCard({ extension }: { extension: Extension }) {
  const devices = useApiData<Page<Device>>("/devices", { extension_id: extension.id, limit: 50 });
  const items = devices.data?.items ?? [];
  return (
    <Card title="Phones" subtitle="Devices provisioned with this extension.">
      {items.length === 0 ? <p className="muted">No registered phone carries this extension. <Link href="/devices/">Register a phone</Link>.</p> : (
        <ul className="list-plain">
          {items.map((d) => (
            <li key={d.id} style={{ padding: "6px 0" }}>
              <Link href={`/devices/view/?id=${d.id}`}>{d.label ?? d.mac_display}</Link> <span className="subtle">{d.manufacturer} {d.model}</span>{" "}
              {d.extension?.id === extension.id ? <Badge tone="outline">Line 1</Badge> : <Badge tone="outline">Extra line</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
