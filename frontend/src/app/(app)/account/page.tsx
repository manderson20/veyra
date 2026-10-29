// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { NewPasswordFields, passwordsMatch } from "@/components/account/PasswordFields";
import { ConnectedAppsCard } from "@/components/account/ConnectedAppsCard";
import { MissedCallEmailCard } from "@/components/account/MissedCallEmailCard";
import { MyCallsCard } from "@/components/account/MyCallsCard";
import { MyVoicemailCard } from "@/components/account/MyVoicemailCard";
import { SessionsTable } from "@/components/account/SessionsTable";
import { TrustedBrowsersCard } from "@/components/account/TrustedBrowsersCard";
import { TwoFactorCard } from "@/components/account/TwoFactorCard";
import { Badge, Button, Callout, Card, ConfirmDialog, LoadingState, PageHeader, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { UserSession } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";

function AccountPage() {
  const { session, refresh } = useSession();
  const forced = session?.must_change_password ?? false;
  const reason = useSearchParams().get("reason");

  if (!session) return <LoadingState />;
  const u = session.user;
  return (
    <div className="stack">
      <PageHeader title="Your account" description="Your sign-in details, password, active sessions and connected apps." />
      {forced ? (
        <Callout tone="warn" title="Choose a new password to continue">
          {reason === "signin" ? "You signed in with a temporary password set by an administrator. " : "An administrator set a temporary password for this account. "}
          The rest of Veyra is unavailable until you choose your own password.
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Profile">
          <dl className="dl">
            <dt>Name</dt><dd>{u.display_name}</dd>
            <dt>Email address</dt><dd>{u.email}</dd>
            <dt>Sign-in method</dt><dd>{SIGN_IN_METHOD[u.auth_source] ?? u.auth_source}</dd>
            <dt>Access</dt>
            <dd className="row">
              {session.is_platform_admin ? <Badge tone="info" icon="shield">Platform Administrator</Badge> : <span>{session.permissions.length} permission{session.permissions.length === 1 ? "" : "s"}</span>}
              {u.is_recovery_admin ? <Badge tone="info">Recovery admin</Badge> : null}
            </dd>
            <dt>Two-factor</dt><dd><Badge tone={session.mfa.enabled ? "ok" : "neutral"}>{session.mfa.enabled ? "On" : "Off"}</Badge></dd>
            <dt>Password changed</dt><dd>{u.password_changed_at ? formatRelative(u.password_changed_at) : "unknown"}</dd>
            <dt>Last sign-in</dt><dd>{formatDateTime(u.last_login_at)}</dd>
          </dl>
          <p className="subtle" style={{ marginTop: 16 }}>Names and email addresses are changed by an administrator from the Users page.</p>
        </Card>
        {u.auth_source === "local" ? (
          <Card title="Change password" subtitle="Your other sessions are signed out when the password changes." id="password">
            <ChangePasswordForm onChanged={refresh} />
          </Card>
        ) : (
          <Card title="Password">
            <p className="muted" style={{ margin: 0 }}>You sign in with your {SIGN_IN_METHOD[u.auth_source] ?? "organization"} account, so there is no Veyra password to change. Change your password there.</p>
          </Card>
        )}
      </div>
      <TwoFactorCard />
      <TrustedBrowsersCard />
      <MyVoicemailCard />
      <MissedCallEmailCard />
      <MyCallsCard />
      <SessionsCard />
      <ConnectedAppsCard />
    </div>
  );
}

function ChangePasswordForm({ onChanged }: { onChanged: () => Promise<void> }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!passwordsMatch(next, confirm)) return;
    setBusy(true);
    errors.clear();
    try {
      const r = await api.post<{ message: string }>("/auth/password", { current_password: current, new_password: next });
      toast.success("Password changed", r.message);
      setCurrent("");
      setNext("");
      setConfirm("");
      await onChanged();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="stack stack--sm" onSubmit={submit}>
      <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      <NewPasswordFields value={next} confirm={confirm} onChange={setNext} onConfirmChange={setConfirm} error={errors.fields.new_password} />
      {errors.message && !errors.fields.new_password ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="form-actions">
        <Button variant="primary" type="submit" loading={busy} disabled={!current || !passwordsMatch(next, confirm)}>Change password</Button>
      </div>
    </form>
  );
}

function SessionsCard() {
  const toast = useToast();
  const sessions = useApiData<UserSession[]>("/auth/sessions");
  const [revoking, setRevoking] = useState<string | null>(null);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const others = (sessions.data ?? []).filter((s) => !s.is_current).length;

  const revoke = async (s: UserSession) => {
    setRevoking(s.id);
    try {
      await api.del(`/auth/sessions/${s.id}`);
      toast.success("Session signed out");
      sessions.reload();
    } catch (err) {
      toast.error("Could not sign out the session", errorMessage(err));
    } finally {
      setRevoking(null);
    }
  };

  const revokeOthers = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ message: string }>("/auth/sessions/revoke-others");
      toast.success("Other sessions signed out", r.message);
      setConfirmOthers(false);
      sessions.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="Active sessions"
      subtitle="Everywhere this account is signed in. A session ends after a set time, and sooner when it is not used."
      flush
      actions={<Button icon="logout" disabled={others === 0} onClick={() => setConfirmOthers(true)}>Sign out other sessions</Button>}
    >
      <SessionsTable rows={sessions.data} loading={sessions.loading} error={sessions.error} onRetry={sessions.reload} onRevoke={revoke} revoking={revoking} />
      <ConfirmDialog
        open={confirmOthers}
        title="Sign out other sessions?"
        confirmLabel="Sign out others"
        busy={busy}
        error={error}
        onConfirm={revokeOthers}
        onCancel={() => { setConfirmOthers(false); setError(null); }}
      >
        <p>{others} other session{others === 1 ? "" : "s"} will be signed out. This session stays signed in.</p>
      </ConfirmDialog>
    </Card>
  );
}

const SIGN_IN_METHOD: Record<string, string> = {
  local: "Veyra password",
  google: "Google",
  microsoft: "Microsoft",
  oidc: "Single sign-on",
};

export default function Page() {
  return <Suspense fallback={<LoadingState />}><AccountPage /></Suspense>;
}
