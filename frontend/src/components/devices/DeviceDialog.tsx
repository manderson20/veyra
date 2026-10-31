// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Dialog, SelectField, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { sameBrand } from "@/lib/brands";
import type { Device, DeviceProfile, Extension, Page, UnregisteredDevice } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

/** Register a phone by MAC address (docs/DEVICE_PROVISIONING.md §2). */
export function DeviceDialog({ open, onClose, onCreated, seen }: { open: boolean; onClose: () => void; onCreated: (d: Device) => void; seen?: UnregisteredDevice }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [mac, setMac] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [model, setModel] = useState("");
  const [label, setLabel] = useState("");
  const [location, setLocation] = useState("");
  const [siteId, setSiteId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [extensionId, setExtensionId] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const options = useProfileOptions(open ? effectiveOrg : "");
  const profiles = useApiData<Page<DeviceProfile>>(open && effectiveOrg ? "/device-profiles" : null, { organization_id: effectiveOrg, limit: 200 });
  const extensions = useApiData<Page<Extension>>(open && effectiveOrg ? "/extensions" : null, { organization_id: effectiveOrg, limit: 500 });
  const models = options.manufacturers.find((m) => m.name.toLowerCase() === manufacturer.toLowerCase())?.models ?? [];

  useOnChange(open, () => {
    if (open) {
      setOrg(seen?.organization_id ?? session?.user.home_organization_id ?? "");
      setMac(seen?.mac_display ?? "");
      setManufacturer(seen?.manufacturer ?? "Poly");
      setModel(seen?.model ?? "");
      setLabel("");
      setLocation("");
      setSiteId("");
      setProfileId("");
      setExtensionId("");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<Device>("/devices", {
        organization_id: effectiveOrg,
        mac_address: mac.trim(),
        manufacturer: manufacturer.trim(),
        model: model.trim(),
        label: label.trim() || null,
        location: location.trim() || null,
        site_id: siteId || null,
        profile_id: profileId || null,
        primary_extension_id: extensionId || null,
      });
      toast.success(`Phone ${created.mac_display} registered`, "It receives its configuration at the next provisioning check.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={seen ? `Register phone ${seen.mac_display}` : "Register a phone"}
      description="The phone is identified by its MAC address. Its profile decides the template and paging zones; the extension is line 1."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="device-form" loading={busy} disabled={!effectiveOrg || !mac.trim() || !manufacturer.trim() || !model.trim()}>Register phone</Button></>}>
      <form id="device-form" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setSiteId(""); setProfileId(""); setExtensionId(""); }} />
        ) : null}
        <TextField label="MAC address" required autoFocus value={mac} error={errors.fields.mac_address} placeholder="00:04:f2:ab:cd:ef" help="Printed on the phone's label; separators are optional." onChange={(e) => setMac(e.target.value)} />
        <div className="form-grid">
          <SelectField label="Manufacturer" required value={options.manufacturers.some((m) => m.name === manufacturer) ? manufacturer : ""} error={errors.fields.manufacturer} placeholder="Choose"
            options={options.manufacturers.map((m) => ({ value: m.name, label: m.name }))} onChange={(e) => { setManufacturer(e.target.value); setModel(""); setProfileId(""); }} />
          {models.length ? (
            <SelectField label="Model" required value={model} error={errors.fields.model} placeholder="Choose a model" options={models.map((m) => ({ value: m, label: m }))} onChange={(e) => setModel(e.target.value)} />
          ) : (
            <TextField label="Model" required value={model} error={errors.fields.model} onChange={(e) => setModel(e.target.value)} />
          )}
        </div>
        <TextField label="Label" value={label} error={errors.fields.label} placeholder="e.g. Room 112" onChange={(e) => setLabel(e.target.value)} />
        <SelectField label="Device profile" value={profileId} error={errors.fields.profile_id} placeholder="No profile yet (nothing is served)"
          help={manufacturer ? `Profiles for ${manufacturer} phones.` : "Choose the manufacturer first."}
          options={(profiles.data?.items ?? []).filter((p) => sameBrand(p.manufacturer, manufacturer)).map((p) => ({ value: p.id, label: p.name }))} onChange={(e) => setProfileId(e.target.value)} />
        <div className="form-grid">
          <SelectField label="Extension (line 1)" value={extensionId} error={errors.fields.primary_extension_id} placeholder="No extension"
            options={(extensions.data?.items ?? []).map((x) => ({ value: x.id, label: `${x.number} — ${x.display_name}` }))} onChange={(e) => setExtensionId(e.target.value)} />
          <SelectField label="Site" value={siteId} error={errors.fields.site_id} placeholder="From the profile" options={options.sites.map((s) => ({ value: s.id, label: s.name }))} onChange={(e) => setSiteId(e.target.value)} />
        </div>
        <TextField label="Location (dispatchable)" value={location} error={errors.fields.location} placeholder="Room 101, first floor"
          help="Floor and room for emergency calls from this phone; wins over the extension's location." onChange={(e) => setLocation(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
