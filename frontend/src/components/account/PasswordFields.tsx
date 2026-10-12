// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { TextField } from "@/components/ui";

export const PASSWORD_HELP = "At least 12 characters. A sentence or a few unrelated words is easiest to remember. It must not contain your name or email address.";

/** New password + confirmation, shared by the account page and the reset page. */
export function NewPasswordFields({
  value,
  confirm,
  onChange,
  onConfirmChange,
  error,
  autoFocus,
}: {
  value: string;
  confirm: string;
  onChange: (v: string) => void;
  onConfirmChange: (v: string) => void;
  error?: string | null;
  autoFocus?: boolean;
}) {
  const mismatch = confirm.length > 0 && confirm !== value;
  return (
    <>
      <TextField label="New password" type="password" autoComplete="new-password" required minLength={12} autoFocus={autoFocus}
        help={PASSWORD_HELP} value={value} error={error ?? null} onChange={(e) => onChange(e.target.value)} />
      <TextField label="Confirm new password" type="password" autoComplete="new-password" required value={confirm}
        error={mismatch ? "Passwords do not match." : null} onChange={(e) => onConfirmChange(e.target.value)} />
    </>
  );
}

export function passwordsMatch(value: string, confirm: string): boolean {
  return value.length > 0 && value === confirm;
}
