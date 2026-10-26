// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_RING_GROUP, RING_STRATEGY_LABELS, RingGroupFields, ringGroupBody, ringGroupDraft, ringGroupValid, type RingGroupDraft } from "@/components/groups/RingGroupFields";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { RingGroup } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function RingGroupView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const group = useApiData<RingGroup>(id ? `/ring-groups/${encodeURIComponent(id)}` : null);
  const editable = can("groups.write");
  const [draft, setDraft] = useState<RingGroupDraft>(EMPTY_RING_GROUP);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(group.data, (g) => {
    if (g) setDraft(ringGroupDraft(g));
  });

  if (!id) return <ErrorState title="No ring group selected" error={{ message: "Open a ring group from the list." }} />;
  if (group.error) return <ErrorState title="Could not load ring group" error={group.error} onRetry={group.reload} />;
  if (!group.data) return <LoadingState />;
  const g = group.data;
  const dirty = JSON.stringify(ringGroupBody(draft)) !== JSON.stringify(ringGroupBody(ringGroupDraft(g)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      group.setData(await api.patch<RingGroup>(`/ring-groups/${g.id}`, ringGroupBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Ring group saved", "Deploy changes to apply it to the phone system.");
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
      await api.del(`/ring-groups/${g.id}`);
      toast.success(`Ring group "${g.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/ring-groups/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/ring-groups/", label: "Ring groups" }}
        title={<span className="row"><span className="mono">{g.number}</span><span>{g.name}</span></span>}
        description={
          <span className="row">
            <span>{g.organization_name}</span>
            <Badge tone={g.is_enabled ? "ok" : "neutral"}>{g.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {g.problems.length ? <Badge tone="warn" icon="alert">{g.problems.length} problem{g.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
            {g.in_use_by ? <Badge tone="outline">Used by {g.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {g.problems.length ? (
        <Callout tone="warn" title="This group will not work as configured">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{g.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Ring group" subtitle={editable ? undefined : "You can view but not change this group."}>
          <form className="stack stack--sm" onSubmit={save}>
            <RingGroupFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={g.organization_id} current={g} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(ringGroupDraft(g))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !ringGroupValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="As deployed" subtitle="What the phone system does with this group after the next deployment.">
            <dl className="dl">
              <dt>Dial</dt><dd><span className="mono">{g.number}</span>{g.caller_id_prefix ? <> (phones show “{g.caller_id_prefix}” before the caller)</> : null}</dd>
              <dt>Rings</dt><dd>{g.members.length ? `${g.members.length} phone${g.members.length === 1 ? "" : "s"}, ${RING_STRATEGY_LABELS[g.strategy].toLowerCase()}, ${g.ring_seconds} s${g.strategy !== "ringall" ? " each" : ""}` : "Nobody"}</dd>
              <dt>Busy members</dt><dd>{g.ring_busy_members ? "Rung anyway (call waiting)" : "Skipped"}</dd>
              <dt>If unanswered</dt><dd><DestinationLabel d={g.failover} /></dd>
              <dt>Pickup</dt><dd><span className="mono">**{g.number}</span> is not needed: pick up the ringing member phone with <span className="mono">**</span>its number or <span className="mono">*8</span></dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{g.context}</dd>
              <dt>Organization</dt><dd>{g.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(g.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(g.updated_at)}</dd>
              <dt>Group ID</dt><dd className="mono">{g.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the ring group "${g.name}"?`} confirmLabel="Delete group" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes, menus, groups and queues that point at it must be changed first. The number stops working at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><RingGroupView /></Suspense>;
}
