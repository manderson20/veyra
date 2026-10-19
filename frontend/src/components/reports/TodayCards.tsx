// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Card } from "@/components/ui";
import { formatRelative } from "@/lib/format";
import type { AlertItem, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

interface Totals {
  totals: { calls: number; answered: number; missed: number; voicemail: number; inbound: number };
  by_day: { inbound: number; outbound: number; internal: number }[];
}

/** "Calls today" and "Alerts" items of the dashboard (docs/REPORTING.md §5.2). */
export function TodayCards() {
  const { can } = useSession();
  // Today so far, and the same weekday last week up to the same time of day.
  const [period] = useState(() => {
    const now = new Date();
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    const week = 7 * 24 * 3600 * 1000;
    return {
      since: start.toISOString(),
      lastFrom: new Date(start.getTime() - week).toISOString(),
      lastTo: new Date(now.getTime() - week).toISOString(),
      weekday: start.toLocaleDateString(undefined, { weekday: "long" }),
    };
  });
  const today = useApiData<Totals>(can("reports.read") ? "/reports/calls" : null, { from: period.since });
  const lastWeek = useApiData<Totals>(can("reports.read") ? "/reports/calls" : null, { from: period.lastFrom, to: period.lastTo });
  const alerts = useApiData<Page<AlertItem>>(can("alerts.read") ? "/alerts" : null, { state: "open", limit: 5 });
  if (!can("reports.read") && !can("alerts.read")) return null;
  const t = today.data?.totals;
  const last = lastWeek.data?.totals;
  const dirs = today.data?.by_day.reduce((acc, d) => ({ inbound: acc.inbound + d.inbound, outbound: acc.outbound + d.outbound, internal: acc.internal + d.internal }), { inbound: 0, outbound: 0, internal: 0 });
  return (
    <div className="grid grid--2">
      {can("reports.read") ? (
        <Card title="Calls today" actions={<Link href="/reports/" className="subtle">Reports</Link>}>
          {t ? (
            <dl className="dl">
              <dt>Calls</dt><dd><strong>{t.calls}</strong> · {t.answered} answered</dd>
              {last ? <><dt>Last {period.weekday}</dt><dd><Trend now={t.calls} before={last.calls} /> <span className="subtle">{last.calls} by this time</span></dd></> : null}
              <dt>Missed</dt><dd>{t.missed}{t.voicemail ? ` · ${t.voicemail} to voicemail` : ""}</dd>
              <dt>Directions</dt><dd>{dirs ? `${dirs.inbound} inbound · ${dirs.outbound} outbound · ${dirs.internal} internal` : "—"}</dd>
            </dl>
          ) : <p className="subtle">{today.error ? "Could not load" : "Loading…"}</p>}
        </Card>
      ) : null}
      {can("alerts.read") ? (
        <Card title="Alerts" actions={<Link href="/system/alerts/" className="subtle">All alerts</Link>}>
          {!alerts.data ? <p className="subtle">{alerts.error ? "Could not load" : "Loading…"}</p> : alerts.data.total === 0 ? (
            <p style={{ margin: 0 }}><Badge tone="ok" icon="check">Nothing is wrong</Badge></p>
          ) : (
            <ul className="list-plain">
              {alerts.data.items.map((a) => (
                <li key={a.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
                  <span><Badge tone="danger" icon="alert">{a.title}</Badge> <span className="subtle">{a.message}</span></span>
                  <span className="subtle nowrap">{formatRelative(a.raised_at ?? a.first_seen_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : null}
    </div>
  );
}

/** Up or down compared with the same time last week. */
function Trend({ now, before }: { now: number; before: number }) {
  if (before === 0) return now === 0 ? <span className="subtle">Same</span> : <Badge tone="neutral">New</Badge>;
  const pct = Math.round(((now - before) / before) * 100);
  if (pct === 0) return <span className="subtle">Same</span>;
  return <Badge tone={pct > 0 ? "accent" : "neutral"}>{pct > 0 ? "▲" : "▼"} {Math.abs(pct)}%</Badge>;
}
