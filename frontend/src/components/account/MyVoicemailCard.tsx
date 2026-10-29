// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, Dialog, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { MyVoicemail } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { LocaterField } from "@/components/voicemail/LocaterField";

/** The caller's own voicemail boxes with a PIN change (account page). */
export function MyVoicemailCard() {
  const boxes = useApiData<MyVoicemail[]>("/me/voicemail");
  const [target, setTarget] = useState<MyVoicemail | null>(null);
  const [keys, setKeys] = useState<MyVoicemail | null>(null);
  if (boxes.error || !boxes.data || boxes.data.length === 0) return null;
  return (
    <Card title="Voicemail" subtitle="Your voicemail boxes. Dial *97 from your phone for your own box, or *98 and the number for a shared inbox, to record greetings and listen to messages.">
      <ul className="list-plain">
        {boxes.data.map((b) => (
          <li key={b.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
            <span>
              <span className="table__primary"><span className="mono">{b.extension_number}</span> {b.extension_name}</span>
              <span className="table__secondary" style={{ display: "block" }}>{b.email ? `New messages are emailed to ${b.email}` : "Messages stay in the box"} · rings {b.ring_seconds} s</span>
            </span>
            <span className="row">
              {!b.is_enabled ? <Badge tone="neutral">Disabled</Badge> : null}
              {!b.shared ? <Button size="sm" onClick={() => setKeys(b)}>Greeting keys</Button> : null}
              {!b.shared ? <Button size="sm" icon="key" onClick={() => setTarget(b)}>Change PIN</Button> : null}
            </span>
          </li>
        ))}
      </ul>
      <PinDialog box={target} onClose={() => setTarget(null)} />
      {keys ? <KeysDialog key={keys.id} box={keys} onClose={() => setKeys(null)} onSaved={() => { setKeys(null); boxes.reload(); }} /> : null}
    </Card>
  );
}

function PinDialog({ box, onClose }: { box: MyVoicemail | null; onClose: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(box, () => { setPin(""); setConfirm(""); errors.clear(); });
  const valid = /^[0-9]{4,10}$/.test(pin) && pin === confirm;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!box) return;
    setBusy(true);
    errors.clear();
    try {
      await api.post(`/me/voicemail/${box.id}/pin`, { pin });
      toast.success("Voicemail PIN changed", "It applies when an administrator next deploys changes to the phone system.");
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={box !== null} onClose={onClose} busy={busy} title={`Change the PIN of ${box?.extension_number ?? ""}`}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="my-pin-form" loading={busy} disabled={!valid}>Change PIN</Button></>}>
      <form id="my-pin-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="New PIN" required autoFocus inputMode="numeric" autoComplete="off" value={pin} error={errors.fields.pin} help="4 to 10 digits." onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
        <TextField label="Repeat the PIN" required inputMode="numeric" autoComplete="off" value={confirm} error={confirm && confirm !== pin ? "The PINs differ." : undefined} onChange={(e) => setConfirm(e.target.value.replace(/\D/g, ""))} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

/** What 1 and 2 do while the greeting plays (#131). */
function KeysDialog({ box, onClose, onSaved }: { box: MyVoicemail; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [one, setOne] = useState(box.locater_1 ?? "");
  const [two, setTwo] = useState(box.locater_2 ?? "");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.patch(`/me/voicemail/${box.id}`, { locater_1: one || null, locater_2: two || null });
      toast.success("Greeting keys saved", "They apply when an administrator next deploys changes to the phone system.");
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} busy={busy} title={`Greeting keys of ${box.extension_number}`}
      description="Callers who reach your voicemail can press a key while your greeting plays instead of leaving a message. Say so in your greeting, for example: “press 1 to try my mobile”. Follow me needs your follow-me numbers (My Phone → call handling). 0 and * stay as the administrator set them."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="my-keys-form" loading={busy}>Save</Button></>}>
      <form id="my-keys-form" className="stack stack--sm" onSubmit={submit}>
        <LocaterField digit="1" value={one} followMe onChange={setOne} error={errors.fields.locater_1} />
        <LocaterField digit="2" value={two} followMe={false} onChange={setTwo} error={errors.fields.locater_2} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
