// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, DataTable, Dialog, EmptyState, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Building, Site } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

type Mode = { kind: "list" } | { kind: "edit"; building: Building | null } | { kind: "delete"; building: Building };

/** The buildings of a site (#126): extensions are placed in one, and a
 * building with its own address gives that address on emergency calls. */
export function BuildingsDialog({ site, editable, onClose, onChanged }: { site: Site | undefined; editable: boolean; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [name, setName] = useState("");
  const [street, setStreet] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postal, setPostal] = useState("");
  const [country, setCountry] = useState("");
  const [busy, setBusy] = useState(false);
  const list = useApiData<Building[]>(site ? `/sites/${site.id}/buildings` : null);

  useOnChange(site?.id, () => setMode({ kind: "list" }));
  const edit = (b: Building | null) => {
    setName(b?.name ?? "");
    setStreet(b?.street ?? "");
    setCity(b?.city ?? "");
    setRegion(b?.region ?? "");
    setPostal(b?.postal_code ?? "");
    setCountry(b?.country ?? "");
    errors.clear();
    setMode({ kind: "edit", building: b });
  };
  const done = (message: string) => {
    toast.success(message);
    setMode({ kind: "list" });
    list.reload();
    onChanged();
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!site || mode.kind !== "edit") return;
    setBusy(true);
    errors.clear();
    const body = { name: name.trim(), street: street.trim() || null, city: city.trim() || null, region: region.trim() || null, postal_code: postal.trim() || null, country: country.trim() || null };
    try {
      if (mode.building) await api.patch(`/buildings/${mode.building.id}`, body);
      else await api.post(`/sites/${site.id}/buildings`, body);
      done(mode.building ? "Building saved" : `Building "${body.name}" added`);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (mode.kind !== "delete") return;
    setBusy(true);
    try {
      await api.del(`/buildings/${mode.building.id}`);
      done(`Building "${mode.building.name}" deleted`);
    } catch (err) {
      toast.error("Could not delete the building", errorMessage(err));
      setMode({ kind: "list" });
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<Building>[] = [
    { key: "name", header: "Building", render: (b) => <span className="table__primary">{b.name}</span> },
    { key: "address", header: "Address", render: (b) => b.has_own_address ? <span>{[b.street, b.city, b.region].filter(Boolean).join(", ")}</span> : <span className="subtle">Same as the site</span> },
    { key: "ext", header: "Extensions", render: (b) => <span>{b.extensions}</span> },
    ...(editable ? [{ key: "actions", header: <span className="sr-only">Actions</span>, render: (b: Building) => (
      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
        <Button size="sm" onClick={(e) => { e.stopPropagation(); edit(b); }}>Edit</Button>
        <Button size="sm" variant="ghost" icon="trash" aria-label={`Delete ${b.name}`} onClick={(e) => { e.stopPropagation(); setMode({ kind: "delete", building: b }); }} />
      </span>
    ) }] : []),
  ];

  const title = mode.kind === "edit" ? (mode.building ? `Edit building "${mode.building.name}"` : "New building") : `Buildings of ${site?.name ?? ""}`;
  const footer = mode.kind === "edit" ? (
    <><Button onClick={() => setMode({ kind: "list" })} disabled={busy}>Back</Button><Button variant="primary" type="submit" form="building-form" loading={busy} disabled={!name.trim()}>{mode.building ? "Save changes" : "Add building"}</Button></>
  ) : mode.kind === "delete" ? (
    <><Button onClick={() => setMode({ kind: "list" })} disabled={busy}>Keep</Button><Button variant="danger" onClick={remove} loading={busy}>Delete building</Button></>
  ) : (
    <>{editable ? <Button icon="plus" onClick={() => edit(null)}>Add building</Button> : null}<Button variant="primary" onClick={onClose}>Done</Button></>
  );

  return (
    <Dialog open={!!site} onClose={onClose} busy={busy} title={title}
      description={mode.kind === "list" ? "Place extensions in a building (Extensions → Location). A building with its own street address gives that address on emergency calls; otherwise the site's is used." : undefined}
      footer={footer}>
      {mode.kind === "list" ? (
        <DataTable columns={columns} rows={list.data} rowKey={(b) => b.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Buildings"
          onRowClick={editable ? (b) => edit(b) : undefined} rowLabel={(b) => `Edit building ${b.name}`}
          empty={<EmptyState compact icon="building" title="No buildings yet">{editable ? "Add the buildings of this site, for example Gym, Main Office, East Wing." : null}</EmptyState>} />
      ) : null}
      {mode.kind === "delete" ? (
        <Callout tone="warn" title={`Delete "${mode.building.name}"?`}>
          {mode.building.extensions ? <>{mode.building.extensions} extension(s) are in this building; move them first.</> : "No extension is in this building."}
        </Callout>
      ) : null}
      {mode.kind === "edit" ? (
        <form id="building-form" className="stack stack--sm" onSubmit={submit}>
          <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Gym" onChange={(e) => setName(e.target.value)} />
          <p className="subtle" style={{ margin: 0 }}>Address: leave empty when it is the same as the site{site?.street ? <> (<Badge tone="neutral">{[site.street, site.city].filter(Boolean).join(", ")}</Badge>)</> : null}.</p>
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
      ) : null}
    </Dialog>
  );
}
