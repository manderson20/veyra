// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PRESENCE_TONE } from "@/components/portal/PresenceCard";
import { Badge, Button, Callout, Card, SearchInput, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { DirectoryEntry, MyExtension, OriginateResult, PresenceState } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const LABEL: Record<PresenceState, string> = { available: "Available", away: "Away", busy: "Busy", meeting: "In a meeting", lunch: "At lunch", out: "Out" };

/** Colleagues with presence, registration and call state (docs/USER_PORTAL.md §7), refreshed every 20 s. */
export function ColleaguesCard({ extensions }: { extensions: MyExtension[] }) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const dir = useApiData<{ results: DirectoryEntry[]; total: number }>("/directory", q.trim() ? { q: q.trim() } : undefined);
  const reload = dir.reload;
  useEffect(() => { const t = window.setInterval(reload, 20000); return () => window.clearInterval(t); }, [reload]);
  const [dialing, setDialing] = useState<string | null>(null);
  const mine = new Set(extensions.map((x) => x.number));
  const phone = extensions.find((x) => x.is_enabled) ?? extensions[0];
  const dial = async (number: string) => {
    if (!phone) return;
    setDialing(number);
    try {
      const r = await api.post<OriginateResult>("/calls/originate", { extension_id: phone.id, number });
      toast.success(`Ringing ${r.extension_number}`, `Pick up to call ${number}.`);
    } catch (err) {
      toast.error("Could not place the call", errorMessage(err));
    } finally {
      setDialing(null);
    }
  };
  const people = (dir.data?.results ?? []).filter((e) => e.type === "extension" && !mine.has(e.number));
  return (
    <Card title="Colleagues" subtitle="Who is available right now.">
      <div className="stack stack--sm">
        <SearchInput value={q} onChange={setQ} placeholder="Search by name or number" label="Search colleagues" />
        {dir.error ? <Callout tone="danger">{errorMessage(dir.error)}</Callout> : null}
        {dir.data && people.length === 0 ? <p className="subtle">Nobody matches.</p> : null}
        <ul className="list-plain">
          {people.map((e) => {
            const presence = (e.presence ?? "available") as PresenceState;
            return (
              <li key={e.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
                <span style={{ minWidth: 0 }}>
                  <span className="table__primary">
                    <span aria-hidden="true" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, marginRight: 8, background: e.on_call ? "var(--danger)" : e.registered === false ? "var(--border-strong)" : "var(--ok)" }} />
                    {e.user_display_name ?? e.name} <span className="subtle mono">{e.number}</span>
                  </span>
                  <span className="table__secondary" style={{ display: "block" }}>
                    <Badge tone={PRESENCE_TONE[presence]}>{LABEL[presence]}</Badge>{e.presence_message ? ` ${e.presence_message}` : ""}
                    {e.on_call ? " · on a call" : e.registered === false ? " · phone offline" : ""}
                  </span>
                </span>
                {phone ? <Button size="sm" icon="phone" loading={dialing === e.number} onClick={() => dial(e.number)}>Call</Button> : null}
              </li>
            );
          })}
        </ul>
      </div>
    </Card>
  );
}
