// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { RecoveryCodes, TotpEnrolment } from "@/components/account/TotpEnrolment";
import { Badge, Button, Callout, Card, Dialog, ErrorState, IconButton, LoadingState, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { MfaMethod, MfaMethods } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

/** The account page's two-factor section: status, devices, recovery codes. */
export function TwoFactorCard() {
  const { refresh } = useSession();
  const toast = useToast();
  const data = useApiData<MfaMethods>("/auth/mfa/methods");
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<MfaMethod | null>(null);
  const [regenerate, setRegenerate] = useState(false);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);

  const reload = async () => {
    data.reload();
    await refresh();
  };

  if (data.error) return <Card title="Two-factor authentication"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!data.data) return <Card title="Two-factor authentication"><LoadingState /></Card>;
  const { status, methods } = data.data;

  return (
    <Card
      title="Two-factor authentication"
      subtitle="A code from an authenticator app on your phone is asked for at every sign-in, in addition to your password."
      id="mfa"
      actions={<Button icon="plus" variant={status.enabled ? "secondary" : "primary"} onClick={() => setAdding(true)}>{status.enabled ? "Add a device" : "Set up"}</Button>}
    >
      <div className="stack stack--sm">
        <div className="row">
          <Badge tone={status.enabled ? "ok" : status.required ? "warn" : "neutral"} icon={status.enabled ? "shield" : undefined}>
            {status.enabled ? "On" : "Off"}
          </Badge>
          {status.required ? <span className="subtle">Required for your role{status.grace_until && !status.enabled ? ` by ${formatDateTime(status.grace_until)}` : ""}.</span> : <span className="subtle">Optional for your role.</span>}
        </div>
        {status.required && !status.enabled ? (
          <Callout tone="warn" title="Set up two-factor authentication">
            Your role requires it. {status.grace_until ? `From ${formatDateTime(status.grace_until)} you will not be able to sign in without it.` : "You will be asked to set it up at your next sign-in."}
          </Callout>
        ) : null}
        {methods.length ? (
          <ul className="list-plain">
            {methods.map((m) => (
              <li key={m.id} className="row row--between" style={{ padding: "8px 0", borderTop: "1px solid var(--border)" }}>
                <span>
                  <span className="table__primary" style={{ display: "block" }}>{m.label}</span>
                  <span className="table__secondary">Authenticator app · added {formatRelative(m.created_at)}{m.last_used_at ? ` · last used ${formatRelative(m.last_used_at)}` : ""}</span>
                </span>
                <IconButton icon="trash" size="sm" label={`Remove ${m.label}`} onClick={() => setRemoving(m)} />
              </li>
            ))}
          </ul>
        ) : null}
        {status.enabled ? (
          <div className="row row--between" style={{ paddingTop: 8, borderTop: "1px solid var(--border)" }}>
            <span>
              <span className="table__primary" style={{ display: "block" }}>Recovery codes</span>
              <span className="table__secondary">{status.recovery_codes_remaining} of 10 unused{status.recovery_codes_remaining <= 2 ? " — generate new ones soon" : ""}</span>
            </span>
            <Button size="sm" icon="refresh" onClick={() => setRegenerate(true)}>New codes</Button>
          </div>
        ) : null}
      </div>

      <Dialog open={adding} onClose={() => setAdding(false)} size="lg" title={status.enabled ? "Add another device" : "Set up two-factor authentication"}>
        {adding ? (
          <TotpEnrolment
            onCancel={() => setAdding(false)}
            onDone={(r) => {
              setAdding(false);
              toast.success("Authenticator added", r.recovery_codes.length ? "Two-factor authentication is on." : undefined);
              void reload();
            }}
          />
        ) : null}
      </Dialog>

      <PasswordDialog
        open={removing !== null}
        title={`Remove ${removing?.label ?? "this device"}?`}
        description={methods.length <= 1 ? "This is your only device: removing it turns two-factor authentication off and discards the recovery codes." : "Codes from this device will no longer be accepted."}
        confirmLabel="Remove device"
        tone="danger"
        onClose={() => setRemoving(null)}
        action={async (password) => {
          if (!removing) return;
          const r = await api.post<{ message: string }>(`/auth/mfa/methods/${removing.id}/remove`, { password });
          toast.success("Device removed", r.message);
          setRemoving(null);
          await reload();
        }}
      />

      <PasswordDialog
        open={regenerate && !newCodes}
        title="Generate new recovery codes?"
        description="Your current codes stop working. You will see the new ones once."
        confirmLabel="Generate codes"
        onClose={() => setRegenerate(false)}
        action={async (password) => {
          const r = await api.post<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes/regenerate", { password });
          setNewCodes(r.recovery_codes);
          setSaved(false);
        }}
      />
      <Dialog open={newCodes !== null} onClose={() => { if (saved) { setNewCodes(null); setRegenerate(false); void reload(); } }} busy={!saved} title="Your new recovery codes">
        {newCodes ? <RecoveryCodes codes={newCodes} saved={saved} onSaved={setSaved} onDone={() => { setNewCodes(null); setRegenerate(false); void reload(); }} /> : null}
      </Dialog>
    </Card>
  );
}

function PasswordDialog({ open, title, description, confirmLabel, tone = "primary", onClose, action }: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  tone?: "primary" | "danger";
  onClose: () => void;
  action: (password: string) => Promise<void>;
}) {
  const errors = useFormErrors();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => { setPassword(""); errors.clear(); });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await action(password);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={title} description={description}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant={tone} type="submit" form="mfa-password" loading={busy} disabled={!password}>{confirmLabel}</Button></>}>
      <form id="mfa-password" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Your password" type="password" autoComplete="current-password" required autoFocus value={password} onChange={(e) => setPassword(e.target.value)} help="Confirm it is you." />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export function mfaErrorText(err: unknown): string {
  return errorMessage(err);
}
