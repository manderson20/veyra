// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_IVR_MENU, IvrMenuFields, ivrMenuBody, ivrMenuDraft, ivrMenuValid, type IvrMenuDraft } from "@/components/ivr/IvrMenuFields";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { IvrMenu } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function IvrMenuView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const menu = useApiData<IvrMenu>(id ? `/ivr/${encodeURIComponent(id)}` : null);
  const editable = can("ivr.write");
  const [draft, setDraft] = useState<IvrMenuDraft>(EMPTY_IVR_MENU);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(menu.data, (m) => {
    if (m) setDraft(ivrMenuDraft(m));
  });

  if (!id) return <ErrorState title="No menu selected" error={{ message: "Open an IVR menu from the list." }} />;
  if (menu.error) return <ErrorState title="Could not load IVR menu" error={menu.error} onRetry={menu.reload} />;
  if (!menu.data) return <LoadingState />;
  const m = menu.data;
  const dirty = JSON.stringify(ivrMenuBody(draft)) !== JSON.stringify(ivrMenuBody(ivrMenuDraft(m)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      menu.setData(await api.patch<IvrMenu>(`/ivr/${m.id}`, ivrMenuBody(draft)));
      setChanged((n) => n + 1);
      toast.success("IVR menu saved", "Deploy changes to apply it to the phone system.");
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
      await api.del(`/ivr/${m.id}`);
      toast.success(`IVR menu "${m.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/ivr/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/ivr/", label: "IVR menus" }}
        title={m.name}
        description={
          <span className="row">
            <span>{m.organization_name}</span>
            <Badge tone={m.is_enabled ? "ok" : "neutral"}>{m.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {m.problems.length ? <Badge tone="warn" icon="alert">{m.problems.length} problem{m.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
            {m.in_use_by ? <Badge tone="outline">Used by {m.in_use_by}</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {m.problems.length ? (
        <Callout tone="warn" title="This menu will not work as configured">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{m.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Menu" subtitle={editable ? undefined : "You can view but not change this menu."}>
          <form className="stack stack--sm" onSubmit={save}>
            <IvrMenuFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={m.organization_id} current={m} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(ivrMenuDraft(m))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !ivrMenuValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="As deployed" subtitle="What the phone system does with this menu after the next deployment.">
            <dl className="dl">
              <dt>Prompt</dt><dd>{m.prompt_name ?? <Badge tone="danger">None</Badge>}</dd>
              {m.entries.map((e) => <><dt key={`k${e.digit}`}>Key {e.digit}</dt><dd key={`v${e.digit}`}><DestinationLabel d={e.destination} /></dd></>)}
              <dt>Extensions</dt><dd>{m.allow_direct_dial ? "Callers may dial an extension" : "Not dialable"}</dd>
              <dt>No key</dt><dd>{m.timeout_seconds} s wait, {m.max_retries} attempt{m.max_retries === 1 ? "" : "s"}, then <DestinationLabel d={m.timeout_destination} /></dd>
              <dt>Invalid key</dt><dd>{m.invalid_prompt_name ?? "Default prompt"}, {m.max_retries} attempt{m.max_retries === 1 ? "" : "s"}, then <DestinationLabel d={m.invalid_destination} /></dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{m.context}</dd>
              <dt>Organization</dt><dd>{m.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(m.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(m.updated_at)}</dd>
              <dt>Menu ID</dt><dd className="mono">{m.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the menu "${m.name}"?`} confirmLabel="Delete menu" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes and menus that point at it must be changed first. The menu leaves the phone system at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><IvrMenuView /></Suspense>;
}
