// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useDeferredValue, useEffect, useState } from "react";
import { Checkbox, TextField } from "@/components/ui";
import { api } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";
import type { Page, VoicemailBox } from "@/lib/types";

export interface ListedBox {
  id: string;
  label: string;
}

function label(b: VoicemailBox): string {
  return b.shared ? `${b.number} ${b.name} (shared inbox)` : `${b.number} ${b.name}`;
}

/** Turn stored box ids into labelled rows (one request per box, at most 20). */
export function useListedBoxes(ids: string[] | undefined, open: boolean): ListedBox[] | null {
  const [rows, setRows] = useState<ListedBox[] | null>(null);
  const key = (ids ?? []).join(",");
  useEffect(() => {
    if (!open) return;
    const list = key ? key.split(",") : [];
    let cancelled = false;
    Promise.all(list.map((id) => api.get<VoicemailBox>(`/voicemail/${id}`).then(label).catch(() => "A deleted box")))
      .then((labels) => { if (!cancelled) setRows(list.map((id, i) => ({ id, label: labels[i] ?? "A deleted box" }))); });
    return () => { cancelled = true; };
  }, [key, open]);
  return rows;
}

/** Other voicemail boxes of an organization, searched by number or name. */
export function BoxListPicker({ label: title, organizationId, exclude, value, onChange, emptyText, error, help }: {
  label: string;
  organizationId: string;
  /** The box being edited: it cannot list itself. */
  exclude?: string;
  value: ListedBox[];
  onChange: (next: ListedBox[]) => void;
  emptyText: string;
  error?: string;
  help?: string;
}) {
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const found = useApiData<Page<VoicemailBox>>(organizationId && q ? "/voicemail" : null, { organization_id: organizationId, q, limit: 20 });
  return (
    <fieldset className="stack stack--sm">
      <legend className="field__label">{title}</legend>
      {help ? <p className="subtle" style={{ margin: 0 }}>{help}</p> : null}
      {value.length ? value.map((x) => <Checkbox key={x.id} label={x.label} checked onChange={() => onChange(value.filter((y) => y.id !== x.id))} />) : <p className="subtle">{emptyText}</p>}
      <TextField label="Add a box" value={search} placeholder="Search by number or name" onChange={(e) => setSearch(e.target.value)} />
      {q ? (found.data?.items ?? []).filter((x) => x.id !== exclude && !value.some((y) => y.id === x.id)).map((x) => (
        <Checkbox key={x.id} label={label(x)} checked={false} onChange={() => onChange([...value, { id: x.id, label: label(x) }])} />
      )) : null}
      {error ? <p className="field__error" role="alert">{error}</p> : null}
    </fieldset>
  );
}
