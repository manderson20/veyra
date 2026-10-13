// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { VoicemailBoxDialog } from "@/components/voicemail/VoicemailBoxDialog";
import { Badge, Button, Card, ErrorState, LoadingState } from "@/components/ui";
import type { Extension, Page, VoicemailBox } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The voicemail box of one extension, on the extension page. */
export function VoicemailCard({ extension, editable, onChanged }: { extension: Extension; editable: boolean; onChanged: () => void }) {
  const boxes = useApiData<Page<VoicemailBox>>("/voicemail", { extension_id: extension.id, limit: 1 });
  const [open, setOpen] = useState(false);
  const box = boxes.data?.items[0];
  const saved = () => { boxes.reload(); onChanged(); };
  return (
    <Card title="Voicemail" subtitle="Where unanswered calls go, and how messages are delivered."
      actions={editable ? <Button icon={box ? "settings" : "plus"} onClick={() => setOpen(true)}>{box ? "Edit box" : "Create box"}</Button> : null}>
      {boxes.error ? <ErrorState compact error={boxes.error} onRetry={boxes.reload} />
        : !boxes.data ? <LoadingState />
        : !box ? <p className="muted">No voicemail box. Calls ring for 30 seconds and then end.</p> : (
          <dl className="dl">
            <dt>Status</dt><dd><Badge tone={box.is_enabled ? "ok" : "neutral"}>{box.is_enabled ? "Enabled" : "Disabled"}</Badge></dd>
            <dt>Rings for</dt><dd>{box.ring_seconds} seconds before voicemail answers</dd>
            <dt>Email</dt><dd>{box.email ? <>{box.email}{box.attach_audio ? " (with the recording)" : ""}{box.delete_after_email ? ", deleted from the box after sending" : ""}</> : <span className="subtle">Messages stay in the box</span>}{box.email && !box.email_delivery_enabled ? <span className="subtle" style={{ display: "block" }}>Email delivery is not configured yet.</span> : null}</dd>
            <dt>From the phone</dt><dd><span className="mono">*97</span> greeting and messages (PIN asked)</dd>
            {box.in_use_by ? <><dt>Used by</dt><dd>{box.in_use_by} inbound route{box.in_use_by === 1 ? "" : "s"} or IVR key{box.in_use_by === 1 ? "" : "s"}</dd></> : null}
          </dl>
        )}
      <VoicemailBoxDialog open={open} onClose={() => setOpen(false)} extension={box ? undefined : extension} box={box} onSaved={saved} />
    </Card>
  );
}
