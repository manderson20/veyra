// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Dialog, SelectField, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { TemplateDetail } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** Create an editable local child of a template (docs/DEVICE_PROVISIONING.md §7). */
export function CustomizeDialog({ open, template, onClose, onCreated }: { open: boolean; template: TemplateDetail; onClose: () => void; onCreated: (key: string) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false);
  const platform = session?.is_platform_admin ?? false;

  useOnChange(open, () => {
    if (open) {
      setKey(`local.${template.key.replace(/^poly\./, "")}`);
      setName(`${template.name} (ours)`);
      setOrg(session?.user.home_organization_id ?? "");
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<TemplateDetail>(`/provisioning/templates/${encodeURIComponent(template.key)}/customize`, { key: key.trim(), name: name.trim(), organization_id: org || null });
      toast.success(`Template "${created.name}" created`, "Edit its files on the Edit tab; the original stays untouched.");
      onClose();
      onCreated(created.key);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={`Customize "${template.name}"`}
      description="Creates a local template that inherits from this one and overrides only what you change; for a family, local model templates are created under it too. Official templates are never modified, so updates never conflict with your changes."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="customize-form" loading={busy} disabled={!key.trim() || !name.trim() || (!org && !platform)}>Create editable copy</Button></>}>
      <form id="customize-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Template key" required value={key} error={errors.fields.key} help="Lower-case segments separated by dots or dashes." onChange={(e) => setKey(e.target.value)} />
        <TextField label="Name" required value={name} error={errors.fields.name} onChange={(e) => setName(e.target.value)} />
        <SelectField label="Organization" value={org} error={errors.fields.organization_id} placeholder={platform ? "Platform-wide (all organizations)" : "Choose an organization"}
          options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
