// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Button, Callout, Checkbox, LoadingState, TextField } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { SessionInfo, TotpBegin, TotpConfirm } from "@/lib/types";


/**
 * Authenticator-app enrolment: QR code (or manual key), first code, then the
 * recovery codes shown once. Used on the sign-in page (pre-authentication
 * session) and on the account page (adding a device).
 */
export function TotpEnrolment({ onDone, onCancel, compact = false }: {
  onDone: (result: TotpConfirm) => void;
  onCancel?: () => void;
  compact?: boolean;
}) {
  const [begin, setBegin] = useState<TotpBegin | null>(null);
  const [label, setLabel] = useState("Authenticator app");
  const [code, setCode] = useState("");
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TotpConfirm | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.post<TotpBegin>("/auth/mfa/totp/begin", { label: "Authenticator app" }, { noRedirect: true })
      .then((b) => { if (!cancelled) setBegin(b); })
      .catch((e) => { if (!cancelled) setError(errorMessage(e)); });
    return () => { cancelled = true; };
  }, []);

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    if (!begin) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<TotpConfirm>("/auth/mfa/totp/confirm", { method_id: begin.method_id, code: code.trim(), label: label.trim() || null }, { noRedirect: true });
      if (r.recovery_codes.length === 0) {
        onDone(r);
        return;
      }
      setResult(r);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return <RecoveryCodes codes={result.recovery_codes} saved={saved} onSaved={setSaved} onDone={() => onDone(result)} session={result.session} />;
  }
  if (error && !begin) return <Callout tone="danger" title="Could not start enrolment">{error}</Callout>;
  if (!begin) return <LoadingState label="Preparing your authenticator…" />;

  return (
    <form className="stack stack--sm" onSubmit={confirm}>
      {!compact ? (
        <p className="muted">
          Open an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy, 1Password and others work), add an account and scan this code.
        </p>
      ) : null}
      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <img src={begin.qr_svg} alt="QR code for your authenticator app" width={180} height={180} style={{ borderRadius: 8, background: "#fff", flex: "0 0 auto" }} />
        <div className="stack stack--sm" style={{ minWidth: 0, flex: 1 }}>
          <button type="button" className="btn btn--ghost btn--sm" style={{ alignSelf: "flex-start" }} onClick={() => setManual((m) => !m)}>
            {manual ? "Hide the key" : "Can't scan? Enter the key by hand"}
          </button>
          {manual ? (
            <div className="stack stack--sm">
              <span className="mono" style={{ wordBreak: "break-all", fontSize: 13 }}>{begin.secret.replace(/(.{4})/g, "$1 ").trim()}</span>
              <div className="row"><CopyButton text={begin.secret} label="Copy key" /><span className="subtle">Time-based, 6 digits, 30 seconds.</span></div>
            </div>
          ) : null}
          <TextField label="Name this device (optional)" value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} help="For example “Work phone”." />
        </div>
      </div>
      <TextField label="Code from the app" required autoFocus inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]*" maxLength={7}
        value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))} help="Enter the 6-digit code the app shows now." />
      {error ? <Callout tone="danger">{error}</Callout> : null}
      <div className="form-actions">
        {onCancel ? <Button onClick={onCancel} disabled={busy}>Cancel</Button> : null}
        <Button variant="primary" type="submit" loading={busy} disabled={code.replace(/\s/g, "").length !== 6}>Verify and enable</Button>
      </div>
    </form>
  );
}

export function RecoveryCodes({ codes, saved, onSaved, onDone, session, title = "Save your recovery codes" }: {
  codes: string[];
  saved: boolean;
  onSaved: (v: boolean) => void;
  onDone: () => void;
  session?: SessionInfo;
  title?: string;
}) {
  const text = `Veyra recovery codes${session ? ` for ${session.user.email}` : ""}\nEach code works once. Keep them somewhere safe, away from your phone.\n\n${codes.join("\n")}\n`;
  const download = () => {
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "veyra-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="stack stack--sm">
      <Callout tone="warn" title={title}>
        If you lose your phone, one of these codes signs you in instead of the app. Each works once. They are shown only now; store them somewhere safe and not on the phone.
      </Callout>
      <div className="code" style={{ columnCount: 2, columnGap: 24, fontSize: 15, letterSpacing: "0.04em" }}>
        {codes.map((c) => <div key={c}>{c}</div>)}
      </div>
      <div className="row">
        <Button icon="download" onClick={download}>Download</Button>
        <CopyButton text={codes.join("\n")} label="Copy all" />
      </div>
      <Checkbox label="I have saved these codes" checked={saved} onChange={(e) => onSaved(e.target.checked)} />
      <div className="form-actions"><Button variant="primary" disabled={!saved} onClick={onDone}>Continue</Button></div>
    </div>
  );
}
