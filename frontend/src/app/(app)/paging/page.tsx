// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { PageDialog, PRIORITY_LABELS } from "@/components/paging/PageDialog";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Page, PageLogEntry, PageSendResult, PagingPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function PagingPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<PagingPage | undefined>();
  const [deleting, setDeleting] = useState<PagingPage | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<PagingPage>>("/pages", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const log = useApiData<Page<PageLogEntry>>("/pages/log", { organization_id: org || undefined, limit: 10 });
  const editable = can("paging.write");
  const canSend = can("paging.send");
  const manyOrgs = organizations.length > 1;
  const saved = () => { list.reload(); setChanged((n) => n + 1); };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/pages/${deleting.id}`);
      toast.success(`Page "${deleting.name}" deleted`, "Deploy the configuration to remove its number from the phones.");
      setDeleting(undefined);
      saved();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const send = async (p: PagingPage) => {
    setSending(p.id);
    try {
      const r = await api.post<PageSendResult>(`/pages/${p.id}/send`, {});
      if (r.started) toast.success(r.message, "The recording plays into the zones now.");
      else toast.error("Not started", r.message);
      list.reload();
      log.reload();
    } catch (err) {
      toast.error("Not started", errorMessage(err));
    } finally {
      setSending(null);
    }
  };
  const columns: Column<PagingPage>[] = [
    { key: "name", header: "Page", render: (p) => <span><span className="table__primary" style={{ display: "block" }}>{p.name}</span><span className="table__secondary">{p.description ?? (p.audio ? `Recording: ${p.audio.name}` : "Live audio")}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (p: PagingPage) => <span>{p.organization_name}</span> }] : []),
    { key: "number", header: "Dial", render: (p) => p.number ? <span className="mono">{p.number}</span> : <span className="subtle">—</span> },
    { key: "zones", header: "Zones", render: (p) => p.zones.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{p.zones.map((z) => <span key={z.id} className="kv-chip" title={`Group ${z.poly_group}`}>{z.name}</span>)}</span> : <span className="subtle">None</span> },
    { key: "priority", header: "Priority", render: (p) => <span>{PRIORITY_LABELS[p.priority].split(" ")[0]}</span> },
    { key: "last", header: "Last sent", render: (p) => p.last_sent_at ? formatRelative(p.last_sent_at) : <span className="subtle">Never</span> },
    { key: "status", header: "Status", render: (p) => !p.is_enabled ? <Badge tone="neutral">Disabled</Badge> : p.problems.length ? <Badge tone="warn" icon="alert">{p.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
    { key: "actions", header: "", render: (p) => (
      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
        {canSend && p.audio ? <Button size="sm" variant="primary" icon="megaphone" loading={sending === p.id} onClick={(e) => { e.stopPropagation(); void send(p); }}>Send now</Button> : null}
        {editable ? <Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(p); }}>Edit</Button> : null}
        {editable ? <Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(p); }} aria-label={`Delete ${p.name}`} /> : null}
      </span>
    ) },
  ];

  return (
    <div className="stack">
      <PageHeader title="Pages"
        description="A page sends audio into paging zones: live from a phone that dials its number, or a recording started here, by a bell schedule or by another system through the API."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New page</Button> : null} />
      <PendingChanges refreshKey={changed} />
      <Callout tone="neutral">
        Zones are configured under Paging Zones. Dialling a zone&apos;s own number pages it live; pages combine zones and can carry a recording. Phones and speakers hear the same page together through the page sender.
      </Callout>
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name, description or number" label="Search pages" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Pages"
          onRowClick={editable ? (p) => setEditing(p) : undefined} rowLabel={(p) => `Edit page ${p.name}`}
          empty={<EmptyState icon="megaphone" title={debounced || org ? "No matching pages" : "No pages yet"}>{!debounced && !org && editable ? "Create a page over one or more zones; give it a recording to start it from here, a bell or the API." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      </Card>
      <Card title="Recent pages" subtitle="Started from phones, the interface, bells or the API." flush>
        {log.data && log.data.items.length === 0 ? <div style={{ padding: 16 }}><p className="muted">Nothing sent yet.</p></div> : (
          <ul className="list-plain">
            {(log.data?.items ?? []).map((e) => (
              <li key={e.id} className="list-row">
                <span style={{ minWidth: 0 }}><span>{e.page_name}</span><span className="subtle" style={{ display: "block" }}>{e.zones.join(", ") || "no zones"} · {e.trigger}{e.actor ? ` · ${e.actor}` : ""}</span></span>
                <span className="row" style={{ flexWrap: "nowrap" }}><Badge tone={e.outcome === "started" ? "ok" : "danger"}>{e.outcome}</Badge><span className="subtle nowrap">{formatRelative(e.at)}</span></span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <PageDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={saved} />
      <PageDialog open={!!editing} page={editing} onClose={() => setEditing(undefined)} onSaved={saved} />
      <ConfirmDialog open={!!deleting} title={`Delete the page "${deleting?.name ?? ""}"?`} confirmLabel="Delete page" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Bell schedules that use this page stop ringing it.</p>
      </ConfirmDialog>
    </div>
  );
}
