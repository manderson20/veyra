// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { EMPTY_INBOUND_ROUTE, InboundRouteFields, inboundRouteBody, inboundRouteDraft, inboundRouteValid, type InboundRouteDraft } from "@/components/routing/InboundRouteFields";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { InboundRoute } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function InboundRouteView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const route = useApiData<InboundRoute>(id ? `/routing/inbound/${encodeURIComponent(id)}` : null);
  const editable = can("routing.write");
  const [draft, setDraft] = useState<InboundRouteDraft>(EMPTY_INBOUND_ROUTE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(route.data, (r) => {
    if (r) setDraft(inboundRouteDraft(r));
  });

  if (!id) return <ErrorState title="No route selected" error={{ message: "Open an inbound route from the list." }} />;
  if (route.error) return <ErrorState title="Could not load inbound route" error={route.error} onRetry={route.reload} />;
  if (!route.data) return <LoadingState />;
  const r = route.data;
  const dirty = JSON.stringify(inboundRouteBody(draft)) !== JSON.stringify(inboundRouteBody(inboundRouteDraft(r)));
  const didLabel = r.did === "any" ? "Any number" : r.did;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      route.setData(await api.patch<InboundRoute>(`/routing/inbound/${r.id}`, inboundRouteBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Inbound route saved", "If the engine configuration changed, Deploy changes appears in the top bar.");
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
      await api.del(`/routing/inbound/${r.id}`);
      toast.success(`Inbound route for ${didLabel} deleted`, "Deploy the configuration to remove it from the engine.");
      router.push("/routing/inbound/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/routing/inbound/", label: "Inbound routes" }}
        title={<span className="mono">{didLabel}</span>}
        description={
          <span className="row">
            <span>{r.organization_name}</span>
            <Badge tone={r.is_enabled ? "ok" : "neutral"}>{r.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {r.destination_missing ? <Badge tone="danger" icon="alert">No destination</Badge> : null}
            {r.trunk_name ? <Badge tone="outline" icon="trunk">{r.trunk_name}</Badge> : <Badge tone="outline">Any trunk</Badge>}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {r.destination_missing ? <Callout tone="danger" title="This route has no working destination">The destination it pointed to no longer exists or is disabled. Calls to {didLabel} are rejected until a new destination is chosen.</Callout> : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Route" subtitle={editable ? undefined : "You can view but not change this route."}>
          <form className="stack stack--sm" onSubmit={save}>
            <InboundRouteFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={r.organization_id} current={r} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(inboundRouteDraft(r))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !inboundRouteValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <Card title="Information">
          <dl className="dl">
            <dt>Matches</dt><dd><span className="mono">{r.did_canonical}</span>{r.aliases.length ? <span className="subtle" style={{ display: "block" }}>also {r.aliases.join(", ")}</span> : null}</dd>
            <dt>Destination</dt><dd><DestinationLabel d={r.destination} /></dd>
            {r.time_condition_name ? <><dt>Time condition</dt><dd>{r.time_condition_name}</dd><dt>After hours</dt><dd><DestinationLabel d={r.after_hours} /></dd></> : null}
            <dt>Organization</dt><dd>{r.organization_name}</dd>
            <dt>Created</dt><dd>{formatDateTime(r.created_at)}</dd>
            <dt>Updated</dt><dd>{formatRelative(r.updated_at)}</dd>
            <dt>Route ID</dt><dd className="mono">{r.id}</dd>
          </dl>
        </Card>
      </div>
      <ConfirmDialog
        open={deleting}
        title={`Delete the route for ${didLabel}?`}
        confirmLabel="Delete route"
        tone="danger"
        busy={deleteBusy}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => { setDeleting(false); setDeleteError(null); }}
      >
        <p>Calls to <span className="mono">{didLabel}</span> will no longer be answered after the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><InboundRouteView /></Suspense>;
}
