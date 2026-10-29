// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import { ClickToDialDialog } from "@/components/extensions/ClickToDial";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { CallGroupsCard } from "@/components/extensions/CallGroupsCard";
import { DevicesCard } from "@/components/extensions/DevicesCard";
import { VoicemailCard } from "@/components/extensions/VoicemailCard";
import { CallHandlingCard } from "@/components/extensions/CallHandlingCard";
import { FollowMeCard } from "@/components/extensions/FollowMeCard";
import { EMPTY_PLACE, PlaceFields, placeBody, placeOf, samePlace, type Place } from "@/components/extensions/PlaceFields";
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
  TabPanel,
  Tabs,
  TextField,
  useToast,
  type TabDef,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { ClassOfService, Extension, ExtensionTemplate, Page, RegistrationContact, SipCredentials, User } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";
import { useUrlTab } from "@/hooks/useUrlTab";

/** The tabs across the top of the page (issue #81); the active one is in the link as ?tab=. */
const TAB_IDS = ["general", "callerid", "handling", "followme", "voicemail", "phones", "groups", "credentials"] as const;

function ExtensionView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can, session } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const ext = useApiData<Extension>(id ? `/extensions/${encodeURIComponent(id)}` : null);
  const classes = useApiData<Page<ClassOfService>>(ext.data ? "/classes-of-service" : null, { organization_id: ext.data?.organization_id, limit: 200 });
  const templates = useApiData<Page<ExtensionTemplate>>(ext.data ? "/extension-templates" : null, { organization_id: ext.data?.organization_id, limit: 200 });
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
  const [faxT38, setFaxT38] = useState(false);
  const [cos, setCos] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [maxReg, setMaxReg] = useState("");
  const [hotline, setHotline] = useState("");
  const [hotlineDelay, setHotlineDelay] = useState("0");
  const [enabled, setEnabled] = useState(true);
  const [place, setPlace] = useState<Place>(EMPTY_PLACE);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const [dialing, setDialing] = useState(false);
  // Cards with their own forms report unsaved edits; a tab switch would lose them.
  const [cardDirty, setCardDirty] = useState<Record<string, boolean>>({});
  const handlingDirty = useCallback((d: boolean) => setCardDirty((c) => (c.handling === d ? c : { ...c, handling: d })), []);
  const followMeDirty = useCallback((d: boolean) => setCardDirty((c) => (c.followme === d ? c : { ...c, followme: d })), []);
  const [tab, setTab] = useUrlTab(TAB_IDS, "general", Object.values(cardDirty).some(Boolean));

  // Reset the form when another extension loads or this one was saved, not on
  // the periodic registration refresh (that would discard edits in progress).
  const loaded = ext.data ? `${ext.data.id}|${ext.data.updated_at}` : null;
  useOnChange(loaded, () => {
    const x = ext.data;
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
      setFaxT38(x.fax_t38 ?? false);
      setCos(x.class_of_service_id ?? "");
      setTemplateId(x.template_id ?? "");
      setMaxReg(x.max_registrations ? String(x.max_registrations) : "");
      setHotline(x.hotline_target ?? "");
      setHotlineDelay(String(x.hotline_delay ?? 0));
      setEnabled(x.is_enabled);
      setPlace(placeOf(x));
    }
  });

  if (!id) return <ErrorState title="No extension selected" error={{ message: "Open an extension from the list." }} />;
  if (ext.error) return <ErrorState title="Could not load extension" error={ext.error} onRetry={ext.reload} />;
  if (!ext.data) return <LoadingState />;
  const x = ext.data;
  const dirty = number !== x.number || name !== x.display_name || userId !== (x.user_id ?? "") || cidName !== (x.caller_id_name ?? "") || cidNumber !== (x.caller_id_number ?? "") || emergencyCid !== (x.emergency_caller_id_number ?? "") || outCidNumber !== (x.outbound_caller_id_number ?? "") || outCidName !== (x.outbound_caller_id_name ?? "") || intercom !== (x.intercom ?? "default") || faxT38 !== (x.fax_t38 ?? false) || cos !== (x.class_of_service_id ?? "") || templateId !== (x.template_id ?? "") || maxReg !== (x.max_registrations ? String(x.max_registrations) : "") || hotline !== (x.hotline_target ?? "") || hotlineDelay !== String(x.hotline_delay ?? 0) || enabled !== x.is_enabled || !samePlace(place, placeOf(x));
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
        fax_t38: faxT38,
        class_of_service_id: cos || null,
        ...(templateId !== (x.template_id ?? "") ? { template_id: templateId || null } : {}),
        max_registrations: maxReg.trim() ? Number(maxReg) : null,
        hotline_target: hotline.trim() || null,
        hotline_delay: Number(hotlineDelay || 0),
        ...placeBody(place),
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

  // The settings form spans several tabs and keeps its values across them;
  // every tab with fields carries the same Save button.
  const saveBar = editable ? (
    <>
      {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="form-actions row">
        {dirty ? <span className="subtle">Unsaved changes</span> : null}
        <Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button>
      </div>
    </>
  ) : null;
  const readOnly = editable ? undefined : "You can view but not change this extension.";

  const tabs: TabDef[] = [
    { id: "general", label: "General" },
    { id: "callerid", label: "Caller ID" },
    { id: "handling", label: "Call handling" },
    { id: "followme", label: "Follow me" },
    ...(can("voicemail.read") ? [{ id: "voicemail", label: "Voicemail" }] : []),
    { id: "phones", label: "Phones" },
    ...(can("groups.read") ? [{ id: "groups", label: "Groups" }] : []),
    ...(editable ? [{ id: "credentials", label: "Credentials" }] : []),
  ];
  const contacts = x.registration?.contacts ?? [];

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
            {dirty ? <Badge tone="warn">Unsaved changes</Badge> : null}
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
      <Tabs idBase="ext" active={tab} onChange={setTab} tabs={tabs} />

      <TabPanel idBase="ext" id="general" active={tab}>
        <div className="stack">
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <Card title="Details" subtitle={readOnly}>
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
              <Switch label="Enabled" description="Disabled extensions are left out of the engine configuration at the next deployment." checked={enabled} disabled={!editable} onChange={(e) => setEnabled(e.target.checked)} />
              {saveBar}
            </form>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>SIP user name</dt><dd className="mono">{x.endpoint_name}</dd>
              <dt>Organization</dt><dd>{x.organization_name} <span className="subtle mono">({x.organization_slug})</span></dd>
              <dt>SIP secret</dt><dd>{x.sip_secret_set ? `Set ${formatRelative(x.sip_secret_changed_at)}` : <Badge tone="warn">Missing</Badge>}</dd>
              <dt>Class of service</dt><dd>{x.class_of_service_name ?? <span className="subtle">None: everything allowed</span>}</dd>
              <dt>Created</dt><dd>{formatDateTime(x.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(x.updated_at)}</dd>
              <dt>Extension ID</dt><dd className="mono">{x.id}</dd>
            </dl>
          </Card>
        </div>
        <Card title="Location" subtitle={readOnly ?? "Where the phone is: its site's emergency route and caller ID, and the address and room an emergency notification gives."}>
          <form className="stack stack--sm" onSubmit={save}>
            <PlaceFields organizationId={x.organization_id} value={place} onChange={setPlace} errors={errors.fields} disabled={!editable} />
            {saveBar}
          </form>
        </Card>
        </div>
      </TabPanel>

      <TabPanel idBase="ext" id="callerid" active={tab}>
        <Card title="Caller ID" subtitle={readOnly ?? "What this phone presents inside the organization, to the carrier, and on emergency calls."}>
          <form className="stack stack--sm" onSubmit={save}>
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
            {saveBar}
          </form>
        </Card>
      </TabPanel>

      <TabPanel idBase="ext" id="handling" active={tab}>
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <CallHandlingCard base={`/extensions/${x.id}`} dnd={x.dnd} editable={editable} onChanged={() => ext.reload()} onDirty={handlingDirty} />
          <Card title="Restrictions" subtitle={readOnly ?? "What this phone may do. Both need a deployment."}>
            <form className="stack stack--sm" onSubmit={save}>
              {(templates.data?.items ?? []).length || x.template_id ? (
                <SelectField label="Extension template" value={templateId} disabled={!editable} error={errors.fields.template_id} placeholder="None: its own settings"
                  options={(templates.data?.items ?? []).map((tpl) => ({ value: tpl.id, label: tpl.name }))} onChange={(e) => setTemplateId(e.target.value)}
                  help={x.template_id && templateId === x.template_id
                    ? (x.locked_fields?.length ? `Locked by the template: ${x.locked_fields.map((f) => f.replace(/_id$/, "").replaceAll("_", " ")).join(", ")}.` : "The template locks nothing.")
                    : "Choosing a template applies all its settings when you save (Telephony → Extension Templates)."} />
              ) : null}
              <SelectField label="Class of service" value={cos} disabled={!editable || !!x.locked_fields?.includes("class_of_service_id")} error={errors.fields.class_of_service_id} placeholder="None: everything allowed"
                options={(classes.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setCos(e.target.value)}
                help="Which outbound routes and feature codes this phone may use (Telephony → Classes of Service)." />
              <SelectField label="Intercom" value={intercom} disabled={!editable || !!x.locked_fields?.includes("intercom")} options={[{ value: "default", label: "Organization default" }, { value: "allow", label: "Allow: other phones can intercom this one" }, { value: "deny", label: "Deny" }]} onChange={(e) => setIntercom(e.target.value)}
                help="Intercom (the intercom feature code followed by this extension) makes the phone answer on speaker." />
              {saveBar}
            </form>
          </Card>
        </div>
      </TabPanel>

      <TabPanel idBase="ext" id="followme" active={tab}>
        <FollowMeCard base={`/extensions/${x.id}`} editable={editable} onDirty={followMeDirty} />
      </TabPanel>

      {can("voicemail.read") ? (
        <TabPanel idBase="ext" id="voicemail" active={tab}>
          <VoicemailCard extension={x} editable={can("voicemail.write")} onChanged={() => setChanged((n) => n + 1)} />
        </TabPanel>
      ) : null}

      <TabPanel idBase="ext" id="phones" active={tab}>
        <div className="grid grid--2" style={{ alignItems: "start" }}>
          <Card title="Registered phones"
            subtitle={x.registration ? `${contacts.length} of ${x.registration_limit ?? 1} registered right now.` : "The telephony engine cannot report registrations."}>
            {contacts.length ? (
              <ul className="list-plain">
                {contacts.map((c) => <RegisteredPhone key={c.uri} contact={c} />)}
              </ul>
            ) : x.registration ? <p className="muted">No phone is registered as <span className="mono">{x.endpoint_name}</span>.</p> : null}
            <form className="stack stack--sm" onSubmit={save} style={{ marginTop: "var(--space-4)" }}>
              <TextField label="Phones that may register" inputMode="numeric" disabled={!editable} value={maxReg} error={errors.fields.max_registrations}
                placeholder={`Automatic (${x.registration_limit ?? 1})`}
                help={`How many phones may register this extension at once, 1 to 16. Empty: as many as are provisioned with it (${x.provisioned_phones ?? 0} today), at least one. Raise it to let a softphone register beside the desk phone. Needs a deployment.`}
                onChange={(e) => setMaxReg(e.target.value.replace(/\D/g, "").slice(0, 2))} />
              <div className="form-grid">
                <TextField label="Hotline number" inputMode="tel" disabled={!editable} value={hotline} error={errors.fields.hotline_target} placeholder="None"
                  help="Lifting the handset dials this number: elevator, lobby, vestibule and emergency phones. Reaches provisioned phones and ATAs at their next check-in." onChange={(e) => setHotline(e.target.value)} />
                <TextField label="Warm-line delay (seconds)" type="number" min={0} max={10} disabled={!editable || !hotline.trim()} value={hotlineDelay} error={errors.fields.hotline_delay}
                  help="0: dials at once. Otherwise the phone waits this long for a digit first (Yealink, Grandstream; Poly dials at once)." onChange={(e) => setHotlineDelay(e.target.value)} />
              </div>
              <Switch label="Fax machine (T.38)" disabled={!editable} checked={faxT38} onChange={(e) => setFaxT38(e.target.checked)}
                description="For a fax machine on an ATA port: Veyra offers T.38 to it, so faxes relay end to end over a trunk with T.38 on. Off: the fax travels as audio (G.711), which works with any trunk. Set the ATA's fax mode to match. Needs a deployment." />
              {saveBar}
            </form>
          </Card>
          {can("devices.read") ? <DevicesCard extension={x} /> : null}
        </div>
      </TabPanel>

      {can("groups.read") ? (
        <TabPanel idBase="ext" id="groups" active={tab}>
          <CallGroupsCard extension={x} />
        </TabPanel>
      ) : null}

      {editable ? (
        <TabPanel idBase="ext" id="credentials" active={tab}>
          <SipCredentialsCard extension={x} onRotated={() => { ext.reload(); setChanged((n) => n + 1); }} />
        </TabPanel>
      ) : null}

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

function address(host: string | null, port: number | null) {
  if (!host) return null;
  const h = host.includes(":") ? `[${host}]` : host;
  return port ? `${h}:${port}` : h;
}

/** One registered contact: where it registers from, what it reports, when it expires. */
function RegisteredPhone({ contact: c }: { contact: RegistrationContact }) {
  const source = address(c.source_host, c.source_port);
  const own = address(c.contact_host, c.contact_port);
  return (
    <li style={{ padding: "6px 0" }}>
      <span className="row">
        <span className="mono">{source ?? own ?? c.uri}</span>
        {c.nat ? <Badge tone="warn">Behind NAT</Badge> : null}
        {c.status ? <Badge tone={c.status === "Avail" ? "ok" : c.status === "Unavail" ? "danger" : "neutral"}>{c.status === "Avail" ? "Reachable" : c.status === "Unavail" ? "Unreachable" : "Not checked"}</Badge> : null}
      </span>
      <span className="table__secondary" style={{ display: "block" }}>
        {c.nat && own ? `phone says ${own} · ` : ""}{c.user_agent ?? "unknown phone"}{c.transport ? ` · ${c.transport.toUpperCase()}` : ""}{c.expires_at ? ` · expires ${formatRelative(c.expires_at)}` : ""}
      </span>
    </li>
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
