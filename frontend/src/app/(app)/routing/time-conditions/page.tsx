// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_TIME_CONDITION, TimeConditionFields, timeConditionBody, timeConditionValid, type TimeConditionDraft } from "@/components/routing/TimeConditionFields";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import { summarizeRanges } from "@/lib/routing";
import type { Page, TimeCondition } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function TimeConditionsPage() {
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

  const list = useApiData<Page<TimeCondition>>("/routing/time-conditions", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<TimeCondition>[] = [
    {
      key: "name",
      header: "Name",
      render: (t) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{t.name}</span>
          {t.description ? <span className="table__secondary">{t.description}</span> : null}
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (t: TimeCondition) => <span>{t.organization_name}</span> }] : []),
    { key: "tz", header: "Time zone", render: (t) => <span className="mono">{t.timezone}</span> },
    { key: "open", header: "Now", render: (t) => <span className="row" style={{ gap: 4 }}><Badge tone={t.effective_open ? "ok" : "neutral"} icon={t.effective_open ? "checkCircle" : "clock"}>{t.effective_open ? "Open now" : "Closed now"}</Badge>{t.override ? <Badge tone="warn" icon="alert">Forced{t.override_temporary ? "" : " (permanent)"}</Badge> : null}{t.code ? <span className="mono subtle">{t.code}</span> : null}</span> },
    {
      key: "ranges",
      header: "Open hours",
      render: (t) => <span>{summarizeRanges(t.ranges)}{t.holidays.length ? <span className="table__secondary" style={{ display: "block" }}>{t.holidays.length} {t.holidays.length === 1 ? "holiday" : "holidays"}</span> : null}</span>,
    },
    { key: "use", header: "Used by", render: (t) => t.in_use_by ? <span>{t.in_use_by} {t.in_use_by === 1 ? "route" : "routes"}</span> : <span className="subtle">Not used</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Time conditions"
        description="Opening hours and holidays. An inbound route with a time condition sends calls outside these hours to its after-hours destination. A time condition can also be forced open or closed, from here or from a phone."
        actions={can("routing.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New time condition</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name" label="Search time conditions" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(t) => t.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Time conditions"
          onRowClick={(t) => router.push(`/routing/time-conditions/view/?id=${t.id}`)}
          rowLabel={(t) => `Open time condition ${t.name}`}
          empty={<EmptyState icon="clock" title={debounced || org ? "No matching time conditions" : "No time conditions yet"}>{!debounced && !org && can("routing.write") ? "Create one for your office hours, then pick it on an inbound route." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateTimeConditionDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(t) => router.push(`/routing/time-conditions/view/?id=${t.id}`)} />
    </div>
  );
}

function CreateTimeConditionDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (t: TimeCondition) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [draft, setDraft] = useState<TimeConditionDraft>(EMPTY_TIME_CONDITION);
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setDraft({ ...EMPTY_TIME_CONDITION, ranges: EMPTY_TIME_CONDITION.ranges.map((r) => ({ ...r, days: [...r.days] })) });
      errors.clear();
    }
  });

  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const orgTimezone = organizations.find((o) => o.id === effectiveOrg)?.timezone;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<TimeCondition>("/routing/time-conditions", { organization_id: effectiveOrg, ...timeConditionBody(draft) });
      toast.success(`Time condition ${created.name} created`, "Pick it on an inbound route to use it.");
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
      title="New time condition"
      description="Calls within the open hours follow the normal destination; others go after hours."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="tc-create" loading={busy} disabled={!effectiveOrg || !timeConditionValid(draft)}>Create time condition</Button></>}
    >
      <form id="tc-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TimeConditionFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} timezonePlaceholder={orgTimezone} autoFocus />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
