// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { EMPTY_PROFILE, ProfileFields, profileBody, type ProfileDraft } from "@/components/devices/ProfileFields";
import { Badge, Button, Callout, Card, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import { groupByBrand } from "@/lib/brands";
import type { DeviceProfile, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

function CreateProfileDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (p: DeviceProfile) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_PROFILE);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const options = useProfileOptions(open ? effectiveOrg : "", draft.template_key || undefined);

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setDraft(EMPTY_PROFILE);
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<DeviceProfile>("/device-profiles", { organization_id: effectiveOrg, ...profileBody(draft) });
      toast.success(`Device profile "${created.name}" created`, "Assign it to phones on the Devices page.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title="New device profile"
      description="A template family plus settings, line keys and paging zones. Make one profile per building when only the paging differs."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="profile-form" loading={busy} disabled={!effectiveOrg || !draft.name.trim() || !draft.template_key}>Create profile</Button></>}>
      <form id="profile-form" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setDraft((d) => ({ ...d, site_id: "", paging: {} })); }} />
        ) : null}
        <ProfileFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} templates={options.templates} template={options.template}
          zones={options.zones} sites={options.sites} firmware={options.firmware} errors={errors.fields} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function DeviceProfilesPage() {
  const router = useRouter();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<DeviceProfile>>("/device-profiles", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const groups = groupByBrand(list.data?.items ?? [], (p) => p.manufacturer);
  const editable = can("devices.write");
  const manyOrgs = organizations.length > 1;
  const columns: Column<DeviceProfile>[] = [
    { key: "name", header: "Profile", render: (p) => <span><span className="table__primary" style={{ display: "block" }}>{p.name}</span><span className="table__secondary">{p.site_name ?? p.description ?? ""}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (p: DeviceProfile) => <span>{p.organization_name}</span> }] : []),
    { key: "template", header: "Template", render: (p) => <span><span style={{ display: "block" }}>{p.template_name ?? <span className="mono">{p.template_key}</span>}</span><span className="table__secondary">{p.template_abstract ? `Family: ${Object.keys(p.models).join(", ") || "no models"}` : Object.keys(p.models).join(", ")}</span></span> },
    { key: "paging", header: "Paging zones", render: (p) => p.paging.length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{p.paging.map((m) => <span key={m.zone_id} className="kv-chip" title={`Group ${m.poly_group}`}>{m.zone_name}</span>)}</span> : <span className="subtle">None</span> },
    { key: "keys", header: "Keys", render: (p) => <span>{p.keys.length}</span> },
    { key: "devices", header: "Phones", render: (p) => <span>{p.devices}</span> },
    { key: "status", header: "Status", render: (p) => p.problems.length ? <Badge tone="warn" icon="alert">{p.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Device profiles"
        description="A profile is a template family plus settings, line keys, paging zones and firmware. Phones point at a profile; the model picks the concrete template."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New profile</Button> : null} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or template" label="Search device profiles" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
        </div>
        {groups.length ? null : <DataTable columns={columns} rows={list.data?.items} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Device profiles"
          onRowClick={(p) => router.push(`/device-profiles/view/?id=${p.id}`)} rowLabel={(p) => `Open profile ${p.name}`}
          empty={<EmptyState icon="settings" title={debounced || org ? "No matching profiles" : "No device profiles yet"}>{!debounced && !org && editable ? "Create a profile for a family of phones (such as Poly VVX, Yealink or Grandstream), then register phones with it." : null}</EmptyState>} />}
      </Card>
      {groups.map((g) => (
        <Card key={g.brand} title={g.brand} flush>
          <DataTable columns={columns} rows={g.rows} rowKey={(p) => p.id} caption={`${g.brand} device profiles`}
            onRowClick={(p) => router.push(`/device-profiles/view/?id=${p.id}`)} rowLabel={(p) => `Open profile ${p.name}`} />
        </Card>
      ))}
      {list.data && list.data.total > LIMIT ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
      <CreateProfileDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(p) => router.push(`/device-profiles/view/?id=${p.id}`)} />
    </div>
  );
}
