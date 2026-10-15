// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, useToast } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { MultiTenancyCheck, MultiTenancyStatus } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The multi-tenancy switch (docs/MULTI_TENANCY.md §6): turning it on runs the
 * isolation checks first; turning it off needs a single active organization. */
export function MultiTenancyCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const st = useApiData<MultiTenancyStatus>("/system/multi-tenancy");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checks, setChecks] = useState<MultiTenancyCheck[] | null>(null);
  const d = st.data;

  const toggle = async () => {
    if (!d) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<MultiTenancyStatus>("/system/multi-tenancy", { enabled: !d.enabled });
      setChecks(r.checks ?? null);
      toast.success(r.enabled ? "Multi-tenancy is on" : "Multi-tenancy is off", r.enabled ? "You can add organizations now; each gets its own phones, numbers and voicemail." : "");
      setConfirm(false);
      st.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail || err.title : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Multi-tenancy" subtitle="Several organizations on one installation, whose phones cannot reach each other."
      actions={editable && d ? <Button variant={d.enabled ? "secondary" : "primary"} onClick={() => setConfirm(true)}>{d.enabled ? "Turn off" : "Turn on"}</Button> : null}>
      {st.loading ? <LoadingState /> : null}
      {st.error ? <ErrorState error={st.error} onRetry={st.reload} /> : null}
      {d ? (
        <div className="stack stack--sm">
          <p className="row" style={{ gap: 8 }}>
            <Badge tone={d.enabled ? "ok" : "neutral"}>{d.enabled ? "On" : "Off"}</Badge>
            <span className="muted">{d.active_organizations} active organization{d.active_organizations === 1 ? "" : "s"}</span>
          </p>
          {!d.enabled && d.active_organizations > 1 ? (
            <Callout tone="warn" title="Several organizations without isolation">
              These organizations share one dialplan: their phones can reach each other. Turn multi-tenancy on.
            </Callout>
          ) : null}
          <div>
            <p className="field__label">Shared by every organization</p>
            <ul className="stack" style={{ paddingLeft: 20, gap: 4, margin: 0 }}>
              {d.shared.map((s) => <li key={s} className="subtle">{s}</li>)}
            </ul>
          </div>
          {checks?.length ? (
            <ul className="list-plain">
              {checks.map((c) => (
                <li key={c.name} className="list-row">
                  <span><Badge tone={c.ok ? "ok" : "danger"}>{c.ok ? "Passed" : "Failed"}</Badge> <strong>{c.name}</strong></span>
                  <span className="subtle">{c.detail}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <ConfirmDialog open={confirm} title={d?.enabled ? "Turn multi-tenancy off?" : "Turn multi-tenancy on?"} confirmLabel={d?.enabled ? "Turn off" : "Run checks and turn on"}
        busy={busy} error={error} onConfirm={toggle} onCancel={() => { setConfirm(false); setError(null); }}>
        {d?.enabled ? (
          <p>Only possible while a single organization is active. New organizations cannot be added afterwards.</p>
        ) : (
          <p>Veyra first generates the configuration with a test copy of your organization and proves that neither can reach the other&apos;s phones, contexts, voicemail or queues. Your current organization keeps its names; nothing changes for its phones.</p>
        )}
      </ConfirmDialog>
    </Card>
  );
}
