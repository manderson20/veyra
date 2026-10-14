// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Dialog, SelectField, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Site, SiteInput } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** Create or edit a site: a building or campus of an organization. */
export function SiteDialog({ open, onClose, site, onSaved }: { open: boolean; onClose: () => void; site?: Site; onSaved: (s: Site) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !site);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postal, setPostal] = useState("");
  const [country, setCountry] = useState("");
  const [emergency, setEmergency] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = site?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));

  useOnChange(open, () => {
    if (open) {
      setOrg(site?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(site?.name ?? "");
      setTimezone(site?.timezone ?? "");
      setStreet(site?.street ?? "");
      setCity(site?.city ?? "");
      setRegion(site?.region ?? "");
      setPostal(site?.postal_code ?? "");
      setCountry(site?.country ?? "");
      setEmergency(site?.emergency_caller_id_number ?? "");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: SiteInput = {
        name: name.trim(),
        timezone: timezone.trim() || null,
        street: street.trim() || null,
        city: city.trim() || null,
        region: region.trim() || null,
        postal_code: postal.trim() || null,
        country: country.trim() || null,
        emergency_caller_id_number: emergency.trim() || null,
      };
      const saved = site
        ? await api.patch<Site>(`/sites/${site.id}`, body)
        : await api.post<Site>("/sites", { organization_id: effectiveOrg, ...body });
      toast.success(site ? "Site saved" : `Site "${saved.name}" created`);
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={site ? `Edit site "${site.name}"` : "New site"}
      description="A building or campus. Phones, device profiles and paging zones can belong to a site; its time zone and emergency caller ID are defaults for its extensions."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="site-form" loading={busy} disabled={!effectiveOrg || !name.trim()}>{site ? "Save changes" : "Create site"}</Button></>}>
      <form id="site-form" className="stack stack--sm" onSubmit={submit}>
        {!site && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Main Campus" onChange={(e) => setName(e.target.value)} />
        <div className="form-grid">
          <TextField label="Time zone" value={timezone} error={errors.fields.timezone} placeholder="Organization default" help="IANA name such as America/Chicago." onChange={(e) => setTimezone(e.target.value)} />
          <TextField label="Emergency caller ID number" inputMode="tel" value={emergency} error={errors.fields.emergency_caller_id_number}
            help="Default for this site's extensions on 911 calls (the building's registered number)." onChange={(e) => setEmergency(e.target.value)} />
        </div>
        <TextField label="Street" value={street} error={errors.fields.street} onChange={(e) => setStreet(e.target.value)} />
        <div className="form-grid">
          <TextField label="City" value={city} error={errors.fields.city} onChange={(e) => setCity(e.target.value)} />
          <TextField label="State or region" value={region} error={errors.fields.region} onChange={(e) => setRegion(e.target.value)} />
        </div>
        <div className="form-grid">
          <TextField label="Postal code" value={postal} error={errors.fields.postal_code} onChange={(e) => setPostal(e.target.value)} />
          <TextField label="Country" value={country} error={errors.fields.country} placeholder="US" maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
