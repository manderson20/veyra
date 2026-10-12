"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { AuthLayout } from "@/components/AuthLayout";
import { BrandLogo } from "@/components/Brand";
import { Button, Callout, LoadingState, TextField } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { SetupStatus } from "@/lib/types";
import { useSession } from "@/hooks/useSession";

function safeNext(value: string | null): string {
  // Only allow same-site relative paths (prevents open redirects).
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) return "/";
  return value;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { session, refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const next = safeNext(params.get("next"));

  useEffect(() => {
    if (session) {
      router.replace(next);
      return;
    }
    api
      .get<SetupStatus>("/setup/status", undefined, { noRedirect: true })
      .then((s) => {
        if (s.setup_required) router.replace("/setup/");
        else setChecking(false);
      })
      .catch(() => setChecking(false));
  }, [session, router, next]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { email, password }, { noRedirect: true });
      await refresh();
      router.replace(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail || err.title : errorMessage(err));
      setBusy(false);
    }
  };

  if (checking) return <LoadingState />;
  return (
    <div className="stack">
      <div className="row" style={{ marginBottom: 8 }}>
        <BrandLogo height={30} />
      </div>
      <div>
        <h1 className="auth__title">Sign in</h1>
        <p className="muted">Use your Veyra administrator account.</p>
      </div>
      <form className="stack stack--sm" onSubmit={submit} noValidate={false}>
        <TextField label="Email address" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
        <Button variant="primary" type="submit" loading={busy} block>
          Sign in
        </Button>
      </form>
      <p className="subtle">
        Locked out? The local recovery administrator can always sign in here, even when single sign-on is configured.
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <AuthLayout>
      <Suspense fallback={<LoadingState />}>
        <LoginForm />
      </Suspense>
    </AuthLayout>
  );
}
