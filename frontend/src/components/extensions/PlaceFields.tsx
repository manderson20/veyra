// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { SelectField, TextField } from "@/components/ui";
import type { Building, Department, Page, Site } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

export interface Place {
  site_id: string;
  building_id: string;
  department_id: string;
  location: string;
}

export const EMPTY_PLACE: Place = { site_id: "", building_id: "", department_id: "", location: "" };

export function placeOf(x: { site_id?: string | null; building_id?: string | null; department_id?: string | null; location?: string | null }): Place {
  return { site_id: x.site_id ?? "", building_id: x.building_id ?? "", department_id: x.department_id ?? "", location: x.location ?? "" };
}

export function placeBody(p: Place) {
  return { site_id: p.site_id || null, building_id: p.building_id || null, department_id: p.department_id || null, location: p.location.trim() || null };
}

export const samePlace = (a: Place, b: Place) =>
  a.site_id === b.site_id && a.building_id === b.building_id && a.department_id === b.department_id && a.location.trim() === b.location.trim();

/** Site, building, department and the dispatchable location of an extension
 * (docs/PRODUCTION_HARDENING.md §6; issue #126). */
export function PlaceFields({ organizationId, value, onChange, errors, disabled }: {
  organizationId: string;
  value: Place;
  onChange: (next: Place) => void;
  errors: Record<string, string>;
  disabled?: boolean;
}) {
  const q = organizationId ? { organization_id: organizationId } : undefined;
  const sites = useApiData<Page<Site>>(organizationId ? "/sites" : null, { ...q, limit: 200 });
  const buildings = useApiData<Building[]>(organizationId ? "/buildings" : null, q);
  const departments = useApiData<Department[]>(organizationId ? "/departments" : null, q);
  const atSite = (buildings.data ?? []).filter((b) => !value.site_id || b.site_id === value.site_id);
  return (
    <>
      <div className="form-grid">
        <SelectField label="Site" disabled={disabled} value={value.site_id} error={errors.site_id} placeholder="No site"
          options={(sites.data?.items ?? []).map((s) => ({ value: s.id, label: s.name }))}
          help="Its emergency route, emergency caller ID and readiness (System → Emergency calling)."
          onChange={(e) => {
            const site = e.target.value;
            const keep = (buildings.data ?? []).find((b) => b.id === value.building_id)?.site_id === site;
            onChange({ ...value, site_id: site, building_id: keep ? value.building_id : "" });
          }} />
        <SelectField label="Building" disabled={disabled || !atSite.length} value={value.building_id} error={errors.building_id}
          placeholder={atSite.length ? "No building" : value.site_id ? "This site has no buildings" : "No buildings yet (Sites → Buildings)"}
          options={atSite.map((b) => ({ value: b.id, label: value.site_id ? b.name : `${b.name} (${b.site_name})` }))}
          help="A building with its own address gives that address on emergency calls."
          onChange={(e) => {
            const b = (buildings.data ?? []).find((x) => x.id === e.target.value);
            onChange({ ...value, building_id: e.target.value, site_id: b ? b.site_id : value.site_id });
          }} />
      </div>
      <div className="form-grid">
        <TextField label="Location (dispatchable)" disabled={disabled} value={value.location} error={errors.location} placeholder="Room 101, first floor"
          help="Floor and room the on-site notification carries on an emergency call."
          onChange={(e) => onChange({ ...value, location: e.target.value })} />
        <SelectField label="Department" disabled={disabled} value={value.department_id} error={errors.department_id} placeholder="No department"
          options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
          help="My Phone layout templates can be assigned by department (Organizations → departments)."
          onChange={(e) => onChange({ ...value, department_id: e.target.value })} />
      </div>
    </>
  );
}
