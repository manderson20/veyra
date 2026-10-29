// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { MemberListEditor, membersFromIds, type MemberDraft } from "@/components/groups/MemberListEditor";
import { Button, Callout, Dialog, SelectField, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Extension, Page, PickupGroup } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** Create or edit a pickup group (docs/RING_GROUPS_QUEUES.md §4). */
export function PickupGroupDialog({ open, onClose, group, onSaved }: { open: boolean; onClose: () => void; group?: PickupGroup; onSaved: (g: PickupGroup) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !group);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [members, setMembers] = useState<MemberDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = group?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const extensions = useApiData<Page<Extension>>(open && effectiveOrg ? "/extensions" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(group?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(group?.name ?? "");
      setDescription(group?.description ?? "");
      setMembers(group ? membersFromIds(group.members) : []);
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { name: name.trim(), description: description.trim() || null, members: members.map((m) => m.extension_id) };
      const saved = group
        ? await api.patch<PickupGroup>(`/pickup-groups/${group.id}`, body)
        : await api.post<PickupGroup>("/pickup-groups", { organization_id: effectiveOrg, ...body });
      toast.success(group ? "Pickup group saved" : `Pickup group "${saved.name}" created`, "Deploy changes to apply it to the phones.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={group ? `Edit pickup group "${group.name}"` : "New pickup group"}
      description="Members may answer each other's ringing calls by dialling *8. Directed pickup (** and the extension) works across the organization unless the organization limits it to the same pickup group."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="pg-form" loading={busy} disabled={!effectiveOrg || !name.trim()}>{group ? "Save changes" : "Create group"}</Button></>}>
      <form id="pg-form" className="stack stack--sm" onSubmit={submit}>
        {!group && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setMembers([]); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Front office" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        <MemberListEditor label="Members" members={members} extensions={extensions.data?.items ?? []} loading={extensions.loading} onChange={setMembers} disabled={!effectiveOrg}
          error={errors.fields.members} emptyText="No members yet." help="An extension can be in several pickup groups." />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
