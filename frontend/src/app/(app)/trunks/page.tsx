// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_TRUNK, TrunkEssentialFields, TrunkModeBadge, TrunkStatusBadge, trunkBody, type TrunkDraft } from "@/components/routing/TrunkFields";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, SearchInput, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { Trunk, TrunkPage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

export default function TrunksPage() {
  const router = useRouter();
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<TrunkPage>("/trunks", { q: debounced });
  const reload = list.reload;
  useEffect(() => {
    // live reachability
    const t = window.setInterval(reload, 15_000);
    return () => window.clearInterval(t);
  }, [reload]);

  const columns: Column<Trunk>[] = [
    {
      key: "name",
      header: "Trunk",
      render: (t) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{t.name}</span>
          {t.description ? <span className="table__secondary">{t.description}</span> : null}
        </span>
      ),
    },
    {
      key: "host",
      header: "Host",
      render: (t) => <span><span className="mono">{t.host}:{t.port}</span> <span className="table__secondary">{t.transport.toUpperCase()}</span></span>,
    },
    { key: "mode", header: "Mode", render: (t) => <TrunkModeBadge mode={t.auth_mode} /> },
    { key: "status", header: "Status", render: (t) => <TrunkStatusBadge trunk={t} /> },
    { key: "enabled", header: "Enabled", render: (t) => <Badge tone={t.is_enabled ? "ok" : "neutral"}>{t.is_enabled ? "Enabled" : "Disabled"}</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="SIP trunks"
        description="Connections to carriers. Outbound routes send calls over trunks; inbound routes answer the numbers carriers deliver on them."
        actions={can("trunks.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New trunk</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or host" label="Search trunks" />
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(t) => t.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="SIP trunks"
          onRowClick={(t) => router.push(`/trunks/view/?id=${t.id}`)}
          rowLabel={(t) => `Open trunk ${t.name}`}
          empty={<EmptyState icon="trunk" title={debounced ? "No matching trunks" : "No trunks yet"}>{!debounced && can("trunks.write") ? "Add the first trunk, then create outbound and inbound routes that use it." : null}</EmptyState>}
          pagination={list.data ? <div className="pagination"><span>{list.data.total} {list.data.total === 1 ? "trunk" : "trunks"}</span></div> : null}
        />
      </Card>
      <CreateTrunkDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(t) => router.push(`/trunks/view/?id=${t.id}`)} />
    </div>
  );
}

function CreateTrunkDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (t: Trunk) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [draft, setDraft] = useState<TrunkDraft>(EMPTY_TRUNK);
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setDraft(EMPTY_TRUNK);
      errors.clear();
    }
  });
  const registration = draft.auth_mode === "registration";
  const valid = draft.name.trim() && draft.host.trim() && draft.port && (!registration || (draft.username.trim() && draft.password));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<Trunk>("/trunks", trunkBody(draft));
      toast.success(`Trunk ${created.name} created`, "Add it to an outbound route, then deploy the configuration.");
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
      title="New trunk"
      description="The essentials to connect to a carrier. Codecs, caller ID handling and other options can be set afterwards."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="trunk-create" loading={busy} disabled={!valid}>Create trunk</Button></>}
    >
      <form id="trunk-create" className="stack stack--sm" onSubmit={submit}>
        <TrunkEssentialFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
