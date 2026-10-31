// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DeviceDialog } from "@/components/devices/DeviceDialog";
import { ImportListDialog } from "@/components/devices/ImportListDialog";
import { Badge, Button, Callout, Card, Checkbox, DataTable, EmptyState, LoadingState, PageHeader, Pagination, SearchInput, SelectField, TextField, useToast, type Column } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { sameBrand } from "@/lib/brands";
import type { CatalogModels, Device, DeviceProfile, DeviceStatus, Extension, Page, UnregisteredDevice } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 50;
export const DEVICE_STATUS: Record<DeviceStatus, { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  never: { label: "Never provisioned", tone: "neutral" },
  provisioned: { label: "Provisioned", tone: "ok" },
  stale: { label: "Not seen lately", tone: "warn" },
  error: { label: "Error", tone: "danger" },
};

/** Green: the phone has what is configured now. Yellow: it has not fetched since the last change. */
function ConfigStatus({ d }: { d: Device }) {
  if (d.status === "error") return <Badge tone="danger">Error</Badge>;
  if (d.config_state === "current") return <Badge tone="ok">Current</Badge>;
  if (d.config_state === "pending") return <Badge tone="warn">Waiting for phone</Badge>;
  if (d.config_state === "never") return <Badge tone="neutral">Never fetched</Badge>;
  return <Badge tone="neutral">No template</Badge>;
}

interface NewRow { org: string; extension_id: string; manufacturer: string; mac: string; profile: string | null; model: string }
const EMPTY_ROW: NewRow = { org: "", extension_id: "", manufacturer: "", mac: "", profile: null, model: "" };
const NEW_KEY = "new";
type Row = Device | typeof NEW_KEY;

function ExtensionMapping() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { can, session } = useSession();
  const { organizations } = useOrganizationOptions();
  const errors = useFormErrors();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [profile, setProfile] = useState(params.get("profile") ?? "");
  const [brand, setBrand] = useState("");
  const [offset, setOffset] = useState(0);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [seen, setSeen] = useState<UnregisteredDevice | undefined>();
  const [draft, setDraft] = useState<NewRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [selected, setSelected] = useState<Device[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [bulkBusy, setBulkBusy] = useState<"use" | "update" | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => { setDebounced(q.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Device>>("/devices", { q: debounced, organization_id: org || undefined, profile_id: profile || undefined, manufacturer: brand || undefined, limit: LIMIT, offset });
  const models = useApiData<CatalogModels>("/provisioning/models");
  const unregistered = useApiData<UnregisteredDevice[]>("/devices/unregistered");
  const profiles = useApiData<Page<DeviceProfile>>("/device-profiles", { organization_id: org || undefined, limit: 200 });
  const editable = can("devices.write");
  const manyOrgs = organizations.length > 1;
  const manufacturers = models.data?.manufacturers ?? [];
  const homeOrg = org || session?.user.home_organization_id || organizations[0]?.id || "";
  const draftOrg = draft?.org || homeOrg;
  const extensions = useApiData<Page<Extension>>(draft && draftOrg ? "/extensions" : null, { organization_id: draftOrg, limit: 500 });
  const reload = () => { list.reload(); unregistered.reload(); };
  const templatesFor = (organizationId: string, manufacturer: string) => (profiles.data?.items ?? []).filter((p) => p.organization_id === organizationId && sameBrand(p.manufacturer, manufacturer));
  const modelsOf = (manufacturer: string) => manufacturers.find((m) => sameBrand(m.name, manufacturer))?.models ?? [];

  const patchRow = async (d: Device, patch: { profile_id?: string | null; model?: string; values?: Record<string, never> }) => {
    try {
      await api.patch<Device>(`/devices/${d.id}`, patch);
      list.reload();
    } catch (err) {
      toast.error("The phone was not changed", errorMessage(err));
      list.reload();
    }
  };

  const saveNew = async () => {
    if (!draft) return;
    setSaving(true);
    errors.clear();
    try {
      const defaultTemplate = templatesFor(draftOrg, draft.manufacturer).find((p) => p.is_default)?.id ?? "";
      await api.post<Device>("/devices", {
        organization_id: draftOrg,
        mac_address: draft.mac.trim(),
        manufacturer: draft.manufacturer,
        model: draft.model,
        profile_id: (draft.profile ?? defaultTemplate) || null,
        primary_extension_id: draft.extension_id || null,
      });
      toast.success("Phone added", "It receives its configuration at its next check.");
      setDraft(null);
      reload();
    } catch (err) {
      errors.set(err);
    } finally {
      setSaving(false);
    }
  };

  const isSelected = (d: Device) => selected.some((x) => x.id === d.id);
  const toggle = (d: Device, on: boolean) => setSelected((rows) => (on ? [...rows, d] : rows.filter((x) => x.id !== d.id)));
  const pageRows = list.data?.items ?? [];
  const allOnPage = pageRows.length > 0 && pageRows.every(isSelected);
  const toggleAll = (on: boolean) => setSelected((rows) => {
    const others = rows.filter((x) => !pageRows.some((d) => d.id === x.id));
    return on ? [...others, ...pageRows] : others;
  });
  const first = selected[0];
  const oneGroup = !!first && selected.every((d) => d.organization_id === first.organization_id && sameBrand(d.manufacturer, first.manufacturer));
  const selectedOptions = first && oneGroup ? templatesFor(first.organization_id, first.manufacturer) : [];
  const applySelected = async () => {
    setBulkBusy("use");
    try {
      const r = await api.post<{ changed: number }>("/devices/use-template", { device_ids: selected.map((d) => d.id), profile_id: selectedTemplate });
      toast.success(`${r.changed} phone${r.changed === 1 ? "" : "s"} moved to the template`, "They pick it up at their next check, or use Update Phones.");
      setSelectedTemplate("");
      list.reload();
    } catch (err) {
      toast.error("No phone was changed", errorMessage(err));
    } finally {
      setBulkBusy(null);
    }
  };
  const updatePhones = async () => {
    setBulkBusy("update");
    try {
      const r = await api.post<{ phones: number; asked: number }>("/devices/update-phones", { device_ids: selected.map((d) => d.id) });
      toast.success("Phones asked to update", `${r.asked} of ${r.phones} accepted the request.`);
    } catch (err) {
      toast.error("The phones were not asked", errorMessage(err));
    } finally {
      setBulkBusy(null);
    }
  };

  const setDraftField = (patch: Partial<NewRow>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const columns: Column<Row>[] = [
    ...(editable ? [{
      key: "select",
      header: <Checkbox label={<span className="sr-only">Select all on this page</span>} checked={allOnPage} onChange={(e) => toggleAll(e.target.checked)} />,
      render: (r: Row) => r === NEW_KEY ? null : <Checkbox label={<span className="sr-only">Select {r.label ?? r.mac_display}</span>} checked={isSelected(r)} onChange={(e) => toggle(r, e.target.checked)} />,
    }] : []),
    {
      key: "extension",
      header: "Extension",
      render: (r) => r === NEW_KEY ? (
        <span className="stack stack--sm">
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={draftOrg} error={errors.fields.organization_id} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setDraftField({ org: e.target.value, extension_id: "", profile: null })} /> : null}
          <SelectField label={<span className="sr-only">Extension</span>} value={draft?.extension_id ?? ""} error={errors.fields.primary_extension_id} placeholder="No extension" options={(extensions.data?.items ?? []).map((x) => ({ value: x.id, label: `${x.number} ${x.display_name}` }))} onChange={(e) => setDraftField({ extension_id: e.target.value })} />
        </span>
      ) : (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{r.extension ? <><span className="mono">{r.extension.number}</span> {r.extension.display_name}</> : <span className="subtle">No extension</span>}{r.lines.length ? <span className="subtle"> +{r.lines.length}</span> : null}</span>
          <span className="table__secondary">{[r.label, manyOrgs ? r.organization_name : null].filter(Boolean).join(" · ")}</span>
        </span>
      ),
    },
    {
      key: "brand",
      header: "Brand / MAC",
      render: (r) => r === NEW_KEY ? (
        <span className="stack stack--sm">
          <SelectField label={<span className="sr-only">Brand</span>} value={draft?.manufacturer ?? ""} error={errors.fields.manufacturer} placeholder="Choose a brand" options={manufacturers.map((m) => ({ value: m.name, label: m.name }))} onChange={(e) => setDraftField({ manufacturer: e.target.value, model: "", profile: null })} />
          <TextField label={<span className="sr-only">MAC address</span>} value={draft?.mac ?? ""} error={errors.fields.mac_address} placeholder="MAC address" onChange={(e) => setDraftField({ mac: e.target.value })} />
        </span>
      ) : <span><span style={{ display: "block" }}>{r.manufacturer}</span><span className="table__secondary mono">{r.mac_display}</span></span>,
    },
    {
      key: "status",
      header: "IP / Status",
      render: (r) => r === NEW_KEY ? <span className="subtle">New phone</span> : (
        <span>
          <span className="mono" style={{ display: "block" }}>{r.last_seen_ip ?? "—"}</span>
          <ConfigStatus d={r} />
          {r.last_seen_at ? <span className="table__secondary" style={{ display: "block" }}>{formatRelative(r.last_seen_at)}</span> : null}
          {r.problems.length ? <Badge tone="warn" icon="alert">{r.problems[0]}</Badge> : null}
        </span>
      ),
    },
    {
      key: "template",
      header: "Template / Model",
      render: (r) => {
        if (r === NEW_KEY) {
          const options = templatesFor(draftOrg, draft?.manufacturer ?? "");
          const value = draft?.profile ?? options.find((p) => p.is_default)?.id ?? "";
          return (
            <span className="stack stack--sm">
              <SelectField label={<span className="sr-only">Template</span>} value={value} error={errors.fields.profile_id} disabled={!draft?.manufacturer} placeholder="No template" options={options.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setDraftField({ profile: e.target.value })} />
              <SelectField label={<span className="sr-only">Model</span>} value={draft?.model ?? ""} error={errors.fields.model} disabled={!draft?.manufacturer} placeholder="Choose a model" options={modelsOf(draft?.manufacturer ?? "").map((m) => ({ value: m, label: m }))} onChange={(e) => setDraftField({ model: e.target.value })} />
            </span>
          );
        }
        const known = modelsOf(r.manufacturer);
        const modelOptions = (known.includes(r.model) ? known : [r.model, ...known]).map((m) => ({ value: m, label: m }));
        const templateOptions = templatesFor(r.organization_id, r.manufacturer).map((p) => ({ value: p.id, label: p.name }));
        return (
          <span className="stack stack--sm">
            <SelectField label={<span className="sr-only">Template</span>} disabled={!editable} value={r.profile_id ?? ""} placeholder="No template" options={r.profile_id && !templateOptions.some((o) => o.value === r.profile_id) ? [{ value: r.profile_id, label: r.profile_name ?? "Current template" }, ...templateOptions] : templateOptions}
              onChange={(e) => void patchRow(r, { profile_id: e.target.value || null, values: {} })} />
            <SelectField label={<span className="sr-only">Model</span>} disabled={!editable} value={r.model} options={modelOptions} onChange={(e) => void patchRow(r, { model: e.target.value })} />
          </span>
        );
      },
    },
    {
      key: "actions",
      header: "",
      render: (r) => r === NEW_KEY ? (
        <span className="row" style={{ gap: 4 }}>
          <Button size="sm" variant="primary" loading={saving} disabled={!draft?.mac.trim() || !draft?.manufacturer || !draft?.model || !draftOrg} onClick={() => void saveNew()}>Save</Button>
          <Button size="sm" variant="ghost" disabled={saving} onClick={() => { setDraft(null); errors.clear(); }}>Cancel</Button>
        </span>
      ) : <Link className={buttonClass("secondary", "sm")} href={`/devices/view/?id=${r.id}`}>Open</Link>,
    },
  ];
  const seenColumns: Column<UnregisteredDevice>[] = [
    { key: "mac", header: "MAC address", render: (u) => <span className="mono">{u.mac_display}</span> },
    { key: "model", header: "Model", render: (u) => <span>{[u.manufacturer, u.model].filter(Boolean).join(" ") || <span className="subtle">{u.user_agent ?? "unknown"}</span>}</span> },
    { key: "org", header: "Credential of", render: (u) => u.organization_name ?? "—" },
    { key: "ip", header: "Address", render: (u) => <span className="mono">{u.ip_address ?? "—"}</span> },
    { key: "seen", header: "Last seen", render: (u) => <span>{formatRelative(u.last_seen_at)} · {u.requests} request{u.requests === 1 ? "" : "s"}</span> },
    ...(editable ? [{ key: "actions", header: "", render: (u: UnregisteredDevice) => <Button size="sm" variant="primary" onClick={() => { setSeen(u); setRegisterOpen(true); }}>Register</Button> }] : []),
  ];
  const rows: Row[] | undefined = draft ? [NEW_KEY, ...pageRows] : list.data?.items;

  return (
    <div className="stack">
      <PageHeader title="Extension Mapping" description="Every phone: its extension, brand, address, template and model. Green means the phone has the current configuration; yellow means it has not fetched since the last change."
        actions={
          <span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            {homeOrg ? <a className={buttonClass("secondary")} href={`${API_BASE}/bulk/phones/export.csv?organization_id=${encodeURIComponent(homeOrg)}`} download>Export List</a> : null}
            {editable && homeOrg ? <Button icon="upload" onClick={() => setImportOpen(true)}>Import List</Button> : null}
            {editable ? <Button variant="primary" icon="plus" disabled={!!draft} onClick={() => { errors.clear(); setDraft({ ...EMPTY_ROW, manufacturer: brand }); }}>Add Extension</Button> : null}
          </span>
        } />
      {unregistered.data?.length ? (
        <Card title="Phones seen but not registered" subtitle="These phones asked for configuration with a valid enrollment credential in the last 7 days but have no device record yet." flush>
          <DataTable columns={seenColumns} rows={unregistered.data} rowKey={(u) => u.mac_address} caption="Unregistered phones" />
        </Card>
      ) : null}
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by extension, name, MAC, IP, brand or model" label="Search phones" />
          {manyOrgs ? <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} /> : null}
          <SelectField label={<span className="sr-only">Brand</span>} value={brand} placeholder="All brands" options={manufacturers.map((m) => ({ value: m.name, label: m.name }))} onChange={(e) => { setBrand(e.target.value); setProfile(""); setOffset(0); }} />
          <SelectField label={<span className="sr-only">Template</span>} value={profile} placeholder="All templates" options={(profiles.data?.items ?? []).filter((p) => !brand || sameBrand(p.manufacturer, brand)).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => { setProfile(e.target.value); setOffset(0); }} />
        </div>
        {selected.length ? (
          <div className="table-toolbar">
            <span>{selected.length} selected</span>
            {oneGroup ? (
              <>
                <SelectField label={<span className="sr-only">Template for the selected phones</span>} value={selectedTemplate} placeholder="Choose a template" options={selectedOptions.map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setSelectedTemplate(e.target.value)} />
                <Button size="sm" variant="primary" loading={bulkBusy === "use"} disabled={!selectedTemplate || !!bulkBusy} onClick={() => void applySelected()}>Use Selected</Button>
              </>
            ) : <span className="subtle">Select phones of one brand and organization to change their template.</span>}
            <Button size="sm" loading={bulkBusy === "update"} disabled={!!bulkBusy} onClick={() => void updatePhones()}>Update Phones</Button>
            <Button size="sm" variant="ghost" disabled={!!bulkBusy} onClick={() => setSelected([])}>Clear</Button>
          </div>
        ) : null}
        {errors.message ? <div style={{ padding: 12 }}><Callout tone="danger">{errors.message}</Callout></div> : null}
        <DataTable columns={columns} rows={rows} rowKey={(r) => (r === NEW_KEY ? NEW_KEY : r.id)} loading={list.loading} error={list.error} onRetry={list.reload} caption="Extension mapping"
          empty={<EmptyState icon="device" title={debounced || org || profile || brand ? "No matching phones" : "No phones yet"}>{!debounced && !org && !profile && editable ? "Choose Add Extension, import a list, or point a phone at this server and it appears above." : null}</EmptyState>} />
      </Card>
      {list.data && list.data.total > LIMIT ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
      <DeviceDialog open={registerOpen} seen={seen} onClose={() => setRegisterOpen(false)} onCreated={(d) => { reload(); router.push(`/devices/view/?id=${d.id}`); }} />
      <ImportListDialog open={importOpen} organizationId={homeOrg} onClose={() => setImportOpen(false)} onImported={reload} />
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ExtensionMapping /></Suspense>;
}
