// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { AuthLayout } from "@/components/AuthLayout";
import { BrandLogo } from "@/components/Brand";
import { Button, Callout, TextField } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

/** Self-service password reset (POST /auth/password-reset/request): the
 * server emails a one-time link and answers the same for any address. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ message: string }>("/auth/password-reset/request", { email: email.trim() }, { noRedirect: true });
      setSent(r.message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <div className="stack">
        <div className="row" style={{ marginBottom: 8 }}>
          <BrandLogo height={30} />
        </div>
        <div>
          <h1 className="auth__title">Forgot your password?</h1>
          <p className="muted">Enter the email address you sign in with. We will email you a link to choose a new password.</p>
        </div>
        {sent ? (
          <>
            <Callout tone="ok" title="Check your email">{sent}</Callout>
            <Link href="/login/" className="btn btn--secondary">Back to sign in</Link>
          </>
        ) : (
          <form className="stack stack--sm" onSubmit={submit}>
            <TextField label="Email address" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            {error ? <Callout tone="danger">{error}</Callout> : null}
            <Button variant="primary" type="submit" loading={busy} disabled={!email.trim()} block>Email me a reset link</Button>
            <Link href="/login/" className="subtle" style={{ textAlign: "center" }}>Back to sign in</Link>
          </form>
        )}
        <p className="subtle">Accounts that sign in with Google or Microsoft change their password there.</p>
      </div>
    </AuthLayout>
  );
}
