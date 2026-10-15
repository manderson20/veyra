// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { ProviderDialog } from "@/components/integrations/ProviderDialog";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Switch, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { IdentityProviderOut, ProviderTestOut } from "@/lib/types";
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

function SetupSteps() {
  return (
    <Card title="Setting up Google Workspace">
      <ol className="stack" style={{ paddingLeft: 20, gap: 6 }}>
        <li>In the Google Cloud console, open <strong>APIs &amp; Services → Credentials</strong> for a project of your organization and create an <strong>OAuth client ID</strong> of type <em>Web application</em>.</li>
        <li>Under <strong>Authorized redirect URIs</strong>, add the redirect address shown in the <em>Add provider</em> dialog; it is the same for every provider.</li>
        <li>On the OAuth consent screen, choose <em>Internal</em> so only your Workspace accounts can use it.</li>
        <li>Copy the client ID and secret into Veyra, and list your e-mail domain.</li>
        <li>For the Companion to sign in without a click on managed Chromebooks, mark the client as <strong>Trusted</strong> in the Admin console (Security → API controls → App access control) and set <span className="mono">ssoProvider</span> in the extension&apos;s policy (Settings → Companion deployment).</li>
      </ol>
      <p className="subtle">Microsoft Entra ID works the same way: an app registration with a Web redirect URI and a client secret; enter the directory (tenant) ID.</p>
    </Card>
  );
}

export default function SignInPage() {
  const { can } = useSession();
  const toast = useToast();
  const editable = can("sso.write");
  const list = useApiData<IdentityProviderOut[]>("/identity-providers");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<IdentityProviderOut | undefined>();
  const [deleting, setDeleting] = useState<IdentityProviderOut | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const test = async (p: IdentityProviderOut) => {
    setTesting(p.id);
    try {
      const r = await api.post<ProviderTestOut>(`/identity-providers/${p.id}/test`);
      if (r.ok) toast.success(`${p.name} answers`, `${r.message} ${r.keys} signing key(s).`);
      else toast.error(`${p.name} is not reachable`, r.message);
      list.reload();
    } catch (err) {
      toast.error("Test failed", errorMessage(err));
    } finally {
      setTesting(null);
    }
  };
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
    { key: "status", header: "Status", render: (p) => !p.enabled ? <Badge tone="neutral">Disabled</Badge> : p.metadata_fetched_at ? <Badge tone="ok">Checked {formatRelative(p.metadata_fetched_at)}</Badge> : <Badge tone="warn">Not tested</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (p: IdentityProviderOut) => <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}><Button size="sm" icon="refresh" loading={testing === p.id} onClick={(e) => { e.stopPropagation(); void test(p); }}>Test</Button><Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(p); }}>Edit</Button><Button size="sm" variant="ghost" icon="trash" aria-label={`Remove ${p.name}`} onClick={(e) => { e.stopPropagation(); setDeleting(p); }} /></span> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader title="Sign-in" description="Single sign-on through Google Workspace, Microsoft Entra ID or another OpenID Connect provider, for the web interface and the Companion extension."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>Add provider</Button> : null} />
      <Card flush>
        <DataTable columns={columns} rows={list.data} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Sign-in providers"
          onRowClick={editable ? (p) => setEditing(p) : undefined} rowLabel={(p) => `Edit ${p.name}`}
          empty={<EmptyState icon="key" title="Passwords only">{editable ? "Add your Google Workspace or Microsoft tenant so people sign in with the account they already have." : null}</EmptyState>} />
      </Card>
      {list.data?.length ? <Callout tone="info">People who already have a Veyra account are linked to their provider account the first time they use the button. The recovery administrator never signs in through a provider.</Callout> : null}
      <PolicyCard editable={editable} />
      <SetupSteps />
      <ProviderDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => list.reload()} />
      <ProviderDialog open={!!editing} provider={editing} onClose={() => setEditing(undefined)} onSaved={() => list.reload()} />
      <ConfirmDialog open={!!deleting} title={`Remove "${deleting?.name ?? ""}"?`} confirmLabel="Remove" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Its sign-in button disappears and the links to its accounts are removed. Accounts created through it have no password; give them a reset link if they still need access.</p>
      </ConfirmDialog>
    </div>
  );
}
