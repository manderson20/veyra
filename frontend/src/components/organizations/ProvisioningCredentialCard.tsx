// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Button, Callout, Card, ConfirmDialog, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ProvisioningCredential, ProvisioningCredentialRotated } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The enrollment credential phones use for their first fetch (docs/DEVICE_PROVISIONING.md §3.2). */
export function ProvisioningCredentialCard({ organizationId, editable }: { organizationId: string; editable: boolean }) {
  const toast = useToast();
  const cred = useApiData<ProvisioningCredential>(`/organizations/${organizationId}/provisioning-credential`);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState<string | null>(null);
  const rotate = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<ProvisioningCredentialRotated>(`/organizations/${organizationId}/provisioning-credential/rotate`);
      setPassword(r.password);
      cred.setData(r);
      setConfirm(false);
      toast.success("Enrollment credential ready", "Copy the password now; it is not shown again.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const c = cred.data;
  return (
    <Card title="Phone provisioning" subtitle="New phones use this enrollment credential once; each phone then gets its own."
      actions={editable ? <Button icon="refresh" onClick={() => setConfirm(true)}>{c?.username ? "Rotate credential" : "Create credential"}</Button> : null}>
      {c ? (
        <dl className="dl">
          <dt>Server URL</dt><dd><span className="mono">{c.url}</span> <CopyButton text={c.url} /></dd>
          <dt>User name</dt><dd>{c.username ? <><span className="mono">{c.username}</span> <CopyButton text={c.username} /></> : <span className="subtle">Not created yet</span>}</dd>
          <dt>Password</dt><dd>{password ? <><span className="mono">{password}</span> <CopyButton text={password} /></> : c.username ? <span className="subtle">Shown once when created or rotated</span> : "—"}</dd>
          <dt>Rotated</dt><dd>{c.rotated_at ? formatDateTime(c.rotated_at) : "—"}</dd>
          <dt>On the phone</dt><dd>Settings → Provisioning Server: type HTTPS, server <span className="mono">{c.url.replace(/^https?:\/\//, "")}</span>, this user name and password. Already-provisioned phones keep working when the credential rotates.</dd>
        </dl>
      ) : <p className="muted">Loading…</p>}
      {c?.http_enabled ? <Callout tone="warn">Provisioning is also served over plain HTTP on this server; SIP secrets cross the network unencrypted.</Callout> : null}
      <ConfirmDialog open={confirm} title={c?.username ? "Rotate the enrollment credential?" : "Create the enrollment credential?"} confirmLabel={c?.username ? "Rotate" : "Create"} busy={busy} error={error} onConfirm={rotate} onCancel={() => { setConfirm(false); setError(null); }}>
        <p>Phones that have not completed their first provisioning will need the new password. Provisioned phones are unaffected.</p>
      </ConfirmDialog>
    </Card>
  );
}
