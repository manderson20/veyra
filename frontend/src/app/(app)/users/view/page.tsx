// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { ConnectedAppsCard } from "@/components/account/ConnectedAppsCard";
import { SessionsTable } from "@/components/account/SessionsTable";
import { UserIdentitiesCard } from "@/components/integrations/UserIdentitiesCard";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  PageHeader,
  SelectField,
  Switch,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { PasswordResetLink, Role, RoleAssignment, User, UserSession } from "@/lib/types";
import { isLockedOut } from "@/lib/users";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

function UserView() {
  const id = useSearchParams().get("id");
  const { session, can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const user = useApiData<User>(id ? `/users/${encodeURIComponent(id)}` : null);
  const roles = useApiData<RoleAssignment[]>(id && can("roles.read") ? `/users/${encodeURIComponent(id)}/roles` : null);
  const [name, setName] = useState("");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [removing, setRemoving] = useState<RoleAssignment | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [unlockBusy, setUnlockBusy] = useState(false);
  const [mfaReset, setMfaReset] = useState(false);
  const [mfaBusy, setMfaBusy] = useState(false);
  const [mfaError, setMfaError] = useState<string | null>(null);

  useOnChange(user.data, (u) => {
    if (u) {
      setName(u.display_name);
      setActive(u.is_active);
    }
  });

  if (!id) return <ErrorState title="No user selected" error={{ message: "Open a user from the list." }} />;
  if (user.error) return <ErrorState title="Could not load user" error={user.error} onRetry={user.reload} />;
  if (!user.data) return <LoadingState />;
  const u = user.data;
  const editable = can("users.write");
  const isSelf = session?.user.id === u.id;
  const dirty = name !== u.display_name || active !== u.is_active;
  const locked = isLockedOut(u);

  const unlock = async () => {
    setUnlockBusy(true);
    try {
      const r = await api.post<{ message: string }>(`/users/${u.id}/unlock`);
      toast.success("Account unlocked", r.message);
      user.reload();
    } catch (err) {
      toast.error("Could not unlock the account", errorMessage(err));
    } finally {
      setUnlockBusy(false);
    }
  };

  const resetMfa = async () => {
    setMfaBusy(true);
    setMfaError(null);
    try {
      const r = await api.post<{ message: string }>(`/users/${u.id}/mfa/reset`);
      toast.success("Two-factor authentication reset", r.message);
      setMfaReset(false);
      user.reload();
    } catch (err) {
      setMfaError(errorMessage(err));
    } finally {
      setMfaBusy(false);
    }
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      user.setData(await api.patch<User>(`/users/${u.id}`, { display_name: name.trim(), is_active: active }));
      toast.success("User saved", active ? undefined : "The user's sessions have been signed out.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const removeRole = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await api.del(`/users/${u.id}/roles/${removing.id}`);
      toast.success("Role removed", removing.role_name);
      setRemoving(null);
      roles.reload();
    } catch (err) {
      setRemoveError(errorMessage(err));
    } finally {
      setRemoveBusy(false);
    }
  };

  const roleColumns: Column<RoleAssignment>[] = [
    { key: "role", header: "Role", render: (r) => <span className="table__primary">{r.role_name}</span> },
    {
      key: "scope",
      header: "Scope",
      render: (r) => (r.scope_type === "platform" ? <Badge tone="info">Entire platform</Badge> : <span>{r.organization_name ?? r.organization_id}{r.scope_type === "site" ? " (site)" : ""}</span>),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      width: "64px",
      render: (r) => (can("roles.write") ? <IconButton icon="trash" size="sm" label={`Remove ${r.role_name}`} onClick={() => setRemoving(r)} /> : null),
    },
  ];

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/users/", label: "Users" }}
        title={u.display_name}
        description={
          <span className="row">
            <span>{u.email}</span>
            <Badge tone={u.is_active ? "ok" : "neutral"}>{u.is_active ? "Active" : "Disabled"}</Badge>
            {u.is_recovery_admin ? <Badge tone="info" icon="shield">Recovery admin</Badge> : null}
            {locked ? <Badge tone="warn" icon="lock">Locked</Badge> : null}
            {u.must_change_password ? <Badge tone="outline" icon="key">Temporary password</Badge> : null}
          </span>
        }
        actions={editable && !isSelf ? <Button icon="key" onClick={() => setResetOpen(true)}>Reset password</Button> : null}
      />
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Profile">
          <form className="stack stack--sm" onSubmit={save}>
            <TextField label="Full name" required value={name} disabled={!editable} error={errors.fields.display_name} onChange={(e) => setName(e.target.value)} />
            <TextField label="Email address" value={u.email} disabled help="Email addresses cannot be changed yet." />
            <Switch label="Account enabled" description={isSelf ? "You cannot disable your own account." : "Disabling signs the user out everywhere."}
              checked={active} disabled={!editable || isSelf} onChange={(e) => setActive(e.target.checked)} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
        <Card title="Account">
          <dl className="dl">
            <dt>Sign-in method</dt><dd>{u.auth_source === "local" ? "Local password" : u.auth_source}</dd>
            <dt>Last sign-in</dt><dd>{formatRelative(u.last_login_at)}</dd>
            <dt>Password</dt>
            <dd>
              {u.must_change_password ? "Temporary; must be changed at next sign-in" : u.password_changed_at ? `Changed ${formatRelative(u.password_changed_at)}` : "Set at creation"}
            </dd>
            <dt>Two-factor</dt>
            <dd>
              <span className="row">
                <Badge tone={u.mfa_enabled ? "ok" : "neutral"}>{u.mfa_enabled ? "On" : "Off"}</Badge>
                {editable && !isSelf && u.mfa_enabled ? <Button size="sm" icon="refresh" onClick={() => setMfaReset(true)}>Reset</Button> : null}
              </span>
            </dd>
            <dt>Lockout</dt>
            <dd>
              {locked ? (
                <span className="row">
                  <span>Locked after repeated failed sign-ins until {formatDateTime(u.locked_until)}.</span>
                  {editable ? <Button size="sm" icon="lock" loading={unlockBusy} onClick={unlock}>Unlock now</Button> : null}
                </span>
              ) : "Not locked"}
            </dd>
            <dt>Created</dt><dd>{formatDateTime(u.created_at)}</dd>
            <dt>User ID</dt><dd className="mono">{u.id}</dd>
          </dl>
        </Card>
      </div>
      {can("roles.read") ? (
        <Card
          title="Roles"
          subtitle="Roles grant permissions across the platform or within an organization."
          flush
          actions={can("roles.write") ? <Button size="sm" icon="plus" onClick={() => setAssignOpen(true)}>Assign role</Button> : null}
        >
          <DataTable
            columns={roleColumns}
            rows={roles.data}
            rowKey={(r) => r.id}
            loading={roles.loading}
            error={roles.error}
            onRetry={roles.reload}
            caption="Role assignments"
            empty={<EmptyState compact icon="shield" title="No roles assigned">Without a role this user can sign in but cannot see or change anything.</EmptyState>}
          />
        </Card>
      ) : null}
      <UserIdentitiesCard userId={u.id} editable={editable} />
      {editable && !isSelf ? <UserSessionsCard user={u} /> : null}
      {editable && !isSelf ? (
        <ConnectedAppsCard listPath={`/users/${u.id}/tokens`} revokeAllPath={`/users/${u.id}/tokens`} revokeOne={false} title="Connected apps (Companion)" showDownload={false} />
      ) : null}
      <ResetPasswordDialog open={resetOpen} onClose={() => setResetOpen(false)} user={u} onChanged={user.reload} />
      <ConfirmDialog
        open={mfaReset}
        title="Reset two-factor authentication?"
        confirmLabel="Reset two-factor"
        tone="danger"
        busy={mfaBusy}
        error={mfaError}
        onConfirm={resetMfa}
        onCancel={() => { setMfaReset(false); setMfaError(null); }}
      >
        <p>{u.display_name}&apos;s authenticator devices and recovery codes are removed and they are signed out everywhere. Use this when they lost their phone. They set up a new authenticator at their next sign-in.</p>
      </ConfirmDialog>
      <AssignRoleDialog open={assignOpen} onClose={() => setAssignOpen(false)} userId={u.id} onAssigned={roles.reload} />
      <ConfirmDialog
        open={removing !== null}
        title="Remove role?"
        confirmLabel="Remove role"
        tone="danger"
        busy={removeBusy}
        error={removeError}
        onConfirm={removeRole}
        onCancel={() => { setRemoving(null); setRemoveError(null); }}
      >
        <p>{u.display_name} will lose the <strong>{removing?.role_name}</strong> role{removing?.organization_name ? ` in ${removing.organization_name}` : ""}.</p>
      </ConfirmDialog>
    </div>
  );
}

function ResetPasswordDialog({ open, onClose, user, onChanged }: { open: boolean; onClose: () => void; user: User; onChanged: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [mode, setMode] = useState<"link" | "password">("link");
  const [password, setPassword] = useState("");
  const [permanent, setPermanent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<PasswordResetLink | null>(null);
  const [copied, setCopied] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setMode("link");
      setPassword("");
      setPermanent(false);
      setLink(null);
      setCopied(false);
      errors.clear();
    }
  });

  const fullLink = link && typeof window !== "undefined" ? `${window.location.origin}${link.path}` : "";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (mode === "link") {
        setLink(await api.post<PasswordResetLink>(`/users/${user.id}/password-reset-link`));
        toast.success("Reset link created", "Give it to the user; it is shown only once.");
      } else {
        await api.patch(`/users/${user.id}`, { password, require_password_change: !permanent });
        toast.success("Password set", `${user.display_name} has been signed out of all sessions.`);
        onClose();
      }
      onChanged();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fullLink);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={`Reset password for ${user.display_name}`}
      description="Either way the user is signed out everywhere and any lockout is cleared."
      footer={link
        ? <Button variant="primary" onClick={onClose}>Done</Button>
        : <><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="pw-reset" loading={busy} disabled={mode === "password" && !password}>{mode === "link" ? "Create reset link" : "Set password"}</Button></>}>
      {link ? (
        <div className="stack stack--sm">
          <Callout tone="ok" title="Reset link ready">
            Valid until {formatDateTime(link.expires_at)} and usable once. Send it to {user.display_name} over a channel you trust; it is not stored and cannot be shown again.
          </Callout>
          <TextField label="Reset link" readOnly value={fullLink} onFocus={(e) => e.currentTarget.select()} spellCheck={false} />
          <div className="form-actions">
            <Button icon={copied ? "check" : "copy"} onClick={copy}>{copied ? "Copied" : "Copy link"}</Button>
          </div>
        </div>
      ) : (
        <form id="pw-reset" className="stack stack--sm" onSubmit={submit}>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field__label" style={{ marginBottom: 10 }}>How</legend>
            <div className="stack stack--sm">
              <label className="check">
                <input type="radio" name="reset-mode" checked={mode === "link"} onChange={() => setMode("link")} />
                <span className="check__text"><span>Create a one-time reset link</span><span className="subtle">The user chooses their own password. Recommended: you never see it.</span></span>
              </label>
              <label className="check">
                <input type="radio" name="reset-mode" checked={mode === "password"} onChange={() => setMode("password")} />
                <span className="check__text"><span>Set a password now</span><span className="subtle">Temporary by default: the user must change it at the next sign-in.</span></span>
              </label>
            </div>
          </fieldset>
          {mode === "password" ? (
            <>
              <TextField label="New password" type="password" required autoFocus autoComplete="new-password" help="At least 12 characters."
                value={password} error={errors.fields.password} onChange={(e) => setPassword(e.target.value)} />
              <Switch label="Permanent password" description="Do not require the user to change it at the next sign-in."
                checked={permanent} onChange={(e) => setPermanent(e.target.checked)} />
            </>
          ) : null}
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        </form>
      )}
    </Dialog>
  );
}

function UserSessionsCard({ user }: { user: User }) {
  const toast = useToast();
  const sessions = useApiData<UserSession[]>(`/users/${user.id}/sessions`);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const count = sessions.data?.length ?? 0;

  const revokeAll = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.del<{ message: string }>(`/users/${user.id}/sessions`);
      toast.success("Sessions signed out", r.message);
      setConfirm(false);
      sessions.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Active sessions" subtitle="Where this account is currently signed in." flush
      actions={<Button icon="logout" disabled={count === 0} onClick={() => setConfirm(true)}>Sign out everywhere</Button>}>
      <SessionsTable rows={sessions.data} loading={sessions.loading} error={sessions.error} onRetry={sessions.reload} />
      <ConfirmDialog open={confirm} title="Sign out everywhere?" confirmLabel="Sign out" tone="danger" busy={busy} error={error}
        onConfirm={revokeAll} onCancel={() => { setConfirm(false); setError(null); }}>
        <p>{user.display_name} will be signed out of {count} session{count === 1 ? "" : "s"} and must sign in again. The password is not changed.</p>
      </ConfirmDialog>
    </Card>
  );
}

function AssignRoleDialog({ open, onClose, userId, onAssigned }: { open: boolean; onClose: () => void; userId: string; onAssigned: () => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const roles = useApiData<Role[]>(open ? "/roles" : null);
  const { organizations } = useOrganizationOptions(open);
  const [roleKey, setRoleKey] = useState("");
  const [orgId, setOrgId] = useState("");
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setRoleKey("");
      setOrgId("");
      errors.clear();
    }
  });

  const platform = roleKey === "platform_admin";
  const available = (roles.data ?? []).filter((r) => r.key !== "platform_admin" || session?.is_platform_admin);
  const selected = available.find((r) => r.key === roleKey);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.post(`/users/${userId}/roles`, platform
        ? { role_key: roleKey, scope_type: "platform" }
        : { role_key: roleKey, scope_type: "organization", organization_id: orgId });
      toast.success("Role assigned", selected?.name);
      onClose();
      onAssigned();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Assign role"
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="role-assign" loading={busy} disabled={!roleKey || (!platform && !orgId)}>Assign role</Button></>}>
      <form id="role-assign" className="stack stack--sm" onSubmit={submit}>
        <SelectField label="Role" required value={roleKey} placeholder="Choose a role" options={available.map((r) => ({ value: r.key, label: r.name }))}
          help={selected?.description} onChange={(e) => setRoleKey(e.target.value)} />
        {platform ? (
          <Callout tone="warn" title="Platform-wide access">The Platform Administrator role grants full control of this installation and every organization on it.</Callout>
        ) : (
          <SelectField label="Organization" required value={orgId} placeholder="Choose an organization" options={organizations.map((o) => ({ value: o.id, label: o.name }))}
            onChange={(e) => setOrgId(e.target.value)} />
        )}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><UserView /></Suspense>;
}
