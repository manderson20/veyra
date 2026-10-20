// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { PasskeyEnrolment } from "@/components/account/PasskeyEnrolment";
import { TotpEnrolment } from "@/components/account/TotpEnrolment";
import { AuthLayout } from "@/components/AuthLayout";
import { BrandLogo } from "@/components/Brand";
import { Button, buttonClass, Callout, Checkbox, LoadingState, TextField } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { MfaChallenge, SessionInfo, SetupStatus, SsoProviderPublic } from "@/lib/types";
import { useSession } from "@/hooks/useSession";
import { getPasskey, passkeyErrorText, passkeyUnavailableReason } from "@/lib/webauthn";

function safeNext(value: string | null): string {
  // Only allow same-site relative paths (prevents open redirects).
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) return "/";
  return value;
}

type Stage = { kind: "password" } | { kind: "mfa"; challenge: MfaChallenge } | { kind: "enrol"; challenge: MfaChallenge };

function isChallenge(value: unknown): value is MfaChallenge {
  return typeof value === "object" && value !== null && (value as MfaChallenge).mfa_pending === true;
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
  const [stage, setStage] = useState<Stage>({ kind: "password" });
  const [providers, setProviders] = useState<SsoProviderPublic[]>([]);
  const [selfReset, setSelfReset] = useState(false);
  const [enrolPasskey, setEnrolPasskey] = useState(false);
  const next = safeNext(params.get("next"));
  const ssoError = params.get("sso_error");

  useEffect(() => {
    api
      .get<SsoProviderPublic[]>("/auth/sso/providers", undefined, { noRedirect: true })
      .then(setProviders)
      .catch(() => setProviders([]));
    api
      .get<{ self_service: boolean }>("/auth/password-reset/options", undefined, { noRedirect: true })
      .then((o) => setSelfReset(o.self_service))
      .catch(() => setSelfReset(false));
  }, []);

  const finish = async (s: SessionInfo | undefined) => {
    await refresh();
    router.replace(s?.must_change_password ? "/account/?reason=signin" : next);
  };

  useEffect(() => {
    if (session) {
      router.replace(session.must_change_password ? "/account/?reason=signin" : next);
      return;
    }
    // A pre-authentication session may already exist (page reload during the second step).
    api
      .get<MfaChallenge>("/auth/mfa/challenge", undefined, { noRedirect: true })
      .then((c) => {
        if (c.mfa_pending) setStage({ kind: c.enrol ? "enrol" : "mfa", challenge: c });
        setChecking(false);
      })
      .catch(() =>
        api
          .get<SetupStatus>("/setup/status", undefined, { noRedirect: true })
          .then((s) => {
            if (s.setup_required) router.replace("/setup/");
            else setChecking(false);
          })
          .catch(() => setChecking(false)),
      );
  }, [session, router, next]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api.post<SessionInfo | MfaChallenge>("/auth/login", { email, password }, { noRedirect: true });
      if (isChallenge(s)) {
        setPassword("");
        setStage({ kind: s.enrol ? "enrol" : "mfa", challenge: s });
        setBusy(false);
        return;
      }
      await finish(s);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail || err.title : errorMessage(err));
      setBusy(false);
    }
  };

  const startOver = async () => {
    try {
      await api.post("/auth/logout", undefined, { noRedirect: true });
    } catch {
      /* the pre-auth session expires by itself */
    }
    setStage({ kind: "password" });
    setError(null);
  };

  if (checking) return <LoadingState />;

  if (stage.kind === "mfa") {
    return <MfaStep challenge={stage.challenge} onDone={finish} onStartOver={startOver} />;
  }
  if (stage.kind === "enrol") {
    return (
      <div className="stack">
        <div className="row" style={{ marginBottom: 8 }}><BrandLogo height={30} /></div>
        <div>
          <h1 className="auth__title">Set up two-factor authentication</h1>
          <p className="muted">Hello {stage.challenge.display_name}. Your role requires a second factor, and none is set up yet. This takes about a minute.</p>
        </div>
        {enrolPasskey ? <PasskeyEnrolment onDone={(r) => void finish(r.session)} /> : <TotpEnrolment compact onDone={(r) => void finish(r.session)} />}
        <div className="row row--between">
          <button type="button" className="link" onClick={() => setEnrolPasskey((v) => !v)}>{enrolPasskey ? "Use an authenticator app instead" : "Use a passkey instead (fingerprint, face or security key)"}</button>
          <button type="button" className="link subtle" onClick={startOver}>Not you? Sign in as someone else</button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="row" style={{ marginBottom: 8 }}>
        <BrandLogo height={30} />
      </div>
      <div>
        <h1 className="auth__title">Sign in</h1>
        <p className="muted">{providers.length ? "Use your organization's account, or your Veyra password." : "Use your Veyra account."}</p>
      </div>
      {ssoError ? <Callout tone="danger">{ssoError}</Callout> : null}
      {providers.length ? (
        <div className="stack stack--sm">
          {providers.map((p) => (
            <a key={p.id} className={buttonClass("secondary", "md", true)} href={`/api/v1/auth/sso/${p.id}/start?next=${encodeURIComponent(next)}`}>
              Sign in with {p.name}
            </a>
          ))}
          <p className="subtle" style={{ textAlign: "center", margin: 0 }}>or with a password</p>
        </div>
      ) : null}
      <form className="stack stack--sm" onSubmit={submit} noValidate={false}>
        <TextField label="Email address" type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
        <Button variant="primary" type="submit" loading={busy} block>
          Sign in
        </Button>
      </form>
      {selfReset ? (
        <p style={{ textAlign: "center", margin: 0 }}><Link href="/forgot-password/">Forgot your password?</Link></p>
      ) : null}
      <p className="subtle">
        {selfReset ? "" : "Forgotten your password? Ask an administrator for a reset link. "}The local recovery administrator can always
        sign in here, even when single sign-on is configured, and can be reset from the server with{" "}
        <span className="mono">veyra users reset-password</span>.
      </p>
    </div>
  );
}

function MfaStep({ challenge, onDone, onStartOver }: { challenge: MfaChallenge; onDone: (s: SessionInfo) => Promise<void>; onStartOver: () => Promise<void> }) {
  const hasPasskey = challenge.methods.some((m) => m.type === "webauthn");
  const hasTotp = challenge.methods.some((m) => m.type === "totp");
  const passkeyBlocked = passkeyUnavailableReason();
  // Issue #107: the passkey prompt first when the account has one.
  const [mode, setMode] = useState<"passkey" | "code" | "recovery">(hasPasskey && !passkeyBlocked ? "passkey" : hasTotp ? "code" : "recovery");
  const [code, setCode] = useState("");
  const [trust, setTrust] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const failed = async (err: unknown) => {
    // Locked after repeated failures, or the pre-auth session expired: back to the password.
    if (err instanceof ApiError && (err.code === "mfa_locked" || err.code === "unauthorized")) {
      setError(err.detail || err.title);
      await onStartOver();
      return;
    }
    setError(passkeyErrorText(err) ?? errorMessage(err));
    setCode("");
    setBusy(false);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await api.post<SessionInfo>("/auth/mfa/verify", { code: code.trim(), trust_browser: trust }, { noRedirect: true });
      await onDone(s);
    } catch (err) {
      await failed(err);
    }
  };
  const signWithPasskey = async () => {
    setBusy(true);
    setError(null);
    try {
      const begin = await api.post<{ options: Record<string, unknown> }>("/auth/mfa/webauthn/authenticate/begin", undefined, { noRedirect: true });
      const credential = await getPasskey(begin.options);
      const s = await api.post<SessionInfo>("/auth/mfa/webauthn/authenticate/finish", { credential, trust_browser: trust }, { noRedirect: true });
      await onDone(s);
    } catch (err) {
      await failed(err);
    }
  };
  const trustBox = challenge.trust_days ? (
    <Checkbox label={`Trust this browser for ${challenge.trust_days} days`} checked={trust} onChange={(e) => setTrust(e.target.checked)}
      description="Signing in here then needs only your password. Not on a shared computer." />
  ) : null;
  const prompt = mode === "passkey" ? "Confirm with your passkey: fingerprint, face, device PIN or security key."
    : mode === "recovery" ? "Enter one of your recovery codes." : "Enter the code from your authenticator app.";

  return (
    <div className="stack">
      <div className="row" style={{ marginBottom: 8 }}><BrandLogo height={30} /></div>
      <div>
        <h1 className="auth__title">Second step</h1>
        <p className="muted">Hello {challenge.display_name}. {prompt}</p>
      </div>
      {mode === "passkey" ? (
        <div className="stack stack--sm">
          {trustBox}
          {error ? <Callout tone="danger">{error}</Callout> : null}
          <Button variant="primary" icon="key" loading={busy} block onClick={() => void signWithPasskey()}>Use your passkey</Button>
        </div>
      ) : (
        <form className="stack stack--sm" onSubmit={submit}>
          {mode === "recovery" ? (
            <TextField label="Recovery code" required autoFocus autoComplete="off" spellCheck={false} placeholder="ABCDE-FGHJK" value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())} help="Each recovery code works once." />
          ) : (
            <TextField label="Authenticator code" required autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code}
              onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))} />
          )}
          {trustBox}
          {error ? <Callout tone="danger">{error}</Callout> : null}
          <Button variant="primary" type="submit" loading={busy} block disabled={!code.trim()}>Verify</Button>
        </form>
      )}
      {hasPasskey && passkeyBlocked && mode !== "passkey" ? <p className="subtle" style={{ margin: 0 }}>Your passkey cannot be used on this page: {passkeyBlocked}</p> : null}
      <div className="stack stack--sm">
        {hasPasskey && !passkeyBlocked && mode !== "passkey" ? <button type="button" className="link" onClick={() => { setMode("passkey"); setError(null); }}>Use your passkey instead</button> : null}
        {hasTotp && mode !== "code" ? <button type="button" className="link" onClick={() => { setMode("code"); setCode(""); setError(null); }}>Use an authenticator code instead</button> : null}
        {mode !== "recovery" ? <button type="button" className="link" onClick={() => { setMode("recovery"); setCode(""); setError(null); }}>Lost your device? Use a recovery code</button> : null}
        <button type="button" className="link subtle" onClick={() => void onStartOver()}>Start over</button>
      </div>
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
