// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { CallFlowFields, EMPTY_CALL_FLOW, callFlowBody, callFlowDraft, callFlowValid, type CallFlowDraft } from "@/components/callflow/CallFlowFields";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CallFlow } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function CallFlowView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const item = useApiData<CallFlow>(id ? `/call-flows/${encodeURIComponent(id)}` : null);
  const editable = can("routing.write");
  const [draft, setDraft] = useState<CallFlowDraft>(EMPTY_CALL_FLOW);
  const [busy, setBusy] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(item.data, (f) => {
    if (f) setDraft(callFlowDraft(f));
  });

  if (!id) return <ErrorState title="No call flow selected" error={{ message: "Open a call flow from the list." }} />;
  if (item.error) return <ErrorState title="Could not load call flow" error={item.error} onRetry={item.reload} />;
  if (!item.data) return <LoadingState />;
  const f = item.data;
  const dirty = JSON.stringify(callFlowBody(draft)) !== JSON.stringify(callFlowBody(callFlowDraft(f)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      item.setData(await api.patch<CallFlow>(`/call-flows/${f.id}`, callFlowBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Call flow saved", "Deploy changes to apply it to the phone system.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (override: boolean) => {
    setSwitching(true);
    try {
      item.setData(await api.post<CallFlow>(`/call-flows/${f.id}/state`, { override }));
      toast.success(override ? "Switched" : "Back to normal", "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not switch the call flow", errorMessage(err));
    } finally {
      setSwitching(false);
    }
  };

  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/call-flows/${f.id}`);
      toast.success(`Call flow "${f.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/routing/call-flows/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/routing/call-flows/", label: "Call flows" }}
        title={f.name}
        description={
          <span className="row">
            <span>{f.organization_name}</span>
            <Badge tone={f.override ? "warn" : "ok"} icon={f.override ? "alert" : "checkCircle"}>{f.override ? "Switched" : "Normal"}</Badge>
            <Badge tone={f.is_enabled ? "ok" : "neutral"}>{f.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {f.problems.length ? <Badge tone="warn" icon="alert">{f.problems.length} problem{f.problems.length === 1 ? "" : "s"}</Badge> : null}
            {f.in_use_by ? <Badge tone="outline">Used by {f.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <span className="row"><Button variant={f.override ? "primary" : "secondary"} icon="power" loading={switching} onClick={() => toggle(!f.override)}>{f.override ? "Back to normal" : "Switch now"}</Button><Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button></span> : null}
      />
      <PendingChanges refreshKey={changed} />
      {f.problems.length ? (
        <Callout tone="warn" title="Check this call flow">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{f.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Call flow" subtitle={editable ? undefined : "You can view but not change this call flow."}>
          <form className="stack stack--sm" onSubmit={save}>
            <CallFlowFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={f.organization_id} current={f} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(callFlowDraft(f))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !callFlowValid(draft)}>Save</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="Right now" subtitle="Where calls that enter this flow go at this moment.">
            <dl className="dl">
              <dt>State</dt><dd>{f.override ? "Switched" : "Normal"}{f.override && f.override_by ? ` by ${f.override_by}` : ""}{f.override && f.override_at ? `, ${formatRelative(f.override_at)}` : ""}</dd>
              <dt>Calls go to</dt><dd><DestinationLabel d={f.override ? f.override_destination : f.normal} /></dd>
              <dt>Phone code</dt><dd>{f.code ? <><span className="mono">{f.code}</span>{f.has_pin ? " (PIN)" : ""}</> : <Badge tone="warn">Toggle code disabled</Badge>}</dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{f.context}</dd>
              <dt>Organization</dt><dd>{f.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(f.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(f.updated_at)}</dd>
              <dt>Call flow ID</dt><dd className="mono">{f.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the call flow "${f.name}"?`} confirmLabel="Delete call flow" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes, menus, groups and announcements that point at it must be changed first. It leaves the phone system at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><CallFlowView /></Suspense>;
}
