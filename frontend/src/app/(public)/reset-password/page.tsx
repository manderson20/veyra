// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { NewPasswordFields, passwordsMatch } from "@/components/account/PasswordFields";
import { AuthLayout } from "@/components/AuthLayout";
import { BrandLogo } from "@/components/Brand";
import { Button, Callout, LoadingState } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ResetTokenInfo } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";

type State = { kind: "checking" } | { kind: "invalid"; message: string } | { kind: "ready"; info: ResetTokenInfo } | { kind: "done" };

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const errors = useFormErrors();
  const [state, setState] = useState<State>(() =>
    token ? { kind: "checking" } : { kind: "invalid", message: "This link is missing its reset code. Request a new one from the sign-in page, or ask an administrator." },
  );
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .post<ResetTokenInfo>("/auth/password-reset/check", { token }, { noRedirect: true })
      .then((info) => setState({ kind: "ready", info }))
      .catch((err) => setState({ kind: "invalid", message: errorMessage(err) }));
  }, [token]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!passwordsMatch(password, confirm)) return;
    setBusy(true);
    errors.clear();
    try {
      await api.post("/auth/password-reset", { token, new_password: password }, { noRedirect: true });
      setState({ kind: "done" });
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row" style={{ marginBottom: 8 }}>
        <BrandLogo height={30} />
      </div>
      {state.kind === "checking" ? <LoadingState label="Checking the reset link…" /> : null}
      {state.kind === "invalid" ? (
        <>
          <div>
            <h1 className="auth__title">Reset link not valid</h1>
            <p className="muted">{state.message}</p>
          </div>
          <Link href="/login/" className="btn btn--secondary">Back to sign in</Link>
        </>
      ) : null}
      {state.kind === "ready" ? (
        <>
          <div>
            <h1 className="auth__title">Set a new password</h1>
            <p className="muted">
              For <strong>{state.info.display_name}</strong> ({state.info.email}). This link works once and expires {formatDateTime(state.info.expires_at)}.
            </p>
          </div>
          <form className="stack stack--sm" onSubmit={submit}>
            <NewPasswordFields value={password} confirm={confirm} onChange={setPassword} onConfirmChange={setConfirm} error={errors.fields.new_password} autoFocus />
            {errors.message && !errors.fields.new_password ? <Callout tone="danger">{errors.message}</Callout> : null}
            <Button variant="primary" type="submit" loading={busy} disabled={!passwordsMatch(password, confirm)} block>Set password</Button>
          </form>
          <p className="subtle">Setting the password signs this account out everywhere. You will sign in with the new password next.</p>
        </>
      ) : null}
      {state.kind === "done" ? (
        <>
          <Callout tone="ok" title="Password set">Sign in with your new password.</Callout>
          <Link href="/login/" className="btn btn--primary">Go to sign in</Link>
        </>
      ) : null}
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthLayout>
      <Suspense fallback={<LoadingState />}>
        <ResetForm />
      </Suspense>
    </AuthLayout>
  );
}
