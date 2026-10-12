// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Badge, Button, DataTable, EmptyState, type Column } from "@/components/ui";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { UserSession } from "@/lib/types";
import { describeUserAgent } from "@/lib/useragent";

/** Active sessions, for the account page (own) and the user page (admin). */
export function SessionsTable({
  rows,
  loading,
  error,
  onRetry,
  onRevoke,
  revoking,
}: {
  rows: UserSession[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  /** Present when the viewer may sign out individual sessions. */
  onRevoke?: (s: UserSession) => void;
  revoking?: string | null;
}) {
  const columns: Column<UserSession>[] = [
    {
      key: "device",
      header: "Device",
      render: (s) => (
        <span>
          <span className="table__primary row" style={{ gap: 8 }}>
            {describeUserAgent(s.user_agent).label}
            {s.is_current ? <Badge tone="ok">This session</Badge> : null}
          </span>
          <span className="table__secondary mono" title={s.user_agent ?? undefined}>{s.ip_address ?? "unknown address"}</span>
        </span>
      ),
    },
    { key: "since", header: "Signed in", render: (s) => <span className="subtle nowrap" title={formatDateTime(s.created_at)}>{formatRelative(s.created_at)}</span> },
    { key: "seen", header: "Last active", render: (s) => <span className="subtle nowrap" title={formatDateTime(s.last_seen_at)}>{formatRelative(s.last_seen_at)}</span> },
    { key: "expires", header: "Expires", render: (s) => <span className="subtle nowrap">{formatDateTime(s.expires_at)}</span> },
  ];
  if (onRevoke) {
    columns.push({
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      width: "120px",
      render: (s) =>
        s.is_current ? null : (
          <Button size="sm" icon="logout" loading={revoking === s.id} onClick={() => onRevoke(s)}>
            Sign out
          </Button>
        ),
    });
  }
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(s) => s.id}
      loading={loading}
      error={error}
      onRetry={onRetry}
      caption="Active sessions"
      empty={<EmptyState compact icon="monitor" title="No active sessions">The user is not signed in anywhere.</EmptyState>}
    />
  );
}
