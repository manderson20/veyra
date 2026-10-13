// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Card, ConfirmDialog, DataTable, EmptyState, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { ApiToken } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/**
 * Bearer tokens issued to the Veyra Companion browser extension (docs/COMPANION.md §3).
 * Own tokens on the account page (`/auth/tokens`); an administrator's view of another
 * user's tokens uses `/users/{id}/tokens` through the `path` props.
 */
export function ConnectedAppsCard({
  listPath = "/auth/tokens",
  revokeAllPath = "/auth/tokens/revoke-all",
  revokeOne = true,
  title = "Connected apps",
}: {
  listPath?: string;
  revokeAllPath?: string;
  revokeOne?: boolean;
  title?: string;
}) {
  const toast = useToast();
  const tokens = useApiData<ApiToken[]>(listPath);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const count = tokens.data?.length ?? 0;

  const revoke = async (t: ApiToken) => {
    setRevoking(t.id);
    try {
      await api.del(`/auth/tokens/${t.id}`);
      toast.success("Access revoked", `${t.label} is signed out.`);
      tokens.reload();
    } catch (err) {
      toast.error("Could not revoke", errorMessage(err));
    } finally {
      setRevoking(null);
    }
  };

  const revokeAll = async () => {
    setBusy(true);
    setError(null);
    try {
      if (revokeAllPath.startsWith("/users/")) {
        await api.del<{ message: string }>(revokeAllPath);
      } else {
        await api.post<{ revoked: number }>(revokeAllPath);
      }
      toast.success("All connected apps signed out");
      setConfirmAll(false);
      tokens.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<ApiToken>[] = [
    {
      key: "label",
      header: "App",
      render: (t) => (
        <span>
          <span className="table__primary row" style={{ gap: 8 }}>
            {t.label}
            {t.is_current ? <Badge tone="ok">This app</Badge> : null}
          </span>
          <span className="table__secondary">{t.kind === "companion" ? "Veyra Companion" : t.kind}</span>
        </span>
      ),
    },
    { key: "created", header: "Signed in", render: (t) => <span className="subtle nowrap" title={formatDateTime(t.created_at)}>{formatRelative(t.created_at)}</span> },
    {
      key: "used",
      header: "Last used",
      render: (t) => (
        <span>
          <span className="nowrap" title={formatDateTime(t.last_used_at)}>{t.last_used_at ? formatRelative(t.last_used_at) : "not yet"}</span>
          <span className="table__secondary mono">{t.last_used_ip ?? t.created_ip ?? ""}</span>
        </span>
      ),
    },
    { key: "expires", header: "Expires", render: (t) => <span className="subtle nowrap" title={formatDateTime(t.expires_at)}>{formatRelative(t.expires_at)}</span> },
    ...(revokeOne
      ? [
          {
            key: "actions",
            header: "",
            render: (t: ApiToken) => (
              <Button variant="ghost" size="sm" onClick={() => void revoke(t)} disabled={revoking === t.id}>
                {revoking === t.id ? "Revoking…" : "Revoke"}
              </Button>
            ),
          } satisfies Column<ApiToken>,
        ]
      : []),
  ];

  return (
    <Card
      title={title}
      subtitle="Browser extensions signed in with this account. A token stops working 30 days after its last use."
      actions={
        count > 0 ? (
          <Button variant="secondary" size="sm" onClick={() => setConfirmAll(true)}>
            Revoke all
          </Button>
        ) : null
      }
    >
      <DataTable
        columns={columns}
        rowKey={(t) => t.id}
        rows={tokens.data ?? []}
        loading={tokens.loading}
        error={tokens.error}
        onRetry={tokens.reload}
        empty={<EmptyState title="No connected apps">Install the Veyra Companion browser extension and sign in to see it here.</EmptyState>}
      />
      <ConfirmDialog
        open={confirmAll}
        title="Revoke all connected apps?"
        confirmLabel="Revoke all"
        tone="danger"
        busy={busy}
        error={error}
        onConfirm={() => void revokeAll()}
        onCancel={() => setConfirmAll(false)}
      >
        <p>Every Veyra Companion sign-in for this account will stop working and will have to sign in again.</p>
      </ConfirmDialog>
    </Card>
  );
}
