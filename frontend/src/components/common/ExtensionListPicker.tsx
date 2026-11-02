// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useDeferredValue, useState } from "react";
import { Checkbox, TextField } from "@/components/ui";
import { useApiData } from "@/hooks/useApiData";
import type { Extension, Page } from "@/lib/types";

export interface ListedExtension {
  id: string;
  number: string;
  name: string;
}

/** A list of an organization's extensions. They can far outnumber a page, so
 * they are searched, not listed. */
export function ExtensionListPicker({ label, organizationId, value, onChange, emptyText, error, disabled }: {
  label: string;
  organizationId: string;
  value: ListedExtension[];
  onChange: (next: ListedExtension[]) => void;
  emptyText: string;
  error?: string;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const found = useApiData<Page<Extension>>(organizationId && q ? "/extensions" : null, { organization_id: organizationId, q, limit: 20 });
  return (
    <fieldset className="stack stack--sm">
      <legend className="field__label">{label}</legend>
      {value.length ? value.map((x) => <Checkbox key={x.id} label={`${x.number} ${x.name}`} checked disabled={disabled} onChange={() => onChange(value.filter((y) => y.id !== x.id))} />) : <p className="subtle">{emptyText}</p>}
      <TextField label="Add an extension" disabled={disabled} value={search} placeholder="Search by number or name" onChange={(e) => setSearch(e.target.value)} />
      {q ? (found.data?.items ?? []).filter((x) => !value.some((y) => y.id === x.id)).map((x) => (
        <Checkbox key={x.id} label={`${x.number} ${x.display_name}`} checked={false} disabled={disabled} onChange={() => onChange([...value, { id: x.id, number: x.number, name: x.display_name }])} />
      )) : null}
      {error ? <p className="field__error" role="alert">{error}</p> : null}
    </fieldset>
  );
}
