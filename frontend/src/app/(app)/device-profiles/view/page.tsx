// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { EMPTY_PROFILE, ProfileFields, profileBody, profileDraft, type ProfileDraft } from "@/components/devices/ProfileFields";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { DeviceProfile } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useProfileOptions } from "@/hooks/useProfileOptions";
import { useSession } from "@/hooks/useSession";

function ProfileView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const profile = useApiData<DeviceProfile>(id ? `/device-profiles/${encodeURIComponent(id)}` : null);
  const editable = can("devices.write");
  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_PROFILE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const options = useProfileOptions(profile.data?.organization_id ?? "", draft.template_key || undefined);

  useOnChange(profile.data, (p) => { if (p) setDraft(profileDraft(p)); });

  if (!id) return <ErrorState title="No profile selected" error={{ message: "Open a profile from the list." }} />;
  if (profile.error) return <ErrorState title="Could not load profile" error={profile.error} onRetry={profile.reload} />;
  if (!profile.data) return <LoadingState />;
  const p = profile.data;
  const dirty = JSON.stringify(profileBody(draft)) !== JSON.stringify(profileBody(profileDraft(p)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      profile.setData(await api.patch<DeviceProfile>(`/device-profiles/${p.id}`, profileBody(draft)));
      toast.success("Profile saved", "Phones pick up the change at their next provisioning check, or use Reprovision on a device.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/device-profiles/${p.id}`);
      toast.success(`Profile "${p.name}" deleted`);
      router.push("/device-profiles/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader back={{ href: "/device-profiles/", label: "Device profiles" }} title={p.name}
        description={<span className="row"><span>{p.organization_name}</span>{p.site_name ? <span className="subtle">· {p.site_name}</span> : null}{p.problems.length ? <Badge tone="warn" icon="alert">{p.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge>}</span>}
        actions={editable ? <Button variant="ghost" icon="trash" onClick={() => setDeleting(true)} disabled={p.devices > 0} title={p.devices > 0 ? "Move its phones to another profile first" : undefined}>Delete</Button> : null} />
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Profile" subtitle={editable ? undefined : "You can view but not change this profile."}>
          <form className="stack stack--sm" onSubmit={save}>
            <ProfileFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} templates={options.templates} template={options.template}
              zones={options.zones} sites={options.sites} firmware={options.firmware} errors={errors.fields} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="Models served">
            {Object.keys(p.models).length ? (
              <dl className="dl">{Object.entries(p.models).map(([model, key]) => <span key={model} style={{ display: "contents" }}><dt>{model}</dt><dd><a className="mono" href={`/provisioning/view/?key=${encodeURIComponent(key)}`} onClick={(e) => { e.preventDefault(); router.push(`/provisioning/view/?key=${encodeURIComponent(key)}`); }}>{key}</a></dd></span>)}</dl>
            ) : <p className="muted">No model template under this family yet.</p>}
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Phones</dt><dd>{p.devices} <a href={`/devices/?profile=${p.id}`} onClick={(e) => { e.preventDefault(); router.push(`/devices/?profile=${p.id}`); }}>view</a></dd>
              <dt>Firmware</dt><dd>{p.firmware ? `${p.firmware.manufacturer ?? ""} ${p.firmware.version} (${p.firmware.filename})` : "Phones keep their current firmware"}</dd>
              <dt>Created</dt><dd>{formatDateTime(p.created_at)}</dd>
              <dt>Updated</dt><dd>{formatDateTime(p.updated_at)}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the profile "${p.name}"?`} confirmLabel="Delete profile" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Profiles with phones cannot be deleted.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ProfileView /></Suspense>;
}
