// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { RecoveryCodes } from "@/components/account/TotpEnrolment";
import { Button, Callout, TextField } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { TotpConfirm } from "@/lib/types";
import { createPasskey, passkeyErrorText, passkeyUnavailableReason } from "@/lib/webauthn";

/** Add a passkey (issue #107): Touch ID, Windows Hello, a security key or a
 * phone. The first factor of an account also returns recovery codes. */
export function PasskeyEnrolment({ onDone, onCancel }: { onDone: (result: TotpConfirm) => void; onCancel?: () => void }) {
  const [label, setLabel] = useState(defaultLabel());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TotpConfirm | null>(null);
  const [saved, setSaved] = useState(false);
  const unavailable = passkeyUnavailableReason();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const begin = await api.post<{ method_id: string; options: Record<string, unknown> }>("/auth/mfa/webauthn/register/begin", { label: label.trim() || "Passkey" }, { noRedirect: true });
      const credential = await createPasskey(begin.options);
      const r = await api.post<TotpConfirm>("/auth/mfa/webauthn/register/finish", { method_id: begin.method_id, credential, label: label.trim() || null }, { noRedirect: true });
      if (r.recovery_codes.length === 0) onDone(r);
      else setResult(r);
    } catch (err) {
      setError(passkeyErrorText(err) ?? errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return <RecoveryCodes codes={result.recovery_codes} saved={saved} onSaved={setSaved} onDone={() => onDone(result)} session={result.session} />;
  }
  if (unavailable) {
    return (
      <div className="stack stack--sm">
        <Callout tone="warn" title="Passkeys are not available on this page">{unavailable} Use an authenticator app instead, or open Veyra by its host name.</Callout>
        {onCancel ? <div className="form-actions"><Button onClick={onCancel}>Close</Button></div> : null}
      </div>
    );
  }
  return (
    <form className="stack stack--sm" onSubmit={submit}>
      <p style={{ margin: 0 }}>Your browser asks you to confirm with your fingerprint, face, device PIN or security key. Nothing biometric leaves your device.</p>
      <TextField label="Name" value={label} onChange={(e) => setLabel(e.target.value)} help="To tell your passkeys apart, for example “MacBook Touch ID”." />
      {error ? <Callout tone="danger">{error}</Callout> : null}
      <div className="form-actions">
        {onCancel ? <Button onClick={onCancel} disabled={busy}>Cancel</Button> : null}
        <Button variant="primary" type="submit" icon="key" loading={busy}>Create passkey</Button>
      </div>
    </form>
  );
}

function defaultLabel(): string {
  if (typeof navigator === "undefined") return "Passkey";
  const ua = navigator.userAgent;
  if (/Macintosh/.test(ua)) return "Mac Touch ID";
  if (/iPhone|iPad/.test(ua)) return "iPhone";
  if (/Windows/.test(ua)) return "Windows Hello";
  if (/Android/.test(ua)) return "Android phone";
  return "Passkey";
}
