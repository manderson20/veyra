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
  showDownload = true,
}: {
  listPath?: string;
  revokeAllPath?: string;
  revokeOne?: boolean;
  title?: string;
  /** The download and install steps (own account page only). */
  showDownload?: boolean;
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
      {showDownload ? (
        <details className="stack" style={{ marginTop: 16 }}>
          <summary className="row" style={{ gap: 8, cursor: "pointer" }}>
            <strong>Get the Veyra Companion extension</strong>
            <span className="subtle">for Chrome and Edge</span>
          </summary>
          <ol className="stack" style={{ marginTop: 12, paddingLeft: 20, gap: 6 }}>
            <li>
              <a href="/downloads/veyra-companion.zip" download>
                Download veyra-companion.zip
              </a>{" "}
              and unzip it into a folder you keep (the browser loads the extension from there).
            </li>
            <li>
              Open <span className="mono">chrome://extensions</span> (or <span className="mono">edge://extensions</span>), turn on <em>Developer mode</em> and choose <em>Load unpacked</em>, then pick the unzipped folder.
            </li>
            <li>
              Click the Veyra icon in the toolbar, enter this server&apos;s address (<span className="mono">{typeof window !== "undefined" ? window.location.origin : "https://…"}</span>), your email and password, then your authenticator code.
            </li>
          </ol>
          <p className="subtle">
            The browser must trust this server&apos;s certificate; with the installer&apos;s self-signed certificate, import it into the computer&apos;s trust store first. Each sign-in appears above as a connected app and can be revoked here.
          </p>
        </details>
      ) : null}
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
