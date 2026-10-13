// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_OUTBOUND_ROUTE, OutboundRouteFields, outboundRouteBody, outboundRouteValid, type OutboundRouteDraft } from "@/components/routing/OutboundRouteFields";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, IconButton, PageHeader, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { moveItem } from "@/lib/routing";
import type { OutboundRoute, OutboundRoutes, TrunkPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function RouteTrunks({ route }: { route: OutboundRoute }) {
  if (route.trunks.length === 0) return <Badge tone="danger" icon="alert">No trunks</Badge>;
  return (
    <span className="row" style={{ gap: 4 }}>
      {route.trunks.map((t, i) => (
        <span key={t.id} className="row" style={{ gap: 4 }}>
          {i > 0 ? <span className="subtle" aria-label="then">→</span> : null}
          <span className={t.is_enabled ? undefined : "subtle"} style={t.is_enabled ? undefined : { textDecoration: "line-through" }}>{t.name}</span>
        </span>
      ))}
    </span>
  );
}

export default function OutboundRoutesPage() {
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const list = useApiData<OutboundRoutes>("/routing/outbound");
  const [createOpen, setCreateOpen] = useState(false);
  const [moving, setMoving] = useState(false);
  const editable = can("trunks.write");
  const items = list.data?.items ?? [];

  const move = async (index: number, delta: -1 | 1) => {
    const target = index + delta;
    const a = items[index];
    const b = items[target];
    if (!a || !b || a.is_emergency !== b.is_emergency) return;
    setMoving(true);
    try {
      list.setData(await api.put<OutboundRoutes>("/routing/outbound/order", { ids: moveItem(items, index, target).map((r) => r.id) }));
    } catch (err) {
      toast.error("Could not reorder routes", errorMessage(err));
    } finally {
      setMoving(false);
    }
  };

  const columns: Column<OutboundRoute>[] = [
    {
      key: "order",
      header: "Order",
      width: "96px",
      render: (r) => {
        const i = items.indexOf(r);
        const prev = items[i - 1];
        const next = items[i + 1];
        return (
          <span className="row" style={{ gap: 2 }} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            <span className="mono" style={{ minWidth: 20 }}>{i + 1}</span>
            {editable ? (
              <>
                <IconButton size="sm" icon="chevronUp" label={`Move ${r.name} up`} disabled={moving || !prev || prev.is_emergency !== r.is_emergency} onClick={() => void move(i, -1)} />
                <IconButton size="sm" icon="chevronDown" label={`Move ${r.name} down`} disabled={moving || !next || next.is_emergency !== r.is_emergency} onClick={() => void move(i, 1)} />
              </>
            ) : null}
          </span>
        );
      },
    },
    {
      key: "name",
      header: "Route",
      render: (r) => (
        <span className="row">
          <span className="table__primary">{r.name}</span>
          {r.is_emergency ? <Badge tone="danger">Emergency</Badge> : null}
        </span>
      ),
    },
    { key: "patterns", header: "Patterns", render: (r) => <span className="mono">{r.examples.join(", ")}</span> },
    { key: "trunks", header: "Trunks", render: (r) => <RouteTrunks route={r} /> },
    { key: "cid", header: "Caller ID", render: (r) => r.caller_id_number ? <span className="mono">{r.caller_id_number}</span> : <span className="subtle">From the extension</span> },
    { key: "enabled", header: "Enabled", render: (r) => <Badge tone={r.is_enabled ? "ok" : "neutral"}>{r.is_enabled ? "Enabled" : "Disabled"}</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Outbound routes"
        description="How dialled numbers reach carriers. Routes are tried in this order; the first whose pattern matches wins, and its trunks are tried in failover order. Emergency routes always come first."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New outbound route</Button> : null}
      />
      <PendingChanges refreshKey={list.data} />
      {list.data?.warnings.length ? (
        <Callout tone="warn" title="Check these routes">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{list.data.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Callout>
      ) : null}
      <Card flush>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(r) => r.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Outbound routes in evaluation order"
          onRowClick={(r) => router.push(`/routing/outbound/view/?id=${r.id}`)}
          rowLabel={(r) => `Open outbound route ${r.name}`}
          empty={<EmptyState icon="arrowOut" title="No outbound routes yet">{editable ? "Without routes, phones can only call other extensions. Create an emergency route first, then routes for local and long-distance numbers." : null}</EmptyState>}
        />
      </Card>
      <CreateOutboundRouteDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={() => list.reload()} />
    </div>
  );
}

function CreateOutboundRouteDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (r: OutboundRoute) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const trunks = useApiData<TrunkPage>(open ? "/trunks" : null);
  const [draft, setDraft] = useState<OutboundRouteDraft>(EMPTY_OUTBOUND_ROUTE);
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setDraft({ ...EMPTY_OUTBOUND_ROUTE, patterns: EMPTY_OUTBOUND_ROUTE.patterns.map((p) => ({ ...p })), trunk_ids: [] });
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<OutboundRoute>("/routing/outbound", outboundRouteBody(draft));
      toast.success(`Route ${created.name} created`, "It was added at the end of its group. Deploy the configuration so calls use it.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      size="lg"
      title="New outbound route"
      description="Numbers matching one of the patterns are sent to the trunks in order."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="outbound-create" loading={busy} disabled={!outboundRouteValid(draft)}>Create route</Button></>}
    >
      <form id="outbound-create" className="stack stack--sm" onSubmit={submit}>
        {trunks.data && trunks.data.items.length === 0 ? <Callout tone="warn">There are no trunks yet. Create a trunk first; a route needs at least one.</Callout> : null}
        <OutboundRouteFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} trunks={trunks.data?.items ?? []} autoFocus />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
