// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_QUEUE, QUEUE_MUSIC_LABELS, QUEUE_STRATEGY_LABELS, QueueFields, queueBody, queueDraft, queueValid, type QueueDraft } from "@/components/groups/QueueFields";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { CallQueue } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function QueueView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const queue = useApiData<CallQueue>(id ? `/queues/${encodeURIComponent(id)}` : null);
  const editable = can("groups.write");
  const [draft, setDraft] = useState<QueueDraft>(EMPTY_QUEUE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const [agentBusy, setAgentBusy] = useState<string | null>(null);

  useOnChange(queue.data, (q) => {
    if (q) setDraft(queueDraft(q));
  });

  if (!id) return <ErrorState title="No queue selected" error={{ message: "Open a queue from the list." }} />;
  if (queue.error) return <ErrorState title="Could not load queue" error={queue.error} onRetry={queue.reload} />;
  if (!queue.data) return <LoadingState />;
  const q = queue.data;
  const dirty = JSON.stringify(queueBody(draft)) !== JSON.stringify(queueBody(queueDraft(q)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      queue.setData(await api.patch<CallQueue>(`/queues/${q.id}`, queueBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Queue saved", "Deploy changes to apply it to the phone system.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/queues/${q.id}`);
      toast.success(`Queue "${q.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/queues/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  const agents = q.members.length;
  const setAgent = async (extensionId: string, body: { logged_in?: boolean; paused?: boolean }, kind: string) => {
    setAgentBusy(`${extensionId}:${kind}`);
    try {
      queue.setData(await api.post<CallQueue>(`/queues/${q.id}/agents/${extensionId}/state`, body));
    } catch (err) {
      toast.error("Could not change the agent", errorMessage(err));
    } finally {
      setAgentBusy(null);
    }
  };
  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/queues/", label: "Call queues" }}
        title={<span className="row"><span className="mono">{q.number}</span><span>{q.name}</span></span>}
        description={
          <span className="row">
            <span>{q.organization_name}</span>
            <Badge tone={q.is_enabled ? "ok" : "neutral"}>{q.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {q.problems.length ? <Badge tone="warn" icon="alert">{q.problems.length} problem{q.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
            {q.in_use_by ? <Badge tone="outline">Used by {q.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {q.problems.length ? (
        <Callout tone="warn" title="This queue will not work as configured">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{q.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Queue" subtitle={editable ? undefined : "You can view but not change this queue."}>
          <form className="stack stack--sm" onSubmit={save}>
            <QueueFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={q.organization_id} current={q} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(queueDraft(q))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !queueValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          {q.members.some((m) => m.dynamic) ? (
            <Card title="Agents" subtitle="Dynamic agents log in and out here or from their phones; changes apply at once.">
              <ul className="list-plain">
                {q.members.filter((m) => m.dynamic).map((m) => (
                  <li key={m.extension_id} className="list-row" style={{ padding: "var(--space-2) 0" }}>
                    <span className="row" style={{ gap: 8 }}>
                      <span className="table__primary">{m.number} — {m.display_name}</span>
                      <Badge tone={m.logged_in ? (m.paused ? "warn" : "ok") : "neutral"}>{m.logged_in ? (m.paused ? "Paused" : "Logged in") : "Logged out"}</Badge>
                    </span>
                    {editable ? (
                      <span className="row" style={{ gap: 4 }}>
                        <Button size="sm" loading={agentBusy === `${m.extension_id}:login`} disabled={agentBusy !== null} onClick={() => setAgent(m.extension_id, { logged_in: !m.logged_in }, "login")}>{m.logged_in ? "Log out" : "Log in"}</Button>
                        <Button size="sm" variant="ghost" loading={agentBusy === `${m.extension_id}:pause`} disabled={agentBusy !== null || !m.logged_in} onClick={() => setAgent(m.extension_id, { paused: !m.paused }, "pause")}>{m.paused ? "Resume" : "Pause"}</Button>
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
          <Card title="As deployed" subtitle="What the phone system does with this queue after the next deployment.">
            <dl className="dl">
              <dt>Dial</dt><dd><span className="mono">{q.number}</span></dd>
              <dt>Agents</dt><dd>{agents ? `${agents}, ${QUEUE_STRATEGY_LABELS[q.strategy].toLowerCase()}, ${q.member_timeout} s per attempt` : "None"}</dd>
              <dt>Callers hear</dt><dd>{QUEUE_MUSIC_LABELS[q.music]}{q.announcement_prompt_name ? ` after “${q.announcement_prompt_name}”` : ""}{q.periodic_prompt_name ? `, “${q.periodic_prompt_name}” every ${q.periodic_seconds} s` : ""}{q.announce_position ? `, their position every ${q.announce_frequency} s` : ""}</dd>
              <dt>Limits</dt><dd>{q.max_wait_seconds ? `${q.max_wait_seconds} s wait` : "Unlimited wait"}{q.max_callers ? `, ${q.max_callers} callers` : ""}{q.join_when_empty ? "" : ", no waiting without agents"}</dd>
              <dt>Then</dt><dd><DestinationLabel d={q.failover} /></dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Queue</dt><dd className="mono">{q.queue_name}</dd>
              <dt>Context</dt><dd className="mono">{q.context}</dd>
              <dt>Organization</dt><dd>{q.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(q.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(q.updated_at)}</dd>
              <dt>Queue ID</dt><dd className="mono">{q.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the queue "${q.name}"?`} confirmLabel="Delete queue" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes, menus, groups and queues that point at it must be changed first. The number stops working at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><QueueView /></Suspense>;
}
