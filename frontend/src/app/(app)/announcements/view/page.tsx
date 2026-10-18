// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { AnnouncementFields, EMPTY_ANNOUNCEMENT, announcementBody, announcementDraft, announcementValid, type AnnouncementDraft } from "@/components/callflow/AnnouncementFields";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { Announcement } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function AnnouncementView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const item = useApiData<Announcement>(id ? `/announcements/${encodeURIComponent(id)}` : null);
  const editable = can("ivr.write");
  const [draft, setDraft] = useState<AnnouncementDraft>(EMPTY_ANNOUNCEMENT);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(item.data, (a) => {
    if (a) setDraft(announcementDraft(a));
  });

  if (!id) return <ErrorState title="No announcement selected" error={{ message: "Open an announcement from the list." }} />;
  if (item.error) return <ErrorState title="Could not load announcement" error={item.error} onRetry={item.reload} />;
  if (!item.data) return <LoadingState />;
  const a = item.data;
  const dirty = JSON.stringify(announcementBody(draft)) !== JSON.stringify(announcementBody(announcementDraft(a)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      item.setData(await api.patch<Announcement>(`/announcements/${a.id}`, announcementBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Announcement saved", "Deploy changes to apply it to the phone system.");
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
      await api.del(`/announcements/${a.id}`);
      toast.success(`Announcement "${a.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/announcements/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/announcements/", label: "Announcements" }}
        title={a.name}
        description={
          <span className="row">
            <span>{a.organization_name}</span>
            <Badge tone={a.is_enabled ? "ok" : "neutral"}>{a.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {a.problems.length ? <Badge tone="warn" icon="alert">{a.problems.length} problem{a.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
            {a.in_use_by ? <Badge tone="outline">Used by {a.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {a.problems.length ? (
        <Callout tone="warn" title="This announcement will not work as configured">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{a.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Announcement" subtitle={editable ? undefined : "You can view but not change this announcement."}>
          <form className="stack stack--sm" onSubmit={save}>
            <AnnouncementFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={a.organization_id} current={a} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(announcementDraft(a))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !announcementValid(draft)}>Save</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="As deployed" subtitle="What the phone system does with this announcement after the next deployment.">
            <dl className="dl">
              <dt>Recording</dt><dd>{a.prompt_name ?? <Badge tone="danger">None</Badge>}</dd>
              <dt>Keys</dt><dd>{a.allow_skip ? "Any key skips" : "Plays to the end"}{a.repeat_key ? `; ${a.repeat_key} replays` : ""}</dd>
              <dt>Then</dt><dd><DestinationLabel d={a.destination} /></dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{a.context}</dd>
              <dt>Organization</dt><dd>{a.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(a.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(a.updated_at)}</dd>
              <dt>Announcement ID</dt><dd className="mono">{a.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the announcement "${a.name}"?`} confirmLabel="Delete announcement" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes, menus, groups and announcements that point at it must be changed first. It leaves the phone system at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><AnnouncementView /></Suspense>;
}
