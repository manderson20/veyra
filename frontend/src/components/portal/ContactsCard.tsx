// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, Checkbox, Dialog, EmptyState, Icon, SearchInput, SelectField, TextArea, TextField, useToast } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import type { Contact, ContactInput, ContactNumber, MyExtension, OriginateResult } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";

const LABELS: { value: ContactNumber["label"]; label: string }[] = [
  { value: "work", label: "Work" }, { value: "mobile", label: "Mobile" }, { value: "home", label: "Home" }, { value: "other", label: "Other" },
];
const EMPTY: ContactInput = { name: "", company: null, numbers: [{ label: "work", number: "" }], email: null, favourite: false, speed_dial: null, notes: null };

/** Personal contacts and speed dials (docs/USER_PORTAL.md §6), with click-to-dial from one of the user's phones. */
export function ContactsCard({ extensions }: { extensions: MyExtension[] }) {
  const toast = useToast();
  const list = useApiData<Contact[]>("/me/contacts");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Contact | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  const [dialing, setDialing] = useState<string | null>(null);
  const phone = extensions.find((x) => x.is_enabled) ?? extensions[0];

  const shown = useMemo(() => {
    const rows = list.data ?? [];
    const needle = q.trim().toLowerCase();
    const digits = q.replace(/[\s().-]/g, "");
    if (!needle) return rows;
    return rows.filter((c) => c.name.toLowerCase().includes(needle) || (c.company ?? "").toLowerCase().includes(needle)
      || (c.email ?? "").toLowerCase().includes(needle) || (digits && c.numbers.some((n) => n.number.includes(digits))));
  }, [list.data, q]);

  const dial = async (number: string) => {
    if (!phone) return;
    setDialing(number);
    try {
      const r = await api.post<OriginateResult>("/calls/originate", { extension_id: phone.id, number });
      toast.success(`Ringing ${r.extension_number}`, `Pick up to call ${number}.`);
    } catch (err) {
      toast.error("Could not place the call", errorMessage(err));
    } finally {
      setDialing(null);
    }
  };
  const toggleFavourite = async (c: Contact) => {
    try {
      await api.patch(`/me/contacts/${c.id}`, { favourite: !c.favourite });
      list.reload();
    } catch (err) {
      toast.error("Could not save", errorMessage(err));
    }
  };

  return (
    <Card title="Contacts" subtitle="Your personal contacts and speed dials. Favourites come first; a speed-dial number can go on a phone key."
      actions={<div className="row"><Button icon="upload" onClick={() => setImporting(true)}>Import</Button><a className={buttonClass("secondary", "md")} href={`${API_BASE}/me/contacts/export.csv`} download><Icon name="download" size={14} /> Export</a><Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New contact</Button></div>}>
      <div className="stack stack--sm">
        {(list.data?.length ?? 0) > 5 ? <SearchInput value={q} onChange={setQ} placeholder="Search by name, company, number or email" label="Search contacts" /> : null}
        {list.error ? <Callout tone="danger">{errorMessage(list.error)}</Callout> : null}
        {list.data && list.data.length === 0 ? (
          <EmptyState icon="users" title="No contacts yet">Add the people and places you call often, or import a CSV file (name, company, number).</EmptyState>
        ) : null}
        {shown.length ? (
          <ul className="list-plain">
            {shown.map((c) => (
              <li key={c.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0, alignItems: "flex-start" }}>
                <span style={{ minWidth: 0 }}>
                  <span className="table__primary">
                    <button type="button" className="btn btn--ghost btn--sm" aria-label={c.favourite ? "Remove from favourites" : "Add to favourites"} onClick={() => toggleFavourite(c)} style={{ padding: 0, marginRight: 6 }}>
                      <Icon name="sparkle" size={14} strokeWidth={c.favourite ? 2.5 : 1.5} />
                    </button>
                    {c.name}{c.company ? <span className="subtle"> · {c.company}</span> : null}
                    {c.speed_dial ? <> <Badge tone="outline">Speed dial {c.speed_dial}</Badge></> : null}
                  </span>
                  <span className="table__secondary" style={{ display: "block" }}>
                    {c.numbers.map((n) => <span key={`${n.label}-${n.number}`} style={{ marginRight: 12 }}>{LABELS.find((l) => l.value === n.label)?.label}: <span className="mono">{n.number}</span></span>)}
                    {c.email ? <span>{c.email}</span> : null}
                  </span>
                </span>
                <span className="row" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
                  {phone && c.numbers[0] ? <Button size="sm" icon="phone" loading={dialing === c.numbers[0].number} onClick={() => dial(c.numbers[0]?.number ?? "")}>Call</Button> : null}
                  <Button size="sm" onClick={() => setEditing(c)}>Edit</Button>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {list.data && list.data.length > 0 && shown.length === 0 ? <p className="subtle">No contact matches.</p> : null}
      </div>
      <ContactDialog contact={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} />
      <ImportDialog open={importing} onClose={() => setImporting(false)} onDone={() => { setImporting(false); list.reload(); }} />
    </Card>
  );
}

function ContactDialog({ contact, onClose, onSaved }: { contact: Contact | "new" | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const initial: ContactInput = contact && contact !== "new" ? { name: contact.name, company: contact.company, numbers: contact.numbers.length ? contact.numbers : [{ label: "work", number: "" }], email: contact.email, favourite: contact.favourite, speed_dial: contact.speed_dial, notes: contact.notes } : EMPTY;
  const [draft, setDraft] = useState<ContactInput>(initial);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const set = (patch: Partial<ContactInput>) => setDraft((d) => ({ ...d, ...patch }));
  const setNumber = (i: number, patch: Partial<ContactNumber>) => setDraft((d) => ({ ...d, numbers: d.numbers.map((n, j) => (j === i ? { ...n, ...patch } : n)) }));
  const body = (): ContactInput => ({ ...draft, numbers: draft.numbers.filter((n) => n.number.trim()).map((n) => ({ label: n.label, number: n.number.trim() })), company: draft.company?.trim() || null, email: draft.email?.trim() || null, notes: draft.notes?.trim() || null });
  const valid = draft.name.trim().length > 0 && (body().numbers.length > 0 || !!body().email);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (contact === "new") await api.post("/me/contacts", body());
      else if (contact) await api.patch(`/me/contacts/${contact.id}`, body());
      toast.success(contact === "new" ? "Contact added" : "Contact saved");
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!contact || contact === "new") return;
    setBusy(true);
    try {
      await api.del(`/me/contacts/${contact.id}`);
      toast.success("Contact deleted");
      onSaved();
    } catch (err) {
      errors.set(err);
      setBusy(false);
    }
  };

  return (
    <Dialog open={contact !== null} onClose={onClose} busy={busy} title={contact === "new" ? "New contact" : `Edit ${contact?.name ?? ""}`}
      footer={<>
        {contact && contact !== "new" ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)} disabled={busy}>Delete</Button> : null}
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="primary" type="submit" form="contact-form" loading={busy} disabled={!valid}>Save</Button>
      </>}>
      <form id="contact-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={draft.name} error={errors.fields.name} onChange={(e) => set({ name: e.target.value })} />
        <TextField label="Company or place" value={draft.company ?? ""} error={errors.fields.company} onChange={(e) => set({ company: e.target.value })} />
        <fieldset className="stack stack--sm" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label">Numbers</legend>
          {draft.numbers.map((n, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-end" }}>
              <SelectField label={<span className="sr-only">Kind</span>} value={n.label} options={LABELS} onChange={(e) => setNumber(i, { label: e.target.value as ContactNumber["label"] })} />
              <TextField label={<span className="sr-only">Number</span>} inputMode="tel" placeholder="e.g. 1002 or +1 573 555 0100" value={n.number} onChange={(e) => setNumber(i, { number: e.target.value })} />
              {draft.numbers.length > 1 ? <Button size="sm" icon="x" aria-label="Remove number" onClick={() => setDraft((d) => ({ ...d, numbers: d.numbers.filter((_, j) => j !== i) }))} /> : null}
            </div>
          ))}
          {errors.fields.numbers ? <p className="field__error">{errors.fields.numbers}</p> : null}
          {draft.numbers.length < 5 ? <div><Button size="sm" icon="plus" onClick={() => setDraft((d) => ({ ...d, numbers: [...d.numbers, { label: "mobile", number: "" }] }))}>Add a number</Button></div> : null}
        </fieldset>
        <TextField label="Email" type="email" value={draft.email ?? ""} error={errors.fields.email} onChange={(e) => set({ email: e.target.value })} />
        <div className="grid grid--2">
          <TextField label="Speed dial (1–99)" type="number" min={1} max={99} value={draft.speed_dial ?? ""} error={errors.fields.speed_dial} help="Can be put on one of your phone keys." onChange={(e) => set({ speed_dial: e.target.value ? Number(e.target.value) : null })} />
          <Checkbox label="Favourite" checked={draft.favourite} onChange={(e) => set({ favourite: e.target.checked })} />
        </div>
        <TextArea label="Notes" value={draft.notes ?? ""} rows={2} onChange={(e) => set({ notes: e.target.value })} />
        {errors.message && !errors.fields.name ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
      <Dialog open={deleting} onClose={() => setDeleting(false)} busy={busy} title="Delete this contact?"
        footer={<><Button onClick={() => setDeleting(false)} disabled={busy}>Cancel</Button><Button variant="danger" loading={busy} onClick={remove}>Delete</Button></>}>
        <p>{contact && contact !== "new" ? contact.name : ""} is removed from your contacts and from any speed-dial key that used it.</p>
      </Dialog>
    </Dialog>
  );
}

function ImportDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ added: number; updated: number; skipped: string[] } | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ added: number; updated: number; skipped: string[] }>("/me/contacts/import", { text, replace });
      setResult(r);
      toast.success(`${r.added} added, ${r.updated} updated`, r.skipped.length ? `${r.skipped.length} line(s) skipped.` : undefined);
      if (!r.skipped.length) { setText(""); onDone(); }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Import contacts" description="Paste CSV lines: name, company, number (more numbers in the next columns), or a file exported from here."
      footer={<><Button onClick={onClose} disabled={busy}>Close</Button><Button variant="primary" loading={busy} disabled={!text.trim()} onClick={submit}>Import</Button></>}>
      <div className="stack stack--sm">
        <TextArea label="CSV" rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder={"Front Office,Example Schools,5735550100\nBus Garage,,5735550199"} />
        <Checkbox label="Replace all my contacts with this list" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
        <label className={buttonClass("secondary", "sm")} style={{ cursor: "pointer", alignSelf: "flex-start" }}>
          <Icon name="upload" size={14} /> Choose a file
          <input type="file" accept=".csv,text/csv,text/plain" style={{ display: "none" }} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void f.text().then(setText); }} />
        </label>
        {error ? <Callout tone="danger">{error}</Callout> : null}
        {result?.skipped.length ? <Callout tone="warn" title="Skipped lines"><ul style={{ margin: 0, paddingLeft: 18 }}>{result.skipped.map((s) => <li key={s}>{s}</li>)}</ul></Callout> : null}
      </div>
    </Dialog>
  );
}
