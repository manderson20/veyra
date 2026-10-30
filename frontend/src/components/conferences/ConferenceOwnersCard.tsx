// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { MemberListEditor, membersFromIds, type MemberDraft } from "@/components/groups/MemberListEditor";
import { Button, Card, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";
import type { ConferenceRoom, Extension, Page } from "@/lib/types";

/** The extensions whose users control this room from My Phone (issue #96). */
export function ConferenceOwnersCard({ room, editable, onSaved }: { room: ConferenceRoom; editable: boolean; onSaved: (room: ConferenceRoom) => void }) {
  const toast = useToast();
  const extensions = useApiData<Page<Extension>>("/extensions", { organization_id: room.organization_id, limit: 200 });
  const fromRoom = () => membersFromIds(room.owners.map((extension_id) => ({ extension_id })));
  const [owners, setOwners] = useState<MemberDraft[]>(fromRoom);
  const [busy, setBusy] = useState(false);
  useOnChange(room.owners, () => setOwners(fromRoom()));
  const ids = owners.map((o) => o.extension_id);
  const dirty = JSON.stringify([...ids].sort()) !== JSON.stringify([...room.owners].sort());

  const save = async () => {
    setBusy(true);
    try {
      onSaved(await api.put<ConferenceRoom>(`/conferences/${room.id}/owners`, { extension_ids: ids }));
      toast.success("Owners saved", "This applies at once; no deployment is needed.");
    } catch (err) {
      toast.error("Not saved", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Room owners" subtitle="The users of these phones get this room's controls in the Conference widget on My Phone.">
      <MemberListEditor label="Owner phones" members={owners} extensions={extensions.data?.items ?? []} loading={extensions.loading} onChange={setOwners} disabled={!editable} emptyText="No owners: only administrators control this room." />
      {editable ? <div className="form-actions"><Button variant="primary" onClick={save} loading={busy} disabled={!dirty}>Save owners</Button></div> : null}
    </Card>
  );
}
