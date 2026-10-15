// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button, Card, ConfirmDialog, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { UserIdentityOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The sign-in provider accounts linked to a user (docs/INTEGRATIONS.md §1.3). */
export function UserIdentitiesCard({ userId, editable }: { userId: string; editable: boolean }) {
  const toast = useToast();
  const list = useApiData<UserIdentityOut[]>(`/users/${userId}/identities`);
  const [unlinking, setUnlinking] = useState<UserIdentityOut | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!list.data?.length) return null;

  const unlink = async () => {
    if (!unlinking) return;
    setBusy(true);
    setError(null);
    try {
      await api.del(`/users/${userId}/identities/${unlinking.id}`);
      toast.success("Unlinked", `The next sign-in with ${unlinking.provider_name} links the account again if the address matches.`);
      setUnlinking(undefined);
      list.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Sign-in" subtitle="Accounts at sign-in providers linked to this user.">
      <ul className="list-plain">
        {list.data.map((i) => (
          <li key={i.id} className="list-row">
            <span>
              <strong>{i.provider_name}</strong> <span className="mono">{i.email}</span>
              <span className="subtle" style={{ display: "block" }}>Linked {formatRelative(i.created_at)}{i.last_used_at ? `, last used ${formatRelative(i.last_used_at)}` : ""}</span>
            </span>
            {editable ? <Button size="sm" variant="ghost" onClick={() => setUnlinking(i)}>Unlink</Button> : null}
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!unlinking} title={`Unlink ${unlinking?.provider_name ?? ""}?`} confirmLabel="Unlink" busy={busy} error={error}
        onConfirm={unlink} onCancel={() => { setUnlinking(undefined); setError(null); }}>
        <p>Use this after a change of provider or address. Sessions already open stay open; sign them out separately if needed.</p>
      </ConfirmDialog>
    </Card>
  );
}
