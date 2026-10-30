// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { LiveConference } from "@/components/conferences/LiveConference";
import { Card } from "@/components/ui";
import { useApiData } from "@/hooks/useApiData";

/** The live view and controls of the conference rooms you own (issue #96). */
export function ConferenceCard() {
  const rooms = useApiData<{ id: string; name: string; number: string }[]>("/me/conferences");
  if (!rooms.data) return <Card title="Conference"><p className="subtle">Loading…</p></Card>;
  if (rooms.data.length === 0) return <Card title="Conference"><p className="subtle">You do not own a conference room. An administrator can make your phone an owner of one.</p></Card>;
  return (
    <div className="stack">
      {rooms.data.map((r) => <LiveConference key={r.id} roomId={r.id} editable base="/me/conferences" title={`${r.name} (${r.number})`} />)}
    </div>
  );
}
