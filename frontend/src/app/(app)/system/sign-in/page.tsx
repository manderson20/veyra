// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { ProviderDialog } from "@/components/integrations/ProviderDialog";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, EmptyState, LinkButton, PageHeader, Switch, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { IdentityProviderOut } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

function PolicyCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const policy = useApiData<{ require_sso: boolean }>("/identity-providers/policy");
  const [busy, setBusy] = useState(false);
  const toggle = async (value: boolean) => {
    setBusy(true);
    try {
      await api.put("/identity-providers/policy", { require_sso: value });
      toast.success(value ? "Single sign-on required" : "Passwords allowed again", value ? "Linked accounts now sign in with their provider only." : "");
      policy.reload();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Policy">
      <Switch label="Require single sign-on" disabled={!editable || busy || !policy.data}
        description="Accounts linked to a provider can no longer use a password, and no password reset links are issued for them. The recovery administrator always signs in with a password."
        checked={policy.data?.require_sso ?? false} onChange={(e) => void toggle(e.target.checked)} />
    </Card>
  );
}

export default function SignInPage() {
  const { can } = useSession();
  const toast = useToast();
  const router = useRouter();
  const editable = can("sso.write");
  const list = useApiData<IdentityProviderOut[]>("/identity-providers");
  const [editing, setEditing] = useState<IdentityProviderOut | undefined>();
  const [deleting, setDeleting] = useState<IdentityProviderOut | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/identity-providers/${deleting.id}`);
      toast.success(`"${deleting.name}" removed`, "Its linked accounts keep working with a password if they have one.");
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const columns: Column<IdentityProviderOut>[] = [
    { key: "name", header: "Provider", render: (p) => <span><span className="table__primary" style={{ display: "block" }}>{p.name}</span><span className="table__secondary">{p.allowed_domains.join(", ")}</span></span> },
    { key: "redirect", header: "Redirect address", render: (p) => <span className="row" style={{ gap: 6 }}><span className="mono subtle" style={{ wordBreak: "break-all" }}>{p.redirect_uri}</span><CopyButton text={p.redirect_uri} /></span> },
    { key: "accounts", header: "Accounts", render: (p) => <span>{p.linked_users} linked<span className="table__secondary" style={{ display: "block" }}>{p.create_accounts ? "New ones created" : "Existing only"}</span></span> },
    { key: "status", header: "Status", render: (p) => !p.enabled ? <Badge tone="neutral">Disabled</Badge> : p.metadata_fetched_at ? <Badge tone="ok">Checked {formatRelative(p.metadata_fetched_at)}</Badge> : <Badge tone="warn">Not checked</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (p: IdentityProviderOut) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" icon="key" onClick={(e) => { e.stopPropagation(); router.push(`/system/sign-in/setup/?provider=${p.id}`); }}>Test</Button><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(p); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" aria-label={`Remove ${p.name}`} onClick={(e) => { e.stopPropagation(); setDeleting(p); }} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Sign-in" description="Single sign-on through Google Workspace, Microsoft Entra ID or another OpenID Connect provider, for the web interface and the Companion extension."
        actions={editable ? <LinkButton variant="primary" icon="plus" href="/system/sign-in/setup/">Set up a provider</LinkButton> : null} />
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Sign-in providers"
          onRowClick={editable ? (p) => setEditing(p) : undefined} rowLabel={(p) => `Edit ${p.name}`}
          empty={<EmptyState icon="key" title="Passwords only">{editable ? <>Let people sign in with the Google Workspace or Microsoft account they already have. <strong>Set up a provider</strong> walks you through it, with a test sign-in before anyone sees the button.</> : null}</EmptyState>} />
      </Card>
      {list.data?.length ? <Callout tone="info">People who already have a Veyra account are linked to their provider account the first time they use the button. The recovery administrator never signs in through a provider.</Callout> : null}
      <PolicyCard editable={editable} />
      <ProviderDialog open={!!editing} provider={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <ConfirmDialog open={!!deleting} title={`Remove "${deleting?.name ?? ""}"?`} confirmLabel="Remove" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Its sign-in button disappears and the links to its accounts are removed. Accounts created through it have no password; give them a reset link if they still need access.</p>
      </ConfirmDialog>
    </div>
  );
}
