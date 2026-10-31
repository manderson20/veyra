// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { EMPTY_PROFILE, ProfileFields, profileBody, type ProfileDraft } from "@/components/devices/ProfileFields";
import { Button, Callout, Dialog, SelectField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { sameBrand } from "@/lib/brands";
import type { DeviceProfile } from "@/lib/types";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

/** A new template of one brand. */
export function NewTemplateDialog({ brand, open, onClose, onCreated }: { brand: string; open: boolean; onClose: () => void; onCreated: (p: DeviceProfile) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const [org, setOrg] = useState("");
  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_PROFILE);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const options = useProfileOptions(open ? effectiveOrg : "", draft.template_key || undefined);
  // A brand with one family needs no choice.
  const families = options.templates.filter((t) => t.abstract && sameBrand(t.manufacturer, brand));
  const onlyFamily = open && families.length === 1 ? families[0]!.key : "";

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setDraft({ ...EMPTY_PROFILE, template_key: onlyFamily });
      errors.clear();
    }
  });
  useOnChange(onlyFamily, () => { if (onlyFamily) setDraft((d) => (d.template_key ? d : { ...d, template_key: onlyFamily })); });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<DeviceProfile>("/device-profiles", { organization_id: effectiveOrg, ...profileBody(draft) });
      toast.success(`Template "${created.name}" created`, "Choose it for phones under Devices.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={`New ${brand} template`}
      description="Settings, line keys and paging zones for a group of phones. Make one template per building when only the paging differs."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="template-form" loading={busy} disabled={!effectiveOrg || !draft.name.trim() || !draft.template_key}>Create template</Button></>}>
      <form id="template-form" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setDraft((d) => ({ ...d, site_id: "", paging: {} })); }} />
        ) : null}
        <ProfileFields brand={brand} draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} templates={options.templates} template={options.template}
          zones={options.zones} sites={options.sites} firmware={options.firmware} errors={errors.fields} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
