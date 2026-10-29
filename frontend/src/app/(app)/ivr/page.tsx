// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { IvrMenu, Page, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function IvrPage() {
  const router = useRouter();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<IvrMenu>>("/ivr", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<IvrMenu>[] = [
    {
      key: "name",
      header: "Menu",
      render: (m) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{m.name}</span>
          <span className="table__secondary">{m.description ?? <span className="mono">{m.context}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (m: IvrMenu) => <span>{m.organization_name}</span> }] : []),
    { key: "prompt", header: "Prompt", render: (m) => m.prompt_name ? <span>{m.prompt_name}</span> : <Badge tone="danger" icon="alert">No prompt</Badge> },
    { key: "keys", header: "Keys", render: (m) => m.entries.length ? <span className="row" style={{ gap: 4 }}>{m.entries.map((e) => <span key={e.digit} className="kv-chip" title={e.destination.label ?? "missing"}>{e.digit}</span>)}{m.allow_direct_dial ? <span className="table__secondary">+ extensions</span> : null}</span> : <span className="subtle">{m.allow_direct_dial ? "Extensions only" : "None"}</span> },
    { key: "status", header: "Status", render: (m) => !m.is_enabled ? <Badge tone="neutral">Disabled</Badge> : m.problems.length ? <Badge tone="warn" icon="alert">{m.problems.length} problem{m.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok">Ready</Badge> },
    { key: "use", header: "Used by", render: (m) => m.in_use_by ? <span>{m.in_use_by} route{m.in_use_by === 1 ? "" : "s"} or menu{m.in_use_by === 1 ? "" : "s"}</span> : <span className="subtle">—</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="IVR menus"
        description="Auto-attendant menus: a prompt, keys that send callers to extensions, voicemail boxes or other menus, and what happens on timeouts and invalid keys. Point an inbound route at a menu to use it."
        actions={can("ivr.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New IVR menu</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or description" label="Search IVR menus" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(m) => m.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="IVR menus"
          onRowClick={(m) => router.push(`/ivr/view/?id=${m.id}`)}
          rowLabel={(m) => `Open IVR menu ${m.name}`}
          empty={<EmptyState icon="ivr" title={debounced || org ? "No matching menus" : "No IVR menus yet"}>{!debounced && !org && can("ivr.write") ? "Upload or record a prompt first, then create a menu and map its keys." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateMenuDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(m) => router.push(`/ivr/view/?id=${m.id}`)} />
    </div>
  );
}

function CreateMenuDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (m: IvrMenu) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const prompts = useApiData<Page<Prompt>>(open && effectiveOrg ? "/prompts" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setName("");
      setPrompt("");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<IvrMenu>("/ivr", { organization_id: effectiveOrg, name: name.trim(), prompt_id: prompt || null });
      toast.success(`IVR menu "${created.name}" created`, "Map its keys, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New IVR menu" description="Keys, fallbacks and the other settings are edited on the menu page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="ivr-create" loading={busy} disabled={!effectiveOrg || !name.trim()}>Create menu</Button></>}>
      <form id="ivr-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setPrompt(""); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Main menu" onChange={(e) => setName(e.target.value)} />
        <SelectField label="Menu prompt" disabled={!effectiveOrg} value={prompt} error={errors.fields.prompt_id}
          placeholder={!effectiveOrg ? "Choose an organization first" : prompts.loading ? "Loading prompts…" : (prompts.data?.items.length ?? 0) ? "Choose later" : "No prompts yet (Telephony → Audio)"}
          options={(prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setPrompt(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
