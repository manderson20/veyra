// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, LoadingState, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApiData } from "@/hooks/useApiData";

interface KeyInfo {
  fingerprint: string | null;
  rotation: { started_at: string; finished_at: string | null; running: boolean; ok: boolean; output: string } | null;
}

/** Rotate the installation key from the interface (issue #125;
 * docs/PRODUCTION_HARDENING.md §3.1): the console's command, run by a root unit. */
export function InstallationKeyCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const info = useApiData<KeyInfo>("/system/installation-key");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = !!info.data?.rotation?.running;
  const reload = info.reload;
  // The services restart at the end: keep asking until the result is in.
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(reload, 3000);
    return () => window.clearInterval(t);
  }, [running, reload]);

  const rotate = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/system/installation-key/rotate");
      toast.success("Rotation started", "The web interface restarts in a moment.");
      setConfirm(false);
      window.setTimeout(reload, 2000);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const d = info.data;
  const r = d?.rotation;
  return (
    <Card title="Installation key" subtitle="The key that encrypts the stored secrets: SIP passwords, the SMTP password, two-factor secrets, recordings."
      footer={editable ? <Button onClick={() => setConfirm(true)} disabled={running || busy}>Rotate the key…</Button> : undefined}>
      {!d ? <LoadingState /> : (
        <div className="stack stack--sm">
          <dl className="dl">
            <dt>Fingerprint</dt><dd className="mono">{d.fingerprint ?? "Not readable"}</dd>
            {r ? <><dt>Last rotation</dt><dd>{r.running ? <Badge tone="info">Running…</Badge> : <Badge tone={r.ok ? "ok" : "danger"}>{r.ok ? "Done" : "Failed"}</Badge>} <span className="subtle">{formatDateTime(r.finished_at ?? r.started_at)}</span></dd></> : null}
          </dl>
          {r && !r.running && !r.ok ? <pre className="mono" style={{ whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto", margin: 0 }}>{r.output}</pre> : null}
          {error ? <Callout tone="danger">{error}</Callout> : null}
        </div>
      )}
      <ConfirmDialog open={confirm} title="Rotate the installation key?" confirmLabel="Rotate now" busy={busy} error={error} onConfirm={() => void rotate()} onCancel={() => setConfirm(false)}>
        <p>A new key is made and every stored secret is encrypted with it; the previous key is kept beside it on the server. The web interface and the worker restart (under a minute); calls are not affected.</p>
        <p className="subtle">Afterwards take a backup, and remove the previous key file once the backup is verified (docs/PRODUCTION_HARDENING.md §3.1).</p>
      </ConfirmDialog>
    </Card>
  );
}
