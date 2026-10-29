// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { MemberListEditor, membersFromIds, type MemberDraft } from "@/components/groups/MemberListEditor";
import { Button, Callout, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Extension, Page, PagingAllowed, PagingCodec, PagingKind, PagingZone, PagingZoneInput, Site } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

export const PAGING_KIND_LABELS: Record<PagingKind, string> = { normal: "Normal", priority: "Priority (interrupts calls)", emergency: "Emergency (group 25)" };
export const PAGING_ALLOWED_LABELS: Record<PagingAllowed, string> = { everyone: "Everyone in the organization", members: "Listed phones only", administrators: "Only from Veyra (interface, bells, API)" };

/** Create or edit a paging zone (docs/DEVICE_PROVISIONING.md §5). */
export function PagingZoneDialog({ open, onClose, zone, onSaved }: { open: boolean; onClose: () => void; zone?: PagingZone; onSaved: (z: PagingZone) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !zone);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [siteId, setSiteId] = useState("");
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("5004");
  const [polyAddress, setPolyAddress] = useState("224.0.1.116");
  const [polyPort, setPolyPort] = useState("5001");
  const [group, setGroup] = useState("1");
  const [kind, setKind] = useState<PagingKind>("normal");
  const [codec, setCodec] = useState<PagingCodec>("G.711Mu");
  const [enabled, setEnabled] = useState(true);
  const [number, setNumber] = useState("");
  const [allowed, setAllowed] = useState<PagingAllowed>("everyone");
  const [members, setMembers] = useState<MemberDraft[]>([]);
  const [maxSeconds, setMaxSeconds] = useState("120");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = zone?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const sites = useApiData<Page<Site>>(open && effectiveOrg ? "/sites" : null, { organization_id: effectiveOrg, limit: 200 });
  const extensions = useApiData<Page<Extension>>(open && effectiveOrg && allowed === "members" ? "/extensions" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(zone?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(zone?.name ?? "");
      setDescription(zone?.description ?? "");
      setSiteId(zone?.site_id ?? "");
      setAddress(zone?.multicast_address ?? "");
      setPort(String(zone?.multicast_port ?? 5004));
      setPolyAddress(zone?.poly_address ?? "224.0.1.116");
      setPolyPort(String(zone?.poly_port ?? 5001));
      setGroup(String(zone?.poly_group ?? 1));
      setKind(zone?.kind ?? "normal");
      setCodec(zone?.codec ?? "G.711Mu");
      setEnabled(zone?.is_enabled ?? true);
      setNumber(zone?.number ?? "");
      setAllowed(zone?.allowed ?? "everyone");
      setMembers(zone ? membersFromIds(zone.members) : []);
      setMaxSeconds(String(zone?.max_seconds ?? 120));
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: PagingZoneInput = {
        name: name.trim(),
        description: description.trim() || null,
        site_id: siteId || null,
        multicast_address: address.trim(),
        multicast_port: Number(port),
        poly_address: polyAddress.trim(),
        poly_port: Number(polyPort),
        poly_group: Number(group),
        kind,
        codec,
        is_enabled: enabled,
        number: number.trim() || null,
        allowed,
        members: allowed === "members" ? members.map((m) => m.extension_id) : [],
        max_seconds: Number(maxSeconds) || 120,
      };
      const saved = zone
        ? await api.patch<PagingZone>(`/paging-zones/${zone.id}`, body)
        : await api.post<PagingZone>("/paging-zones", { organization_id: effectiveOrg, ...body });
      toast.success(zone ? "Paging zone saved" : `Paging zone "${saved.name}" created`, "Phones pick up the change at their next provisioning check; deploy the changes for dialling the zone.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={zone ? `Edit paging zone "${zone.name}"` : "New paging zone"}
      description="A zone is one multicast page group: the address and port the speakers listen to, and the Poly group number the phones subscribe to for the same zone."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="zone-form" loading={busy} disabled={!effectiveOrg || !name.trim() || !address.trim()}>{zone ? "Save changes" : "Create zone"}</Button></>}>
      <form id="zone-form" className="stack stack--sm" onSubmit={submit}>
        {!zone && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setSiteId(""); }} />
        ) : null}
        <div className="form-grid">
          <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Building A" onChange={(e) => setName(e.target.value)} />
          <SelectField label="Site (optional)" value={siteId} error={errors.fields.site_id} placeholder="No site" options={(sites.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => setSiteId(e.target.value)} />
        </div>
        <div className="form-grid">
          <TextField label="Speakers' multicast address" required value={address} error={errors.fields.multicast_address} placeholder="239.1.2.10" help="The group the speakers already listen to (224.0.0.0–239.255.255.255)." onChange={(e) => setAddress(e.target.value)} />
          <TextField label="Speakers' port" required type="number" min={1024} max={65535} value={port} error={errors.fields.multicast_port} onChange={(e) => setPort(e.target.value)} />
        </div>
        <div className="form-grid">
          <TextField label="Poly group number" required type="number" min={1} max={25} value={group} error={errors.fields.poly_group} help="1–24 for normal zones; 25 is the Poly emergency group." onChange={(e) => setGroup(e.target.value)} />
          <SelectField label="Kind" value={kind} options={(Object.keys(PAGING_KIND_LABELS) as PagingKind[]).map((k) => ({ value: k, label: PAGING_KIND_LABELS[k] }))} onChange={(e) => setKind(e.target.value as PagingKind)} />
        </div>
        <div className="form-grid">
          <TextField label="Poly paging address" value={polyAddress} error={errors.fields.poly_address} help="One address and port for all Poly phones of the organization (default 224.0.1.116:5001)." onChange={(e) => setPolyAddress(e.target.value)} />
          <TextField label="Poly paging port" type="number" min={1024} max={65535} value={polyPort} error={errors.fields.poly_port} onChange={(e) => setPolyPort(e.target.value)} />
        </div>
        <SelectField label="Codec" value={codec} options={[{ value: "G.711Mu", label: "G.711 µ-law (default)" }, { value: "G.722", label: "G.722 (wideband)" }]} onChange={(e) => setCodec(e.target.value as PagingCodec)} />
        <div className="form-grid">
          <TextField label="Number to dial (optional)" inputMode="numeric" value={number} error={errors.fields.number} help="From the numbering plan; shares the space with extensions, groups and pages. Dialling it pages this zone live." onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
          <TextField label="Longest page (seconds)" type="number" min={5} max={600} value={maxSeconds} error={errors.fields.max_seconds} onChange={(e) => setMaxSeconds(e.target.value)} />
        </div>
        <SelectField label="Who may page it" value={allowed} error={errors.fields.allowed} options={(Object.keys(PAGING_ALLOWED_LABELS) as PagingAllowed[]).map((a) => ({ value: a, label: PAGING_ALLOWED_LABELS[a] }))} onChange={(e) => setAllowed(e.target.value as PagingAllowed)} />
        {allowed === "members" ? (
          <MemberListEditor label="Phones allowed to page" members={members} extensions={extensions.data?.items ?? []} loading={extensions.loading} onChange={setMembers} error={errors.fields.members} emptyText="No phones yet: nobody can page this zone from a phone." />
        ) : null}
        <TextArea label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <Switch label="Enabled" description="Disabled zones are left out of the phones' paging groups." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
