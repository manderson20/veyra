// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  ErrorState,
  LoadingState,
  PageHeader,
  SelectField,
  Switch,
  TextField,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { timeZones } from "@/lib/timezones";
import type { Organization } from "@/lib/types";
import { ProvisioningCredentialCard } from "@/components/organizations/ProvisioningCredentialCard";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

function OrganizationView() {
  const id = useSearchParams().get("id");
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const org = useApiData<Organization>(id ? `/organizations/${encodeURIComponent(id)}` : null);
  const zones = useMemo(() => timeZones(), []);
  const [name, setName] = useState("");
  const [tz, setTz] = useState("UTC");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);

  useOnChange(org.data, (o) => {
    if (o) {
      setName(o.name);
      setTz(o.timezone);
      setActive(o.is_active);
    }
  });

  if (!id) return <ErrorState title="No organization selected" error={{ message: "Open an organization from the list." }} />;
  if (org.error) return <ErrorState title="Could not load organization" error={org.error} onRetry={org.reload} />;
  if (!org.data) return <LoadingState />;
  const o = org.data;
  const editable = can("organizations.write");
  const dirty = name !== o.name || tz !== o.timezone || active !== o.is_active;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const updated = await api.patch<Organization>(`/organizations/${o.id}`, { name: name.trim(), timezone: tz, is_active: active });
      org.setData(updated);
      toast.success("Organization saved");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/organizations/", label: "Organizations" }}
        title={o.name}
        description={<span className="row"><span className="mono">{o.slug}</span><Badge tone={o.is_active ? "ok" : "neutral"}>{o.is_active ? "Active" : "Inactive"}</Badge></span>}
      />
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Details" subtitle={editable ? undefined : "You can view but not change this organization."}>
          <form className="stack stack--sm" onSubmit={save}>
            <TextField label="Name" required value={name} disabled={!editable} error={errors.fields.name} onChange={(e) => setName(e.target.value)} />
            <TextField label="Short name" value={o.slug} disabled help="The short name cannot be changed." />
            <SelectField label="Time zone" value={tz} disabled={!editable} options={zones.map((z) => ({ value: z, label: z.replace(/_/g, " ") }))} onChange={(e) => setTz(e.target.value)} />
            <Switch label="Active" description="Inactive organizations are kept but cannot be used for new configuration." checked={active} disabled={!editable} onChange={(e) => setActive(e.target.checked)} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? (
              <div className="form-actions">
                <Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button>
              </div>
            ) : null}
          </form>
        </Card>
        <Card title="Information">
          <dl className="dl">
            <dt>Organization ID</dt><dd className="mono">{o.id}</dd>
            <dt>Created</dt><dd>{formatDateTime(o.created_at)}</dd>
          </dl>
          <div style={{ marginTop: 16 }}>
            <Callout tone="neutral">Sites are managed under Directory → Sites.</Callout>
          </div>
        </Card>
        {can("devices.read") ? <ProvisioningCredentialCard organizationId={o.id} editable={can("devices.write")} /> : null}
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><OrganizationView /></Suspense>;
}
