// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import type { Announcement, Page, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function AnnouncementsPage() {
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

  const list = useApiData<Page<Announcement>>("/announcements", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<Announcement>[] = [
    {
      key: "name",
      header: "Announcement",
      render: (a) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{a.name}</span>
          <span className="table__secondary">{a.description ?? <span className="mono">{a.context}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (a: Announcement) => <span>{a.organization_name}</span> }] : []),
    { key: "prompt", header: "Recording", render: (a) => a.prompt_name ? <span>{a.prompt_name}</span> : <Badge tone="danger" icon="alert">No recording</Badge> },
    { key: "then", header: "Then", render: (a) => <DestinationLabel d={a.destination} /> },
    { key: "status", header: "Status", render: (a) => !a.is_enabled ? <Badge tone="neutral">Disabled</Badge> : a.problems.length ? <Badge tone="warn" icon="alert">{a.problems.length} problem{a.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge> },
    { key: "use", header: "Used by", render: (a) => a.in_use_by ? <span>{a.in_use_by}</span> : <span className="subtle">—</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Announcements"
        description="Play a recording, then send the call on: a closure notice before the main menu, a disclaimer before a queue, directions before an extension. Point a route, menu key, group or queue at an announcement."
        actions={can("ivr.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New announcement</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or description" label="Search announcements" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(a) => a.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Announcements"
          onRowClick={(a) => router.push(`/announcements/view/?id=${a.id}`)}
          rowLabel={(a) => `Open announcement ${a.name}`}
          empty={<EmptyState icon="play" title={debounced || org ? "No matching announcements" : "No announcements yet"}>{!debounced && !org && can("ivr.write") ? "Upload or record the audio first (Telephony → Audio), then create an announcement and choose where the call goes afterwards." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateAnnouncementDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(a) => router.push(`/announcements/view/?id=${a.id}`)} />
    </div>
  );
}

function CreateAnnouncementDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (a: Announcement) => void }) {
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
      const created = await api.post<Announcement>("/announcements", { organization_id: effectiveOrg, name: name.trim(), prompt_id: prompt || null });
      toast.success(`Announcement "${created.name}" created`, "Choose where the call goes afterwards, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="New announcement" description="The destination and the key options are edited on the announcement page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="ann-create" loading={busy} disabled={!effectiveOrg || !name.trim()}>Create announcement</Button></>}>
      <form id="ann-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setPrompt(""); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Closed for the holiday" onChange={(e) => setName(e.target.value)} />
        <SelectField label="Recording to play" disabled={!effectiveOrg} value={prompt} error={errors.fields.prompt_id}
          placeholder={!effectiveOrg ? "Choose an organization first" : prompts.loading ? "Loading recordings…" : (prompts.data?.items.length ?? 0) ? "Choose later" : "No recordings yet (Telephony → Audio)"}
          options={(prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setPrompt(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
