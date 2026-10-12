"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
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
import type { Role, RoleAssignment, User } from "@/lib/types";
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
      <ResetPasswordDialog open={resetOpen} onClose={() => setResetOpen(false)} user={u} />
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

function ResetPasswordDialog({ open, onClose, user }: { open: boolean; onClose: () => void; user: User }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setPassword("");
      errors.clear();
    }
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.patch(`/users/${user.id}`, { password });
      toast.success("Password reset", `${user.display_name} has been signed out of all sessions.`);
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={`Reset password for ${user.display_name}`}
      description="The user is signed out everywhere and any account lockout is cleared."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="pw-reset" loading={busy}>Reset password</Button></>}>
      <form id="pw-reset" className="stack stack--sm" onSubmit={submit}>
        <TextField label="New password" type="password" required autoFocus autoComplete="new-password" help="At least 12 characters."
          value={password} error={errors.fields.password} onChange={(e) => setPassword(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
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
