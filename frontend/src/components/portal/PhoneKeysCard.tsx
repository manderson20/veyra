// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Card, Dialog, Icon, SelectField, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Contact, DirectoryEntry, MyDevice, MyDeviceSlot, UserKeyInput } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

const TYPE_LABEL: Record<string, string> = { line: "Line", blf: "Busy lamp", speed_dial: "Speed dial", page: "Page", user: "Open" };

/** The user's phones: locked keys greyed, open slots editable (docs/USER_PORTAL.md §8). */
export function PhoneKeysCard() {
  const toast = useToast();
  const devices = useApiData<MyDevice[]>("/me/devices");
  const [editing, setEditing] = useState<{ device: MyDevice; slot: MyDeviceSlot } | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (device: MyDevice, slot: MyDeviceSlot, key: UserKeyInput | null) => {
    setBusy(true);
    try {
      const updated = await api.put<MyDevice>(`/me/devices/${device.id}/keys`, { keys: { [String(slot.index)]: key } });
      devices.setData((devices.data ?? []).map((d) => (d.id === updated.id ? updated : d)));
      toast.success(key ? `Key ${slot.index} set` : `Key ${slot.index} cleared`, "Your phone picks the change up within a minute.");
      setEditing(null);
    } catch (err) {
      toast.error("Could not save the key", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (devices.error) return <Card title="Phone keys"><Callout tone="danger">{errorMessage(devices.error)}</Callout></Card>;
  if (!devices.data || devices.data.length === 0) return null;
  return (
    <Card title="Phone keys" subtitle="Keys with a lock are set by an administrator and stay. Open slots are yours: a speed dial or a lamp that shows whether a colleague is on the phone.">
      <div className="stack">
        {devices.data.map((d) => (
          <section key={d.id} className="stack stack--sm" aria-label={`${d.manufacturer} ${d.model} ${d.mac_display}`}>
            <p style={{ margin: 0 }}><strong>{d.label || `${d.manufacturer} ${d.model}`}</strong> <span className="subtle mono">{d.mac_display}</span> · extension {d.extension_number}{d.profile_name ? ` · ${d.profile_name}` : ""}{d.user_slots === 0 ? " · no open slots on this phone" : ""}</p>
            <ol className="list-plain" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
              {d.slots.map((s) => (
                <li key={s.index} className="card" style={{ padding: 10, opacity: s.kind === "locked" ? 0.8 : 1 }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <span className="subtle">Key {s.index}</span>
                    {s.kind === "locked" ? <Icon name="lock" size={14} aria-label="Locked by an administrator" /> : <Badge tone="info">Yours</Badge>}
                  </div>
                  <div className="table__primary" style={{ marginTop: 4 }}>{s.type ? (s.label || s.value || TYPE_LABEL[s.type]) : <span className="subtle">Empty</span>}</div>
                  <div className="table__secondary">{s.type ? `${TYPE_LABEL[s.type] ?? s.type}${s.value && s.type !== "line" ? ` · ${s.value}` : ""}` : "Nothing on this key yet"}</div>
                  {s.kind === "user" ? (
                    <div className="row" style={{ marginTop: 6 }}>
                      <Button size="sm" onClick={() => setEditing({ device: d, slot: s })}>{s.type ? "Change" : "Set"}</Button>
                      {s.type ? <Button size="sm" variant="ghost" icon="x" loading={busy} onClick={() => save(d, s, null)}>Clear</Button> : null}
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
      <KeyDialog target={editing} busy={busy} onClose={() => setEditing(null)} onSave={(key) => editing && save(editing.device, editing.slot, key)} />
    </Card>
  );
}

function KeyDialog({ target, busy, onClose, onSave }: { target: { device: MyDevice; slot: MyDeviceSlot } | null; busy: boolean; onClose: () => void; onSave: (key: UserKeyInput) => void }) {
  const contacts = useApiData<Contact[]>(target ? "/me/contacts" : null);
  const dir = useApiData<{ results: DirectoryEntry[] }>(target ? "/directory" : null);
  const [type, setType] = useState<"speed_dial" | "blf">((target?.slot.type as "speed_dial" | "blf") || "speed_dial");
  const [value, setValue] = useState(target?.slot.value ?? "");
  const [label, setLabel] = useState(target?.slot.label ?? "");
  const [contactId, setContactId] = useState("");
  const [ext, setExt] = useState("");
  const pickContact = (id: string) => {
    setContactId(id);
    const c = contacts.data?.find((x) => x.id === id);
    if (c) { setValue(c.numbers[0]?.number ?? ""); if (!label) setLabel(c.name); }
  };
  const pickExt = (number: string) => {
    setExt(number);
    const e = dir.data?.results.find((x) => x.number === number);
    if (e) { setValue(e.number); if (!label) setLabel(e.user_display_name ?? e.name); }
  };
  const valid = value.trim().length > 0;
  return (
    <Dialog open={target !== null} onClose={onClose} busy={busy} title={target ? `Key ${target.slot.index} on ${target.device.label || target.device.model}` : ""}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" loading={busy} disabled={!valid} onClick={() => onSave({ type, label: label.trim() || null, value: value.trim(), contact_id: type === "speed_dial" && contactId ? contactId : null })}>Save key</Button></>}>
      <div className="stack stack--sm">
        <SelectField label="Kind" value={type} options={[{ value: "speed_dial", label: "Speed dial: call a number with one press" }, { value: "blf", label: "Busy lamp: watch a colleague, press to call or pick up" }]} onChange={(e) => { setType(e.target.value as "speed_dial" | "blf"); setValue(""); setContactId(""); setExt(""); }} />
        {type === "speed_dial" ? (
          <>
            {contacts.data?.length ? <SelectField label="From your contacts" value={contactId} placeholder="Choose a contact…" options={contacts.data.filter((c) => c.numbers.length).map((c) => ({ value: c.id, label: `${c.name} (${c.numbers[0]?.number ?? ""})` }))} onChange={(e) => pickContact(e.target.value)} /> : null}
            <TextField label="Number" inputMode="tel" value={value} onChange={(e) => { setValue(e.target.value); setContactId(""); }} placeholder="e.g. 1002 or +1 573 555 0100" />
          </>
        ) : (
          <>
            <SelectField label="Colleague, ring group or queue" value={ext} placeholder="Choose…" options={(dir.data?.results ?? []).map((e) => ({ value: e.number, label: `${e.number} ${e.user_display_name ?? e.name}` }))} onChange={(e) => pickExt(e.target.value)} />
            <TextField label="Number" inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} />
          </>
        )}
        <TextField label="Label on the key" value={label} maxLength={40} onChange={(e) => setLabel(e.target.value)} placeholder="Shown next to the key" />
      </div>
    </Dialog>
  );
}
