// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { ConferenceFields, EMPTY_CONFERENCE, conferenceBody, conferenceDraft, conferenceValid, type ConferenceDraft } from "@/components/callflow/ConferenceFields";
import { ConferenceOwnersCard } from "@/components/conferences/ConferenceOwnersCard";
import { LiveConference } from "@/components/conferences/LiveConference";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { ConferenceRoom } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function ConferenceView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const item = useApiData<ConferenceRoom>(id ? `/conferences/${encodeURIComponent(id)}` : null);
  const editable = can("groups.write");
  const [draft, setDraft] = useState<ConferenceDraft>(EMPTY_CONFERENCE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(item.data, (c) => {
    if (c) setDraft(conferenceDraft(c));
  });

  if (!id) return <ErrorState title="No conference room selected" error={{ message: "Open a room from the list." }} />;
  if (item.error) return <ErrorState title="Could not load conference room" error={item.error} onRetry={item.reload} />;
  if (!item.data) return <LoadingState />;
  const c = item.data;
  const dirty = JSON.stringify(conferenceBody(draft)) !== JSON.stringify(conferenceBody(conferenceDraft(c)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      item.setData(await api.patch<ConferenceRoom>(`/conferences/${c.id}`, conferenceBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Conference room saved", "Deploy changes to apply it to the phone system.");
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
      await api.del(`/conferences/${c.id}`);
      toast.success(`Conference room "${c.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/conferences/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/conferences/", label: "Conference rooms" }}
        title={`${c.number} — ${c.name}`}
        description={
          <span className="row">
            <span>{c.organization_name}</span>
            <Badge tone={c.is_enabled ? "ok" : "neutral"}>{c.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {c.problems.length ? <Badge tone="warn" icon="alert">{c.problems.length} problem{c.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
            {c.in_use_by ? <Badge tone="outline">Used by {c.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {c.problems.length ? (
        <Callout tone="warn" title="Check this room's settings">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{c.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Room" subtitle={editable ? undefined : "You can view but not change this room."}>
          <form className="stack stack--sm" onSubmit={save}>
            <ConferenceFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={c.organization_id} current={c} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(conferenceDraft(c))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !conferenceValid(draft)}>Save</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <LiveConference roomId={c.id} editable={editable} />
          <ConferenceOwnersCard room={c} editable={editable} onSaved={item.setData} />
          <Card title="In the room" subtitle="Keys participants can press.">
            <dl className="dl">
              <dt>*1</dt><dd>Mute or unmute yourself</dd>
              <dt>*4 / *6</dt><dd>Listening volume down / up</dd>
              <dt>*7 / *9</dt><dd>Talking volume down / up</dd>
              <dt>*2</dt><dd>Administrator: lock or unlock the room</dd>
              <dt>*3</dt><dd>Administrator: drop the last participant who joined</dd>
              <dt>*8</dt><dd>Administrator: mute or unmute everyone else</dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{c.context}</dd>
              <dt>Hold music</dt><dd>{c.moh_class_name ?? "Default"}</dd>
              <dt>Organization</dt><dd>{c.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(c.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(c.updated_at)}</dd>
              <dt>Room ID</dt><dd className="mono">{c.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the conference room "${c.name}"?`} confirmLabel="Delete room" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes, menus, groups and announcements that point at it must be changed first. The room leaves the phone system at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ConferenceView /></Suspense>;
}
