// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { CopyButton } from "@/components/common/CopyButton";
import {
  Badge,
  Button,
  Callout,
  Card,
  ConfirmDialog,
  ErrorState,
  LoadingState,
  PageHeader,
  SelectField,
  Switch,
  TextField,
  useToast,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { Extension, Page, SipCredentials, User } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

function ExtensionView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const ext = useApiData<Extension>(id ? `/extensions/${encodeURIComponent(id)}` : null);
  const editable = can("extensions.write");
  const users = useApiData<Page<User>>(editable && ext.data ? "/users" : null, { limit: 200 });
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [cidName, setCidName] = useState("");
  const [cidNumber, setCidNumber] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(ext.data, (x) => {
    if (x) {
      setNumber(x.number);
      setName(x.display_name);
      setUserId(x.user_id ?? "");
      setCidName(x.caller_id_name ?? "");
      setCidNumber(x.caller_id_number ?? "");
      setEnabled(x.is_enabled);
    }
  });

  if (!id) return <ErrorState title="No extension selected" error={{ message: "Open an extension from the list." }} />;
  if (ext.error) return <ErrorState title="Could not load extension" error={ext.error} onRetry={ext.reload} />;
  if (!ext.data) return <LoadingState />;
  const x = ext.data;
  const dirty = number !== x.number || name !== x.display_name || userId !== (x.user_id ?? "") || cidName !== (x.caller_id_name ?? "") || cidNumber !== (x.caller_id_number ?? "") || enabled !== x.is_enabled;
  const orgUsers = (users.data?.items ?? []).filter((u) => u.home_organization_id === x.organization_id && (u.is_active || u.id === x.user_id));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const renumbered = number !== x.number;
      ext.setData(await api.patch<Extension>(`/extensions/${x.id}`, {
        number: number.trim(),
        display_name: name.trim(),
        user_id: userId || null,
        caller_id_name: cidName.trim() || null,
        caller_id_number: cidNumber.trim() || null,
        is_enabled: enabled,
      }));
      setChanged((n) => n + 1);
      toast.success("Extension saved", renumbered ? "The SIP user name changed with the number: reconfigure the phone." : "Deploy the configuration to apply the change.");
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
      await api.del(`/extensions/${x.id}`);
      toast.success(`Extension ${x.number} deleted`, "Deploy the configuration to remove it from the engine.");
      router.push("/extensions/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/extensions/", label: "Extensions" }}
        title={<span className="row"><span className="mono">{x.number}</span><span>{x.display_name}</span></span>}
        description={
          <span className="row">
            <span>{x.organization_name}</span>
            <Badge tone={x.is_enabled ? "ok" : "neutral"}>{x.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {x.user_display_name ? <Badge tone="info" icon="users">{x.user_display_name}</Badge> : <Badge tone="outline">Shared phone</Badge>}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Details" subtitle={editable ? undefined : "You can view but not change this extension."}>
          <form className="stack stack--sm" onSubmit={save}>
            <div className="form-grid">
              <TextField label="Extension number" required inputMode="numeric" disabled={!editable} value={number} error={errors.fields.number}
                help="Changing it also changes the SIP user name." onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
              <TextField label="Name" required disabled={!editable} value={name} error={errors.fields.display_name} onChange={(e) => setName(e.target.value)} />
            </div>
            {editable ? (
              <SelectField label="Assigned user" value={userId} error={errors.fields.user_id} placeholder="Shared phone (no user)"
                options={orgUsers.map((u) => ({ value: u.id, label: `${u.display_name} (${u.email})` }))} onChange={(e) => setUserId(e.target.value)} />
            ) : (
              <TextField label="Assigned user" disabled value={x.user_display_name ? `${x.user_display_name} (${x.user_email})` : "Shared phone"} />
            )}
            <div className="form-grid">
              <TextField label="Caller ID name" disabled={!editable} value={cidName} error={errors.fields.caller_id_name} help="Defaults to the name." onChange={(e) => setCidName(e.target.value)} />
              <TextField label="Caller ID number" disabled={!editable} value={cidNumber} error={errors.fields.caller_id_number} help="Defaults to the extension number." onChange={(e) => setCidNumber(e.target.value)} />
            </div>
            <Switch label="Enabled" description="Disabled extensions are left out of the engine configuration at the next deployment." checked={enabled} disabled={!editable} onChange={(e) => setEnabled(e.target.checked)} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          {editable ? <SipCredentialsCard extension={x} onRotated={() => { ext.reload(); setChanged((n) => n + 1); }} /> : null}
          <Card title="Information">
            <dl className="dl">
              <dt>SIP user name</dt><dd className="mono">{x.endpoint_name}</dd>
              <dt>Organization</dt><dd>{x.organization_name} <span className="subtle mono">({x.organization_slug})</span></dd>
              <dt>SIP secret</dt><dd>{x.sip_secret_set ? `Set ${formatRelative(x.sip_secret_changed_at)}` : <Badge tone="warn">Missing</Badge>}</dd>
              <dt>Created</dt><dd>{formatDateTime(x.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(x.updated_at)}</dd>
              <dt>Extension ID</dt><dd className="mono">{x.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog
        open={deleting}
        title={`Delete extension ${x.number}?`}
        confirmLabel="Delete extension"
        tone="danger"
        typeToConfirm={x.number}
        busy={deleteBusy}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => { setDeleting(false); setDeleteError(null); }}
      >
        <p>The phone registered as <span className="mono">{x.endpoint_name}</span> stops working at the next deployment. Type <strong>{x.number}</strong> to confirm.</p>
      </ConfirmDialog>
    </div>
  );
}

function SipCredentialsCard({ extension, onRotated }: { extension: Extension; onRotated: () => void }) {
  const toast = useToast();
  const [creds, setCreds] = useState<SipCredentials | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);
  useOnChange(extension.id, () => { setCreds(null); setError(null); });

  const reveal = async () => {
    setBusy(true);
    setError(null);
    try {
      setCreds(await api.get<SipCredentials>(`/extensions/${extension.id}/sip-credentials`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const rotate = async () => {
    setBusy(true);
    setRotateError(null);
    try {
      setCreds(await api.post<SipCredentials>(`/extensions/${extension.id}/sip-credentials/rotate`));
      setConfirmRotate(false);
      toast.success("SIP secret replaced", "Update the phone, then deploy the configuration.");
      onRotated();
    } catch (err) {
      setRotateError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const ports = creds ? [`UDP ${creds.udp_port}`, creds.tcp_port ? `TCP ${creds.tcp_port}` : null, creds.tls_port ? `TLS ${creds.tls_port}` : null].filter(Boolean).join(", ") : "";
  return (
    <Card title="SIP credentials" subtitle="What the phone registers with. Showing the secret is recorded in the audit log."
      actions={<Button icon="refresh" disabled={busy} onClick={() => setConfirmRotate(true)}>New secret</Button>}>
      <dl className="dl">
        <dt>User name</dt><dd className="row"><span className="mono">{extension.endpoint_name}</span><CopyButton text={extension.endpoint_name} label="Copy user name" /></dd>
        <dt>Secret</dt>
        <dd>
          {creds ? (
            <span className="row"><span className="mono">{creds.secret}</span><CopyButton text={creds.secret} label="Copy secret" /><Button size="sm" onClick={() => setCreds(null)}>Hide</Button></span>
          ) : (
            <Button size="sm" icon="eye" loading={busy} onClick={reveal} disabled={!extension.sip_secret_set}>Show secret</Button>
          )}
        </dd>
        {creds ? <><dt>SIP ports</dt><dd>{ports}</dd></> : null}
      </dl>
      {error ? <Callout tone="danger">{error}</Callout> : null}
      <ConfirmDialog open={confirmRotate} title="Replace the SIP secret?" confirmLabel="Replace secret" tone="danger" busy={busy} error={rotateError}
        onConfirm={rotate} onCancel={() => { setConfirmRotate(false); setRotateError(null); }}>
        <p>The phone using extension <strong>{extension.number}</strong> stops registering until it is given the new secret and the configuration is deployed.</p>
      </ConfirmDialog>
    </Card>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ExtensionView /></Suspense>;
}
