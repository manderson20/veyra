// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Callout, Dialog, TextField } from "@/components/ui";
import { api, errorMessage, setReauthPrompt } from "@/lib/api";
import { useSession } from "@/hooks/useSession";

/** Asks for the password again before a sensitive action (#137): granting a
 * role, resetting someone's sign-in, changing a sign-in policy, installing an
 * update, failing over. The refused request is sent again on success. */
export function ReauthDialog() {
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const settle = useRef<((ok: boolean) => void) | null>(null);
  const needsCode = !!session?.mfa?.enabled;

  useEffect(() => {
    setReauthPrompt(() => new Promise<boolean>((resolve) => {
      settle.current = resolve;
      setPassword("");
      setCode("");
      setError(null);
      setOpen(true);
    }));
    return () => setReauthPrompt(null);
  }, []);

  const finish = (ok: boolean) => {
    setOpen(false);
    settle.current?.(ok);
    settle.current = null;
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/reauth", { password, ...(needsCode ? { code: code.trim() } : {}) });
      finish(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={() => finish(false)} busy={busy} title="Confirm it is you"
      description="This action changes who can sign in or what the system runs. Enter your password again; it is not asked again for 15 minutes."
      footer={<><Button onClick={() => finish(false)} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="reauth-form" loading={busy} disabled={!password || (needsCode && !code.trim())}>Continue</Button></>}>
      <form id="reauth-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Password" type="password" required autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {needsCode ? (
          <TextField label="Authenticator code" required inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))} />
        ) : null}
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </form>
    </Dialog>
  );
}
