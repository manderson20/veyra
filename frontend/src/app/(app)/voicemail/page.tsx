// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { VoicemailBoxDialog } from "@/components/voicemail/VoicemailBoxDialog";
import { VoicemailBoxPanel } from "@/components/voicemail/VoicemailBoxPanel";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, type Column } from "@/components/ui";
import type { Page, VoicemailBox } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function VoicemailPage() {
  const { can, session } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [createShared, setCreateShared] = useState(false);
  const [editing, setEditing] = useState<VoicemailBox | null>(null);
  const [changed, setChanged] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<VoicemailBox>>("/voicemail", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const editable = can("voicemail.write");
  const canRead = can("voicemail.read");
  const [messagesFor, setMessagesFor] = useState<VoicemailBox | null>(null);
  const deliveryOff = list.data?.items.length ? !list.data.items[0]!.email_delivery_enabled : false;
  const createOrg = org || (organizations.length === 1 ? organizations[0]!.id : session?.user.home_organization_id ?? "");

  const columns: Column<VoicemailBox>[] = [
    {
      key: "ext",
      header: "Number",
      render: (b) => (
        <span>
          <span className="table__primary mono" style={{ display: "block" }}>{b.number}</span>
          <span className="table__secondary">{b.name}{b.user_display_name ? ` · ${b.user_display_name}` : ""}</span>
        </span>
      ),
    },
    {
      key: "kind",
      header: "Kind",
      render: (b) => b.shared
        ? <span><Badge tone="info">Shared</Badge>{b.members.length ? <span className="table__secondary" style={{ display: "block" }}>{b.members.length} member phone{b.members.length === 1 ? "" : "s"}</span> : null}</span>
        : <span className="subtle">Extension</span>,
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (b: VoicemailBox) => <span>{b.organization_name}</span> }] : []),
    { key: "email", header: "Email", render: (b) => b.email ? <span>{b.email}{b.delete_after_email ? <span className="table__secondary" style={{ display: "block" }}>deleted after sending</span> : null}</span> : <span className="subtle">No email</span> },
    { key: "ring", header: "Rings for", render: (b) => <span>{b.ring_seconds} s</span> },
    { key: "use", header: "Used by", render: (b) => b.in_use_by ? <span>{b.in_use_by} route{b.in_use_by === 1 ? "" : "s"} or key{b.in_use_by === 1 ? "" : "s"}</span> : <span className="subtle">—</span> },
    { key: "enabled", header: "Enabled", render: (b) => <Badge tone={b.is_enabled ? "ok" : "neutral"}>{b.is_enabled ? "Enabled" : "Disabled"}</Badge> },
    ...(canRead ? [{ key: "messages", header: "", render: (b: VoicemailBox) => <Button size="sm" icon="voicemail" onClick={(e) => { e.stopPropagation(); setMessagesFor(b); }}>Messages</Button> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Voicemail"
        description="One box per extension, plus shared inboxes with their own number that several phones watch: a PIN, the ring time before voicemail answers, and email delivery of new messages. Users record their greeting and listen to messages with *97 from the phone."
        actions={editable ? (
          <>
            <Button icon="plus" onClick={() => setCreateShared(true)}>New shared inbox</Button>
            <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New voicemail box</Button>
          </>
        ) : null}
      />
      <PendingChanges refreshKey={changed + (list.data?.total ?? 0)} />
      {deliveryOff && can("system.settings.read") ? <Callout tone="warn" title="Email delivery is not configured">Messages stay in the boxes and no email is sent until an SMTP server is set up under Settings → Email delivery.</Callout> : null}
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by number, name or email" label="Search voicemail boxes" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(b) => b.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Voicemail boxes"
          onRowClick={editable ? (b) => setEditing(b) : undefined}
          rowLabel={(b) => b.shared ? `Edit the shared inbox ${b.name}` : `Edit the voicemail box of ${b.extension_number}`}
          empty={<EmptyState icon="voicemail" title={debounced || org ? "No matching voicemail boxes" : "No voicemail boxes yet"}>{!debounced && !org && editable ? "Create a box for an extension, give the user the PIN, then deploy the configuration." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <VoicemailBoxDialog open={createOpen} onClose={() => setCreateOpen(false)} organizationId={createOrg} onSaved={() => { list.reload(); setChanged((n) => n + 1); }} />
      <VoicemailBoxDialog open={createShared} shared onClose={() => setCreateShared(false)} organizationId={createOrg} onSaved={() => { list.reload(); setChanged((n) => n + 1); }} />
      <VoicemailBoxDialog open={editing !== null} onClose={() => setEditing(null)} box={editing ?? undefined} onSaved={() => { list.reload(); setChanged((n) => n + 1); }} />
      <Dialog open={messagesFor !== null} onClose={() => setMessagesFor(null)} size="lg"
        title={messagesFor ? (messagesFor.shared ? `Messages of ${messagesFor.name}` : `Messages of ${messagesFor.extension_number} ${messagesFor.extension_name}`) : ""}
        description="What the user hears with *97: messages and greetings. Listening and every change are written to the audit log.">
        {messagesFor ? (
          <VoicemailBoxPanel base={`/voicemail/${messagesFor.id}`} idBase={`vm-admin-${messagesFor.id}`} editable={editable}
            targets={(list.data?.items ?? []).filter((b) => b.id !== messagesFor.id && b.organization_id === messagesFor.organization_id).map((b) => ({ id: b.id, label: b.shared ? `${b.number} ${b.name}` : `${b.extension_number} ${b.extension_name}` }))} />
        ) : null}
      </Dialog>
    </div>
  );
}
