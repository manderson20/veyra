// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { clock, DIRECTION, OUTCOME, party } from "@/components/calls/format";
import { Badge, Card, Icon } from "@/components/ui";
import { formatRelative } from "@/lib/format";
import type { CallHistoryItem, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The caller's own recent calls (account page; docs/REPORTING.md §3.5). */
export function MyCallsCard() {
  const calls = useApiData<Page<CallHistoryItem>>("/me/calls", { limit: 10 });
  if (calls.error || !calls.data || calls.data.total === 0) return null;
  return (
    <Card title="Recent calls" subtitle="Calls to and from your phones in the last 30 days.">
      <ul className="list-plain">
        {calls.data.items.map((c) => {
          return (
            <li key={c.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
              <span className="row" style={{ gap: 8, minWidth: 0 }}>
                <Icon name={DIRECTION[c.direction].icon} label={DIRECTION[c.direction].label} size={16} />
                <span style={{ minWidth: 0 }}>
                  {party(c.from_number, c.from_name, c.from_extension)} <span className="subtle">→</span> {party(c.to_number, null, c.to_extension)}
                  <span className="table__secondary" style={{ display: "block" }}>{formatRelative(c.started_at)}{c.talk_seconds ? ` · ${clock(c.talk_seconds)}` : ""}</span>
                </span>
              </span>
              <Badge tone={OUTCOME[c.outcome].tone}>{OUTCOME[c.outcome].label}</Badge>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
