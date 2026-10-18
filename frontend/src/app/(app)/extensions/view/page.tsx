// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { ClickToDialDialog } from "@/components/extensions/ClickToDial";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { CallGroupsCard } from "@/components/extensions/CallGroupsCard";
import { DevicesCard } from "@/components/extensions/DevicesCard";
import { VoicemailCard } from "@/components/extensions/VoicemailCard";
import { CopyButton } from "@/components/common/CopyButton";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
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
import type { ClassOfService, Extension, ExtensionState, FollowMe, FollowMeMember, Page, SipCredentials, User } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

function ExtensionView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can, session } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const ext = useApiData<Extension>(id ? `/extensions/${encodeURIComponent(id)}` : null);
  const classes = useApiData<Page<ClassOfService>>(ext.data ? "/classes-of-service" : null, { organization_id: ext.data?.organization_id, limit: 200 });
  const editable = can("extensions.write");
  const users = useApiData<Page<User>>(editable && ext.data ? "/users" : null, { limit: 200 });
  const reloadExt = ext.reload;
  useEffect(() => {
    // live registration state
    const t = window.setInterval(reloadExt, 15_000);
    return () => window.clearInterval(t);
  }, [reloadExt]);
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [cidName, setCidName] = useState("");
  const [cidNumber, setCidNumber] = useState("");
  const [emergencyCid, setEmergencyCid] = useState("");
  const [outCidNumber, setOutCidNumber] = useState("");
  const [outCidName, setOutCidName] = useState("");
  const [intercom, setIntercom] = useState("default");
  const [cos, setCos] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const [dialing, setDialing] = useState(false);

  useOnChange(ext.data, (x) => {
    if (x) {
      setNumber(x.number);
      setName(x.display_name);
      setUserId(x.user_id ?? "");
      setCidName(x.caller_id_name ?? "");
      setCidNumber(x.caller_id_number ?? "");
      setEmergencyCid(x.emergency_caller_id_number ?? "");
      setOutCidNumber(x.outbound_caller_id_number ?? "");
      setOutCidName(x.outbound_caller_id_name ?? "");
      setIntercom(x.intercom ?? "default");
      setCos(x.class_of_service_id ?? "");
      setEnabled(x.is_enabled);
    }
  });

  if (!id) return <ErrorState title="No extension selected" error={{ message: "Open an extension from the list." }} />;
  if (ext.error) return <ErrorState title="Could not load extension" error={ext.error} onRetry={ext.reload} />;
  if (!ext.data) return <LoadingState />;
  const x = ext.data;
  const dirty = number !== x.number || name !== x.display_name || userId !== (x.user_id ?? "") || cidName !== (x.caller_id_name ?? "") || cidNumber !== (x.caller_id_number ?? "") || emergencyCid !== (x.emergency_caller_id_number ?? "") || outCidNumber !== (x.outbound_caller_id_number ?? "") || outCidName !== (x.outbound_caller_id_name ?? "") || intercom !== (x.intercom ?? "default") || cos !== (x.class_of_service_id ?? "") || enabled !== x.is_enabled;
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
        emergency_caller_id_number: emergencyCid.trim() || null,
        outbound_caller_id_number: outCidNumber.trim() || null,
        outbound_caller_id_name: outCidName.trim() || null,
        intercom,
        class_of_service_id: cos || null,
        is_enabled: enabled,
      }));
      setChanged((n) => n + 1);
      toast.success("Extension saved", renumbered ? "The SIP user name changed with the number: reconfigure the phone and deploy." : "If the engine configuration changed, Deploy changes appears in the top bar.");
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
            {x.registration ? (x.registration.registered ? <Badge tone="ok" icon="checkCircle">{x.registration.channels ? `On a call (${x.registration.channels})` : "Registered"}</Badge> : <Badge tone="neutral">Not registered</Badge>) : null}
          </span>
        }
        actions={
          <span className="row">
            {(editable || x.user_id === session?.user.id) && can("calls.originate") ? <Button icon="phone" onClick={() => setDialing(true)}>Call from this phone</Button> : null}
            {editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
          </span>
        }
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
              <TextField label="Caller ID name" disabled={!editable} value={cidName} error={errors.fields.caller_id_name} help="Internal calls. Defaults to the name." onChange={(e) => setCidName(e.target.value)} />
              <TextField label="Caller ID number" disabled={!editable} value={cidNumber} error={errors.fields.caller_id_number} help="Internal calls. Defaults to the extension number." onChange={(e) => setCidNumber(e.target.value)} />
            </div>
            <div className="form-grid">
              <TextField label="Outbound caller ID number" inputMode="tel" disabled={!editable} value={outCidNumber} error={errors.fields.outbound_caller_id_number}
                help="Sent to the carrier on outside calls: one of the organization's numbers (inbound routes) or a number on its allow list. Empty: the route's or the trunk's number." onChange={(e) => setOutCidNumber(e.target.value)} />
              <TextField label="Outbound caller ID name" disabled={!editable} value={outCidName} error={errors.fields.outbound_caller_id_name} help="Sent with the outbound number; carriers may replace it." onChange={(e) => setOutCidName(e.target.value)} />
            </div>
            <TextField label="Emergency caller ID number" inputMode="tel" disabled={!editable} value={emergencyCid} error={errors.fields.emergency_caller_id_number}
              help="Presented on emergency calls (911) instead of the regular caller ID: the building's registered number. Otherwise the emergency route's number is used."
              onChange={(e) => setEmergencyCid(e.target.value)} />
            <SelectField label="Class of service" value={cos} disabled={!editable} error={errors.fields.class_of_service_id} placeholder="None: everything allowed"
              options={(classes.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setCos(e.target.value)}
              help="Which outbound routes and feature codes this phone may use (Telephony → Classes of Service). Needs a deployment." />
            <SelectField label="Intercom" value={intercom} disabled={!editable} options={[{ value: "default", label: "Organization default" }, { value: "allow", label: "Allow: other phones can intercom this one" }, { value: "deny", label: "Deny" }]} onChange={(e) => setIntercom(e.target.value)}
              help="Intercom (the intercom feature code followed by this extension) makes the phone answer on speaker. Needs a deployment." />
            <Switch label="Enabled" description="Disabled extensions are left out of the engine configuration at the next deployment." checked={enabled} disabled={!editable} onChange={(e) => setEnabled(e.target.checked)} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <CallHandlingCard extension={x} editable={editable} onChanged={() => ext.reload()} />
          <FollowMeCard extension={x} editable={editable} />
          {can("voicemail.read") ? <VoicemailCard extension={x} editable={can("voicemail.write")} onChanged={() => setChanged((n) => n + 1)} /> : null}
          {can("groups.read") ? <CallGroupsCard extension={x} /> : null}
          {can("devices.read") ? <DevicesCard extension={x} /> : null}
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
      <ClickToDialDialog open={dialing} onClose={() => setDialing(false)} extension={x} />
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

function CallHandlingCard({ extension, editable, onChanged }: { extension: Extension; editable: boolean; onChanged: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const state = useApiData<ExtensionState>(`/extensions/${extension.id}/state`);
  const [busy, setBusy] = useState(false);
  const [always, setAlways] = useState("");
  const [onBusy, setOnBusy] = useState("");
  const [noAnswer, setNoAnswer] = useState("");
  const [ring, setRing] = useState("30");
  useOnChange(state.data, (v) => {
    if (v) { setAlways(v.cf_always ?? ""); setOnBusy(v.cf_busy ?? ""); setNoAnswer(v.cf_no_answer ?? ""); setRing(String(v.ring_seconds)); }
  });
  const s = state.data;
  const dirty = !!s && (always.trim() !== (s.cf_always ?? "") || onBusy.trim() !== (s.cf_busy ?? "") || noAnswer.trim() !== (s.cf_no_answer ?? "") || ring !== String(s.ring_seconds));
  const put = async (body: Record<string, unknown>, done: string, detail?: string) => {
    setBusy(true);
    errors.clear();
    try {
      state.setData(await api.put<ExtensionState>(`/extensions/${extension.id}/state`, body));
      toast.success(done, detail);
      onChanged();
    } catch (err) {
      errors.set(err);
      toast.error("Could not change the call handling", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    const ringChanged = !!s && ring !== String(s.ring_seconds);
    void put({ cf_always: always.trim(), cf_busy: onBusy.trim(), cf_no_answer: noAnswer.trim(), ...(ringChanged ? { ring_seconds: Number(ring) } : {}) },
      "Call handling saved", ringChanged ? "Forwards take effect at once; the ring time needs a deployment." : "Takes effect at once; no deployment needed.");
  };
  const by = s?.updated_by === "phone" ? "from the phone" : s?.updated_by === "sync" ? "by the engine sync" : "here";
  return (
    <Card title="Call handling" subtitle={s?.updated_at ? `Last changed ${formatRelative(s.updated_at)} ${by}.` : undefined}>
      <form className="stack stack--sm" onSubmit={save}>
        <Switch label="Do Not Disturb" checked={s?.dnd ?? extension.dnd ?? false} disabled={!editable || busy || !s}
          onChange={(e) => void put({ dnd: e.target.checked }, e.target.checked ? "Do Not Disturb on" : "Do Not Disturb off", "Takes effect at once; no deployment needed.")}
          description="Callers hear busy, or the busy greeting when the extension has a voicemail box. From the phone: the Do Not Disturb feature codes; a lamp key on the toggle code shows the state." />
        <div className="form-grid">
          <TextField label="Forward all calls to" inputMode="tel" disabled={!editable || !s} value={always} error={errors.fields.cf_always} onChange={(e) => setAlways(e.target.value)} help="An extension or an outside number. Empty: off." />
          <TextField label="Forward when busy to" inputMode="tel" disabled={!editable || !s} value={onBusy} error={errors.fields.cf_busy} onChange={(e) => setOnBusy(e.target.value)} help="Also used while Do Not Disturb is on." />
          <TextField label="Forward when unanswered to" inputMode="tel" disabled={!editable || !s} value={noAnswer} error={errors.fields.cf_no_answer} onChange={(e) => setNoAnswer(e.target.value)} help="After the ring time below." />
          <TextField label="Ring time (seconds)" type="number" min={5} max={120} disabled={!editable || !s} value={ring} error={errors.fields.ring_seconds} onChange={(e) => setRing(e.target.value)} help="Before voicemail or the no-answer forward. Needs a deployment." />
        </div>
        <p className="subtle">From the phone: *72 / *73 forward all, *90 / *91 on busy, *52 / *53 unanswered (Telephony → Feature Codes). Outside numbers leave through the organization’s outbound routes with this extension’s outbound caller ID.</p>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save forwards</Button></div> : null}
      </form>
    </Card>
  );
}

function FollowMeCard({ extension, editable }: { extension: Extension; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const fm = useApiData<FollowMe>(`/extensions/${extension.id}/follow-me`);
  const [busy, setBusy] = useState(false);
  const [strategy, setStrategy] = useState("ringall");
  const [initial, setInitial] = useState("0");
  const [confirm, setConfirm] = useState(false);
  const [cidMode, setCidMode] = useState("caller");
  const [members, setMembers] = useState<FollowMeMember[]>([]);
  const [dest, setDest] = useState("");
  useOnChange(fm.data, (v) => {
    if (v) { setStrategy(v.strategy); setInitial(String(v.initial_ring_seconds)); setConfirm(v.confirm_calls); setCidMode(v.caller_id_mode); setMembers(v.members.map((m) => ({ ...m }))); setDest(v.no_answer_destination ?? ""); }
  });
  const d = fm.data;
  const body = { strategy, initial_ring_seconds: Number(initial), confirm_calls: confirm, caller_id_mode: cidMode, members: members.map((m) => ({ ...m, target: m.target.trim(), ring_seconds: Number(m.ring_seconds) })), no_answer_destination: dest.trim() || null };
  const dirty = !!d && JSON.stringify(body) !== JSON.stringify({ strategy: d.strategy, initial_ring_seconds: d.initial_ring_seconds, confirm_calls: d.confirm_calls, caller_id_mode: d.caller_id_mode, members: d.members, no_answer_destination: d.no_answer_destination });
  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      await api.put(`/extensions/${extension.id}/state`, { fmfm_enabled: on });
      fm.setData(d ? { ...d, enabled: on } : d);
      toast.success(on ? "Follow me on" : "Follow me off", "Takes effect at once; no deployment needed.");
    } catch (err) {
      toast.error("Could not switch follow me", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      fm.setData(await api.put<FollowMe>(`/extensions/${extension.id}/follow-me`, body));
      toast.success("Follow me saved", "Deploy changes to apply the legs to the phone system.");
    } catch (err) {
      errors.set(err);
      toast.error("Could not save follow me", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const setMember = (i: number, patch: Partial<FollowMeMember>) => setMembers((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  return (
    <Card title="Find me / follow me" subtitle={d?.updated_at ? `Legs last changed ${formatRelative(d.updated_at)}.` : undefined}>
      <form className="stack stack--sm" onSubmit={save}>
        <Switch label="Follow me" checked={d?.enabled ?? false} disabled={!editable || busy || !d || !(d.members.length)} onChange={(e) => void toggle(e.target.checked)}
          description={d && !d.members.length ? "Add at least one number below and save before switching it on." : "Rings the numbers below as well as the phone. From the phone: the follow-me toggle code; a lamp key on it shows the state."} />
        <div className="grid grid--2">
          <SelectField label="Ring" value={strategy} disabled={!editable || !d} options={[{ value: "ringall", label: "All at once" }, { value: "sequential", label: "One after another" }]} onChange={(e) => setStrategy(e.target.value)} />
          <TextField label="Ring the phone alone first (seconds)" type="number" min={0} max={60} disabled={!editable || !d} value={initial} error={errors.fields.initial_ring_seconds} onChange={(e) => setInitial(e.target.value)} help="0 skips it." />
        </div>
        <div className="stack stack--sm">
          {members.map((m, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-end", gap: 8 }}>
              <SelectField label={i === 0 ? "Type" : <span className="sr-only">Type</span>} value={m.type} disabled={!editable} options={[{ value: "extension", label: "Extension" }, { value: "external", label: "Outside number" }]} onChange={(e) => setMember(i, { type: e.target.value as FollowMeMember["type"] })} />
              <TextField label={i === 0 ? "Number" : <span className="sr-only">Number</span>} inputMode="tel" disabled={!editable} value={m.target} error={errors.fields[`members.${i + 1}`]} onChange={(e) => setMember(i, { target: e.target.value })} />
              <TextField label={i === 0 ? "Ring (s)" : <span className="sr-only">Ring seconds</span>} type="number" min={5} max={60} disabled={!editable} value={String(m.ring_seconds)} onChange={(e) => setMember(i, { ring_seconds: Number(e.target.value) })} />
              {editable ? <Button variant="ghost" size="sm" onClick={() => setMembers((ms) => ms.filter((_, j) => j !== i))} aria-label="Remove">Remove</Button> : null}
            </div>
          ))}
          {editable && members.length < 10 ? <div><Button size="sm" icon="plus" onClick={() => setMembers((ms) => [...ms, { type: "external", target: "", ring_seconds: 20 }])}>Add a number</Button></div> : null}
        </div>
        <div className="grid grid--2">
          <SelectField label="Outside numbers see" value={cidMode} disabled={!editable || !d} options={[{ value: "caller", label: "The caller’s number" }, { value: "extension", label: "This extension’s outbound caller ID" }]} onChange={(e) => setCidMode(e.target.value)} />
          <TextField label="When nobody answers, send to extension" inputMode="numeric" disabled={!editable || !d} value={dest} error={errors.fields.no_answer_destination} onChange={(e) => setDest(e.target.value)} help="Empty: this extension’s own no-answer handling (forward, voicemail)." />
        </div>
        <Checkbox label="Outside numbers must press 1 to accept" checked={confirm} disabled={!editable || !d} onChange={(e) => setConfirm(e.target.checked)} description="Keeps a mobile’s voicemail from swallowing the call." />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save follow me</Button></div> : null}
      </form>
    </Card>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ExtensionView /></Suspense>;
}
