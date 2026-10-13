// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_OUTBOUND_ROUTE, OutboundRouteFields, outboundRouteBody, outboundRouteDraft, outboundRouteValid, type OutboundRouteDraft } from "@/components/routing/OutboundRouteFields";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { OutboundRoute, TrunkPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function OutboundRouteView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const route = useApiData<OutboundRoute>(id ? `/routing/outbound/${encodeURIComponent(id)}` : null);
  const editable = can("trunks.write");
  const trunks = useApiData<TrunkPage>(editable ? "/trunks" : null);
  const [draft, setDraft] = useState<OutboundRouteDraft>(EMPTY_OUTBOUND_ROUTE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(route.data, (r) => {
    if (r) setDraft(outboundRouteDraft(r));
  });

  if (!id) return <ErrorState title="No route selected" error={{ message: "Open an outbound route from the list." }} />;
  if (route.error) return <ErrorState title="Could not load outbound route" error={route.error} onRetry={route.reload} />;
  if (!route.data) return <LoadingState />;
  const r = route.data;
  const dirty = JSON.stringify(outboundRouteBody(draft)) !== JSON.stringify(outboundRouteBody(outboundRouteDraft(r)));
  // Without trunk listing rights, the picker shows the trunks already on the route.
  const trunkOptions = trunks.data?.items ?? r.trunks;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      route.setData(await api.patch<OutboundRoute>(`/routing/outbound/${r.id}`, outboundRouteBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Outbound route saved", "If the engine configuration changed, Deploy changes appears in the top bar.");
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
      await api.del(`/routing/outbound/${r.id}`);
      toast.success(`Route ${r.name} deleted`, "Deploy the configuration to remove it from the engine.");
      router.push("/routing/outbound/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/routing/outbound/", label: "Outbound routes" }}
        title={r.name}
        description={
          <span className="row">
            <Badge tone={r.is_enabled ? "ok" : "neutral"}>{r.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {r.is_emergency ? <Badge tone="danger">Emergency</Badge> : null}
            <span className="subtle">Position {r.position}</span>
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Route" subtitle={editable ? undefined : "You can view but not change this route."}>
          <form className="stack stack--sm" onSubmit={save}>
            <OutboundRouteFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} trunks={trunkOptions} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(outboundRouteDraft(r))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !outboundRouteValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <Card title="Information">
          <dl className="dl">
            <dt>Engine patterns</dt><dd>{r.examples.length ? r.examples.map((x) => <span key={x} className="mono" style={{ display: "block" }}>{x}</span>) : <span className="subtle">—</span>}</dd>
            <dt>Trunks</dt><dd>{r.trunks.length ? <ol style={{ margin: 0, paddingLeft: 18 }}>{r.trunks.map((t) => <li key={t.id}>{t.name}{t.is_enabled ? "" : <span className="subtle"> (disabled)</span>}</li>)}</ol> : <Badge tone="danger">None</Badge>}</dd>
            <dt>Engine name</dt><dd className="mono">{r.slug}</dd>
            <dt>Created</dt><dd>{formatDateTime(r.created_at)}</dd>
            <dt>Updated</dt><dd>{formatRelative(r.updated_at)}</dd>
            <dt>Route ID</dt><dd className="mono">{r.id}</dd>
          </dl>
        </Card>
      </div>
      <ConfirmDialog
        open={deleting}
        title={`Delete route ${r.name}?`}
        confirmLabel="Delete route"
        tone="danger"
        busy={deleteBusy}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => { setDeleting(false); setDeleteError(null); }}
      >
        <p>Numbers matching <span className="mono">{r.examples.join(", ")}</span> will no longer be routed by this route after the next deployment{r.is_emergency ? "; make sure another emergency route exists" : ""}.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><OutboundRouteView /></Suspense>;
}
