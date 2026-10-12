"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  PageHeader,
  Pagination,
  SearchInput,
  SelectField,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api } from "@/lib/api";
import { formatRelative, initials } from "@/lib/format";
import type { Page, User } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const LIMIT = 25;

export default function UsersPage() {
  const router = useRouter();
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<User>>("/users", { q: debounced, limit: LIMIT, offset });
  const columns: Column<User>[] = [
    {
      key: "name",
      header: "Name",
      render: (u) => (
        <span className="row" style={{ flexWrap: "nowrap" }}>
          <span className="avatar" aria-hidden="true">{initials(u.display_name)}</span>
          <span>
            <span className="table__primary" style={{ display: "block" }}>{u.display_name}</span>
            <span className="table__secondary">{u.email}</span>
          </span>
        </span>
      ),
    },
    { key: "source", header: "Sign-in", render: (u) => (u.auth_source === "local" ? "Local password" : u.auth_source) },
    {
      key: "status",
      header: "Status",
      render: (u) => (
        <span className="row">
          <Badge tone={u.is_active ? "ok" : "neutral"}>{u.is_active ? "Active" : "Disabled"}</Badge>
          {u.is_recovery_admin ? <Badge tone="info" icon="shield">Recovery admin</Badge> : null}
        </span>
      ),
    },
    { key: "login", header: "Last sign-in", render: (u) => <span className="subtle nowrap">{formatRelative(u.last_login_at)}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Users"
        description="People who can sign in to Veyra and the roles they hold."
        actions={can("users.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New user</Button> : null}
      />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or email" label="Search users" />
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(u) => u.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Users"
          onRowClick={(u) => router.push(`/users/view/?id=${u.id}`)}
          rowLabel={(u) => `Open ${u.display_name}`}
          empty={<EmptyState icon="users" title={debounced ? "No matching users" : "No users yet"} />}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateUserDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(u) => router.push(`/users/view/?id=${u.id}`)} />
    </div>
  );
}

function CreateUserDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (u: User) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setEmail("");
      setName("");
      setPassword("");
      setOrg(session?.user.home_organization_id ?? "");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const user = await api.post<User>("/users", {
        email: email.trim(),
        display_name: name.trim(),
        password,
        home_organization_id: org || null,
      });
      toast.success("User created", "Assign a role so they can use Veyra.");
      onClose();
      onCreated(user);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="New user"
      description="Create a local account. Single sign-on arrives in a later release."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="user-create" loading={busy}>Create user</Button></>}
    >
      <form id="user-create" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Full name" required autoFocus value={name} error={errors.fields.display_name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Email address" type="email" required value={email} error={errors.fields.email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Initial password" type="password" required autoComplete="new-password" help="At least 12 characters. Share it securely; the user can change it after signing in."
          value={password} error={errors.fields.password} onChange={(e) => setPassword(e.target.value)} />
        <SelectField label="Organization" value={org} error={errors.fields.home_organization_id}
          placeholder={session?.is_platform_admin ? "None (platform-level account)" : "Choose an organization"}
          options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
