// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { Card } from "@/components/ui";
import type { Extension, Membership } from "@/lib/types";

function List({ items, href }: { items: Membership[]; href: (m: Membership) => string }) {
  if (!items.length) return <span className="subtle">None</span>;
  return (
    <span className="row" style={{ gap: 6, flexWrap: "wrap" }}>
      {items.map((m) => (
        <Link key={m.id} href={href(m)} className="kv-chip">{m.number ? <><span className="mono">{m.number}</span> {m.name}</> : m.name}</Link>
      ))}
    </span>
  );
}

/** The ring groups, queues and pickup groups an extension belongs to (docs/RING_GROUPS_QUEUES.md). */
export function CallGroupsCard({ extension }: { extension: Extension }) {
  const x = extension;
  return (
    <Card title="Call groups" subtitle="Groups this phone rings in, queues it takes calls from, and whose calls it may pick up with *8.">
      <dl className="dl">
        <dt>Ring groups</dt><dd><List items={x.ring_groups} href={(m) => `/ring-groups/view/?id=${m.id}`} /></dd>
        <dt>Call queues</dt><dd><List items={x.queues} href={(m) => `/queues/view/?id=${m.id}`} /></dd>
        <dt>Pickup groups</dt><dd><List items={x.pickup_groups} href={() => "/pickup-groups/"} /></dd>
        <dt>From the phone</dt><dd><span className="mono">*8</span> picks up a ringing call in your pickup groups; <span className="mono">**</span>number picks up that phone</dd>
      </dl>
    </Card>
  );
}
