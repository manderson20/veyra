// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Checkbox, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApiData } from "@/hooks/useApiData";

interface WakeupCall {
  id: string;
  time: string;
  daily: boolean;
  next_at: string | null;
  last_result: string | null;
}

/** Wake-up calls of one extension (issue #392); `base` is the extension's API path. */
export function WakeupCard({ base, editable }: { base: string; editable: boolean }) {
  const toast = useToast();
  const calls = useApiData<WakeupCall[]>(`${base}/wakeup-calls`);
  const [time, setTime] = useState("");
  const [daily, setDaily] = useState(false);
  const [busy, setBusy] = useState(false);

  const change = async (act: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await act();
      calls.reload();
      return true;
    } catch (err) {
      toast.error("Could not change the wake-up calls", errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await change(() => api.post(`${base}/wakeup-calls`, { time, daily }))) { setTime(""); setDaily(false); }
  };

  return (
    <Card title="Wake-up calls" subtitle="The phone rings at this time and plays a message. Unanswered calls are tried three times, five minutes apart. Applies at once.">
      <div className="stack stack--sm">
        {calls.data?.length ? (
          <ul className="list-plain">
            {calls.data.map((c) => (
              <li key={c.id} className="list-row" style={{ padding: "var(--space-2) 0" }}>
                <span className="row" style={{ gap: 8 }}>
                  <span className="mono">{c.time}</span>
                  <span>{c.daily ? "Every day" : "Once"}</span>
                  {c.next_at ? <span className="subtle">next {formatDateTime(c.next_at)}</span> : null}
                  {c.last_result === "missed" ? <Badge tone="warn">Last one missed</Badge> : null}
                  {c.last_result === "skipped" ? <Badge tone="warn">Last one skipped</Badge> : null}
                </span>
                {editable ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void change(() => api.del(`${base}/wakeup-calls/${c.id}`))}>Delete</Button> : null}
              </li>
            ))}
          </ul>
        ) : <p className="subtle" style={{ margin: 0 }}>None set.</p>}
        {editable ? (
          <form className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={add}>
            <TextField label="Time" type="time" required value={time} onChange={(e) => setTime(e.target.value)} />
            <Checkbox label="Every day" checked={daily} onChange={(e) => setDaily(e.target.checked)} />
            <Button type="submit" loading={busy} disabled={!time}>Add</Button>
          </form>
        ) : null}
      </div>
    </Card>
  );
}
