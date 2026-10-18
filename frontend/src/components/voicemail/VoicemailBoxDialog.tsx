// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { MemberListEditor, membersFromIds, type MemberDraft } from "@/components/groups/MemberListEditor";
import { Button, Callout, Checkbox, ConfirmDialog, Dialog, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Extension, Page, VoicemailBox, VoicemailBoxCreated, VoicemailBoxInput } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

interface Draft {
  extension_id: string;
  /** Shared inbox: its own number and name. */
  number: string;
  name: string;
  members: MemberDraft[];
  pin: string;
  email: string;
  /** Creation only: leave the address to the extension's user. */
  defaultEmail: boolean;
  attach_audio: boolean;
  delete_after_email: boolean;
  ring_seconds: string;
  operator_extension: string;
  is_enabled: boolean;
}

const EMPTY: Draft = { extension_id: "", number: "", name: "", members: [], pin: "", email: "", defaultEmail: true, attach_audio: true, delete_after_email: false, ring_seconds: "20", operator_extension: "", is_enabled: true };

function fromBox(b: VoicemailBox): Draft {
  return { extension_id: b.extension_id ?? "", number: b.shared ? b.number : "", name: b.shared ? b.name : "", members: membersFromIds(b.members ?? []), pin: "", email: b.email ?? "", defaultEmail: false, attach_audio: b.attach_audio, delete_after_email: b.delete_after_email, ring_seconds: String(b.ring_seconds), operator_extension: b.operator_extension ?? "", is_enabled: b.is_enabled };
}

/** How a box is named in titles and toasts: its extension, or a shared inbox's name. */
function boxName(b: { shared?: boolean; number?: string; name?: string; extension_number: string }): string {
  return b.shared ? `${b.name} (${b.number})` : b.extension_number;
}

/** One PIN shown once, after creation or a reset. */
export function PinReveal({ pin, extension }: { pin: string; extension: string }) {
  return (
    <Callout tone="ok" title={`PIN for extension ${extension}`}>
      <p className="row"><span className="mono" style={{ fontSize: "1.25rem", letterSpacing: "0.1em" }}>{pin}</span><CopyButton text={pin} label="Copy PIN" /></p>
      <p className="subtle">Give it to the user now. It is not shown again; it can be reset here or changed by the user on their account page or from the phone.</p>
    </Callout>
  );
}

/**
 * Create a voicemail box (pick an extension unless `extension` is fixed), a
 * shared inbox with its own number and member phones (docs/PAGING_RECORDINGS.md
 * §5), or edit one. Creation shows the PIN once; editing offers a PIN reset.
 */
export function VoicemailBoxDialog({ open, onClose, onSaved, organizationId, extension, box, shared: sharedNew = false }: {
  open: boolean;
  onClose: () => void;
  onSaved: (box: VoicemailBox) => void;
  /** Creation: which organization's extensions to offer. */
  organizationId?: string;
  /** Creation from an extension page: the extension is fixed. */
  extension?: Extension;
  /** Editing: the existing box. */
  box?: VoicemailBox;
  /** Creation: a shared inbox instead of an extension's box. */
  shared?: boolean;
}) {
  const toast = useToast();
  const errors = useFormErrors();
  const editing = !!box;
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<VoicemailBoxCreated | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetPin, setResetPin] = useState<string | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const shared = editing ? !!box?.shared : sharedNew;
  const orgId = box?.organization_id ?? extension?.organization_id ?? organizationId ?? "";
  const needExtensions = open && orgId && (shared || (!editing && !extension));
  const extensions = useApiData<Page<Extension>>(needExtensions ? "/extensions" : null, { organization_id: orgId, limit: 200 });
  const boxes = useApiData<Page<VoicemailBox>>(open && !editing && !extension && !shared && orgId ? "/voicemail" : null, { organization_id: orgId, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setDraft(box ? fromBox(box) : { ...EMPTY, extension_id: extension?.id ?? "" });
      setCreated(null);
      setResetPin(null);
      setResetError(null);
      setDeleteError(null);
      errors.clear();
    }
  });

  const withBox = new Set((boxes.data?.items ?? []).map((b) => b.extension_id));
  const extOptions = (extensions.data?.items ?? []).filter((x) => !withBox.has(x.id)).map((x) => ({ value: x.id, label: `${x.number} — ${x.display_name}${x.user_display_name ? ` (${x.user_display_name})` : ""}` }));
  const ring = Number(draft.ring_seconds);
  const targetOk = shared ? draft.number.trim() && draft.name.trim() : editing || draft.extension_id;
  const valid = targetOk && Number.isInteger(ring) && ring >= 5 && ring <= 120 && (!draft.pin || /^[0-9]{4,10}$/.test(draft.pin)) && (!draft.delete_after_email || (draft.defaultEmail && !shared) || draft.email.trim());

  const body = (): VoicemailBoxInput => {
    const b: VoicemailBoxInput = {
      attach_audio: draft.attach_audio,
      delete_after_email: draft.delete_after_email,
      ring_seconds: ring,
      operator_extension: draft.operator_extension.trim() || null,
      is_enabled: draft.is_enabled,
    };
    if (shared) {
      if (!editing) b.organization_id = orgId;
      b.number = draft.number.trim();
      b.name = draft.name.trim();
      b.members = draft.members.map((m) => m.extension_id);
    } else if (!editing) {
      b.extension_id = draft.extension_id;
    }
    if (draft.pin) b.pin = draft.pin;
    if (editing || shared || !draft.defaultEmail) b.email = draft.email.trim() || null;
    return b;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      if (editing && box) {
        const saved = await api.patch<VoicemailBox>(`/voicemail/${box.id}`, body());
        toast.success(`${shared ? "Shared inbox" : "Voicemail box of"} ${boxName(saved)} saved`, "Deploy changes to apply it to the phone system.");
        onSaved(saved);
        onClose();
      } else {
        const made = await api.post<VoicemailBoxCreated>("/voicemail", body());
        setCreated(made);
        onSaved(made);
        toast.success(`${shared ? "Shared inbox" : "Voicemail box for"} ${boxName(made)} created`, "Note the PIN, then deploy changes.");
      }
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const doReset = async () => {
    if (!box) return;
    setBusy(true);
    setResetError(null);
    try {
      const r = await api.post<{ pin: string }>(`/voicemail/${box.id}/reset-pin`);
      setResetPin(r.pin);
      setResetting(false);
    } catch (err) {
      setResetError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (!box) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/voicemail/${box.id}`);
      toast.success(`${box.shared ? "Shared inbox" : "Voicemail box of"} ${boxName(box)} deleted`, "Deploy changes to remove it from the phone system.");
      setDeleting(false);
      onSaved({ ...box, id: "" });
      onClose();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const title = created
    ? `${shared ? "Shared inbox" : "Voicemail box for"} ${boxName(created)} created`
    : editing && box ? `${shared ? "Shared inbox" : "Voicemail box of"} ${boxName(box)}`
    : shared ? "New shared inbox"
    : extension ? `Voicemail box for ${extension.number}` : "New voicemail box";
  const description = shared
    ? "A mailbox that belongs to no phone: callers reach it by its number, from inbound routes or from IVR keys. Member phones light their message lamp and can open it from *97 (choosing the inbox) or by dialling its number. Messages are also sent by email when delivery is configured."
    : "Callers reach the box when the phone does not answer, and from inbound routes or IVR keys that point at it. Messages are also sent by email when delivery is configured.";
  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={title}
      description={created ? undefined : description}
      footer={created ? <Button variant="primary" onClick={onClose}>Done</Button> : (
        <>
          {editing ? <Button variant="danger" icon="trash" disabled={busy} onClick={() => setDeleting(true)}>Delete box</Button> : null}
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="voicemail-box-form" loading={busy} disabled={!valid}>{editing ? "Save changes" : "Create box"}</Button>
        </>
      )}>
      {created ? (
        <div className="stack stack--sm">
          <PinReveal pin={created.pin} extension={boxName(created)} />
          <p className="subtle">Deploy changes so the phone system learns about the box. Dial <span className="mono">*97</span> from the phone to record the greeting and listen to messages.</p>
        </div>
      ) : (
        <form id="voicemail-box-form" className="stack stack--sm" onSubmit={submit}>
          {shared ? (
            <div className="form-grid">
              <TextField label="Name" required autoFocus={!editing} value={draft.name} error={errors.fields.name} placeholder="Attendance line"
                onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <TextField label="Number" required inputMode="numeric" value={draft.number} error={errors.fields.number} help="From the numbering plan; callers and member phones dial it."
                onChange={(e) => setDraft({ ...draft, number: e.target.value.replace(/[^0-9*#]/g, "") })} />
            </div>
          ) : null}
          {!editing && !extension && !shared ? (
            <SelectField label="Extension" required autoFocus value={draft.extension_id} error={errors.fields.extension_id}
              placeholder={extensions.loading ? "Loading extensions…" : extOptions.length ? "Choose an extension" : "Every extension already has a box"}
              options={extOptions} onChange={(e) => setDraft({ ...draft, extension_id: e.target.value })} />
          ) : null}
          {shared ? (
            <MemberListEditor label="Member phones" members={draft.members} extensions={extensions.data?.items ?? []} loading={extensions.loading} onChange={(members) => setDraft({ ...draft, members })}
              error={errors.fields.members} help="Their message lamp follows this inbox as well as their own box." emptyText="No member phones yet: the inbox is reached by its number, routes and IVR keys only." />
          ) : null}
          {resetPin ? <PinReveal pin={resetPin} extension={box ? boxName(box) : ""} /> : null}
          <div className="form-grid">
            <TextField label={editing ? "New PIN" : "PIN"} inputMode="numeric" autoComplete="off" value={draft.pin} error={errors.fields.pin}
              placeholder={editing ? "Leave empty to keep the current PIN" : "Leave empty for a random PIN"} help="4 to 10 digits." onChange={(e) => setDraft({ ...draft, pin: e.target.value.replace(/\D/g, "") })} />
            <TextField label="Ring time (seconds)" type="number" min={5} max={120} required value={draft.ring_seconds} error={errors.fields.ring_seconds}
              help={shared ? "Kept for consistency; a shared inbox answers at once." : "How long the phone rings before voicemail answers."} onChange={(e) => setDraft({ ...draft, ring_seconds: e.target.value })} />
            <TextField label="Operator extension (press 0)" inputMode="numeric" value={draft.operator_extension} error={errors.fields.operator_extension}
              help="A caller who presses 0 while the greeting plays rings this extension; * opens the box. Empty: 0 does nothing." onChange={(e) => setDraft({ ...draft, operator_extension: e.target.value })} />
          </div>
          {!editing && !shared ? (
            <Checkbox label="Use the extension user's email address" description="Unassigned extensions get no email unless one is entered below." checked={draft.defaultEmail}
              onChange={(e) => setDraft({ ...draft, defaultEmail: e.target.checked })} />
          ) : null}
          {editing || shared || !draft.defaultEmail ? (
            <TextField label="Email address for new messages" type="email" autoComplete="off" value={draft.email} error={errors.fields.email}
              placeholder="Empty: messages stay in the box" onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
          ) : null}
          {editing && box && !box.email_delivery_enabled ? <Callout tone="warn">Email delivery is not configured (Settings → Email delivery). Messages stay in the box until it is.</Callout> : null}
          <Checkbox label="Attach the recording to the email" checked={draft.attach_audio} onChange={(e) => setDraft({ ...draft, attach_audio: e.target.checked })} />
          <Checkbox label="Delete the message from the box once it has been emailed" description="The email is then the only copy; needs an address." checked={draft.delete_after_email}
            onChange={(e) => setDraft({ ...draft, delete_after_email: e.target.checked })} />
          {errors.fields.delete_after_email ? <p className="field__error" role="alert">{errors.fields.delete_after_email}</p> : null}
          <Switch label="Enabled" description="A disabled box keeps its settings and messages, but calls no longer land in it." checked={draft.is_enabled} onChange={(e) => setDraft({ ...draft, is_enabled: e.target.checked })} />
          {editing ? (
            <div className="row">
              <Button icon="key" disabled={busy} onClick={() => setResetting(true)}>Reset PIN</Button>
              <span className="subtle">Generates a new random PIN and shows it once.</span>
            </div>
          ) : null}
          {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        </form>
      )}
      <ConfirmDialog open={resetting} title={`Reset the PIN of ${box ? boxName(box) : ""}?`} confirmLabel="Reset PIN" busy={busy} error={resetError} onConfirm={doReset} onCancel={() => { setResetting(false); setResetError(null); }}>
        <p>The current PIN stops working at the next deployment. The new one is shown once.</p>
      </ConfirmDialog>
      <ConfirmDialog open={deleting} title={box?.shared ? `Delete the shared inbox ${boxName(box)}?` : `Delete the voicemail box of ${box?.extension_number}?`} confirmLabel="Delete box" tone="danger" busy={busy} error={deleteError} onConfirm={doDelete} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Routes and IVR keys that point at this box must be changed first. Messages already recorded stay in the phone system&apos;s spool until it is cleaned up.</p>
      </ConfirmDialog>
    </Dialog>
  );
}
