// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Card, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { QueuePauseReason } from "@/lib/types";

/** The organization's pause reasons (issue #392); changes apply at once. */
export function PauseReasonsCard({ organizationId, reasons, editable, onChange }: { organizationId: string; reasons: QueuePauseReason[]; editable: boolean; onChange: () => void }) {
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);

  const change = async (act: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await act();
      onChange();
      return true;
    } catch (err) {
      toast.error("Could not change the pause reasons", errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (await change(() => api.post("/queues/pause-reasons", { organization_id: organizationId, label: label.trim() }))) setLabel("");
  };

  return (
    <Card title="Pause reasons" subtitle="For every queue in this organization. Agents dial *46** and the number; your feature codes may differ.">
      <div className="stack stack--sm">
        {reasons.length ? (
          <ul className="list-plain">
            {reasons.map((r) => (
              <li key={r.id} className="list-row" style={{ padding: "var(--space-2) 0" }}>
                <span className="row" style={{ gap: 8 }}><span className="mono">{r.code}</span><span>{r.label}</span></span>
                {editable ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => void change(() => api.del(`/queues/pause-reasons/${r.id}`))}>Delete</Button> : null}
              </li>
            ))}
          </ul>
        ) : <p className="subtle" style={{ margin: 0 }}>None yet. Agents can still pause without a reason.</p>}
        {editable ? (
          <form className="row" style={{ gap: 8, alignItems: "flex-end" }} onSubmit={add}>
            <TextField label="New reason" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} />
            <Button type="submit" loading={busy} disabled={!label.trim()}>Add</Button>
          </form>
        ) : null}
      </div>
    </Card>
  );
}
