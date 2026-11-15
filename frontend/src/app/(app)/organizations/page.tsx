// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  PageHeader,
  Pagination,
  SearchInput,
  SelectField,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api } from "@/lib/api";
import { parseNumbers } from "@/lib/numberblocks";
import { formatDateTime, slugify } from "@/lib/format";
import { browserTimeZone, timeZones } from "@/lib/timezones";
import type { MultiTenancyStatus, NumberConflict, Organization, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const LIMIT = 25;

export default function OrganizationsPage() {
  const router = useRouter();
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Organization>>("/organizations", { q: debounced, limit: LIMIT, offset });
  const mt = useApiData<MultiTenancyStatus>(can("system.settings.read") ? "/system/multi-tenancy" : null);
  const conflicts = useApiData<NumberConflict[]>(can("organizations.write") ? "/numbers/conflicts" : null);
  const columns: Column<Organization>[] = [
    { key: "name", header: "Name", render: (o) => <span className="table__primary">{o.name}</span> },
    { key: "slug", header: "Short name", render: (o) => <span className="mono">{o.slug}</span> },
    ...(can("system.settings.read") ? [{ key: "ns", header: "Engine names", render: (o: Organization) => <span className="mono subtle">{o.engine_namespace ? `veyra_${o.engine_namespace}-…` : "veyra-… (original)"}</span> }] : []),
    { key: "tz", header: "Time zone", render: (o) => o.timezone },
    { key: "status", header: "Status", render: (o) => <Badge tone={o.is_active ? "ok" : "neutral"}>{o.is_active ? "Active" : "Inactive"}</Badge> },
    { key: "created", header: "Created", render: (o) => <span className="subtle nowrap">{formatDateTime(o.created_at)}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Organizations"
        description="The school districts, municipalities and businesses served by this installation."
        actions={can("organizations.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}
          disabled={!!mt.data && !mt.data.enabled && mt.data.active_organizations >= 1}>New organization</Button> : null}
      />
      {mt.data && !mt.data.enabled ? (
        mt.data.active_organizations > 1 ? (
          <Callout tone="warn" title="Several organizations without isolation">Their phones can reach each other. Turn multi-tenancy on under System → Settings.</Callout>
        ) : can("organizations.write") ? (
          <Callout tone="info">A second organization needs multi-tenancy (System → Settings), which keeps the organizations&apos; phones, numbers and voicemail apart.</Callout>
        ) : null
      ) : null}
      {conflicts.data?.length ? (
        <Callout tone="warn" title="Numbers routed by an organization that does not own them">
          <p>These inbound routes are skipped until you decide: assign the number to the route&apos;s organization (withdraw it from the owner first), or delete the route.</p>
          <ul>
            {conflicts.data.map((c) => (
              <li key={c.route_id}><span className="mono">{c.did}</span>: routed by {c.route_organization_name}, owned by {c.owner_organization_name}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or short name" label="Search organizations" />
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(o) => o.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Organizations"
          onRowClick={(o) => router.push(`/organizations/view/?id=${o.id}`)}
          rowLabel={(o) => `Open ${o.name}`}
          empty={<EmptyState icon="building" title={debounced ? "No matching organizations" : "No organizations yet"} />}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <CreateOrganizationDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        multiTenancy={!!mt.data?.enabled}
        onCreated={(o) => router.push(`/organizations/setup/?id=${o.id}`)}
      />
    </div>
  );
}

/** Onboarding step 1 (docs/MULTI_TENANCY_MSP.md §10): the organization and its
 * numbers in one save; the setup page takes it from there. */
function CreateOrganizationDialog({ open, onClose, onCreated, multiTenancy }: { open: boolean; onClose: () => void; onCreated: (o: Organization) => void; multiTenancy: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const zones = useMemo(() => timeZones(), []);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [tz, setTz] = useState("UTC");
  const [nums, setNums] = useState("");
  const [mainNumber, setMainNumber] = useState("");
  const [emergencyNumber, setEmergencyNumber] = useState("");
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setNums("");
      setMainNumber("");
      setEmergencyNumber("");
      setName("");
      setSlug("");
      setSlugTouched(false);
      setTz(browserTimeZone());
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const numbers = parseNumbers(nums);
      const org = await api.post<Organization>("/organizations", {
        name: name.trim(), slug, timezone: tz,
        ...(numbers.length ? { numbers } : {}),
        ...(mainNumber.trim() ? { main_number: mainNumber.trim() } : {}),
        ...(emergencyNumber.trim() ? { emergency_caller_id_number: emergencyNumber.trim() } : {}),
      });
      toast.success("Organization created", org.name);
      onClose();
      onCreated(org);
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
      title="New organization: organization and numbers"
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="org-create" loading={busy}>Create and continue</Button></>}
    >
      <form id="org-create" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name}
          onChange={(e) => { setName(e.target.value); if (!slugTouched) setSlug(slugify(e.target.value)); }} />
        <TextField label="Short name" required help="Lower-case letters, digits and dashes. Cannot be changed later." value={slug}
          error={errors.fields.slug} onChange={(e) => { setSlug(e.target.value.toLowerCase()); setSlugTouched(true); }} />
        <SelectField label="Time zone" value={tz} error={errors.fields.timezone} options={zones.map((z) => ({ value: z, label: z.replace(/_/g, " ") }))} onChange={(e) => setTz(e.target.value)} />
        <TextArea label="Numbers" rows={3} required={multiTenancy} value={nums} spellCheck={false} placeholder={"5735550100\n5735550200-5735550299"}
          error={errors.fields.numbers ?? errors.fields.first ?? errors.fields.last}
          help="The carrier numbers that belong to this organization, one number or block (first-last) per line. Only its own numbers can ring it or be its caller ID." onChange={(e) => setNums(e.target.value)} />
        <TextField label="Main number" required={multiTenancy} value={mainNumber} inputMode="tel" error={errors.fields.main_number}
          help="One of the numbers above: the caller ID of its outside calls." onChange={(e) => setMainNumber(e.target.value)} />
        <TextField label="Emergency number" required={multiTenancy} value={emergencyNumber} inputMode="tel" error={errors.fields.emergency_caller_id_number}
          help="One of the numbers above, registered with the carrier at the organization's address, presented on its 911 calls." onChange={(e) => setEmergencyNumber(e.target.value)} />
        {multiTenancy ? null : <Callout tone="neutral">The numbers are optional for the first organization. They are required once multi-tenancy is on.</Callout>}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
