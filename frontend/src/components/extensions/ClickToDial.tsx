// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Dialog, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Extension, OriginateResult } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

/** Click-to-dial: ring this extension's phone, then place the call to the number entered. */
export function ClickToDialDialog({ open, onClose, extension }: { open: boolean; onClose: () => void; extension: Extension }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => { setNumber(""); errors.clear(); });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const r = await api.post<OriginateResult>("/calls/originate", { extension_id: extension.id, number: number.trim() });
      toast.success(`Ringing ${r.extension_number}`, r.message);
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const registered = extension.registration?.registered;
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={`Call from ${extension.number}`}
      description="The phone rings first; when it is picked up, the call is placed to the number below."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="click-to-dial" icon="phone" loading={busy} disabled={!number.trim()}>Call</Button></>}>
      <form id="click-to-dial" className="stack stack--sm" onSubmit={submit}>
        {registered === false ? <Callout tone="warn">This phone is not registered right now; the call cannot be placed until it is.</Callout> : null}
        <TextField label="Number to call" required autoFocus inputMode="tel" autoComplete="off" placeholder="e.g. 1002 or *43" value={number} error={errors.fields.number}
          help="Internal extensions and feature codes for now; outside numbers arrive with SIP trunks." onChange={(e) => setNumber(e.target.value)} />
        {errors.message && !errors.fields.number ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
