// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { clock, DIRECTION, party } from "@/components/calls/format";
import { PickList } from "@/components/calls/PickList";
import { RecordingPlayer } from "@/components/calls/RecordingPlayer";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  Dialog,
  EmptyState,
  IconButton,
  PageHeader,
  Pagination,
  SelectField,
  Switch,
  TabPanel,
  Tabs,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime } from "@/lib/format";
import type {
  CallQueue,
  CallRecordingItem,
  Extension,
  InboundRoute,
  Page,
  Prompt,
  RecordingPolicy,
  RecordingPolicyInput,
  RingGroup,
} from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 50;

function directions(p: { inbound: boolean; outbound: boolean; internal: boolean }) {
  return [p.inbound && "inbound", p.outbound && "outbound", p.internal && "internal"].filter(Boolean).join(", ") || "none";
}

function PolicyDialog({ open, onClose, onSaved, policy }: { open: boolean; onClose: () => void; onSaved: () => void; policy?: RecordingPolicy }) {
  const toast = useToast();
  const errors = useFormErrors();
  const { session } = useSession();
  const { organizations } = useOrganizationOptions(open && !policy);
  const [org, setOrg] = useState("");
  const [form, setForm] = useState<RecordingPolicyInput | null>(null);
  const [busy, setBusy] = useState(false);
  const orgId = policy?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const q = { organization_id: orgId, limit: 500 };
  const selected = form?.scope === "selected";
  const extensions = useApiData<Page<Extension>>(open && orgId && selected ? "/extensions" : null, q);
  const groups = useApiData<Page<RingGroup>>(open && orgId && selected ? "/ring-groups" : null, q);
  const queues = useApiData<Page<CallQueue>>(open && orgId && selected ? "/queues" : null, q);
  const routes = useApiData<Page<InboundRoute>>(open && orgId && selected ? "/routing/inbound" : null, q);
  const prompts = useApiData<Page<Prompt>>(open && orgId ? "/prompts" : null, q);

  useOnChange(open, () => {
    if (!open) return;
    setOrg(policy?.organization_id ?? session?.user.home_organization_id ?? "");
    setForm(policy ? { ...policy } : {
      organization_id: "", name: "", is_enabled: true, inbound: true, outbound: false, internal: false, scope: "all",
      extension_ids: [], ring_group_ids: [], queue_ids: [], inbound_route_ids: [], announcement_prompt_id: null, retention_days: 90,
    });
    errors.clear();
  });
  if (!form) return null;
  const set = <K extends keyof RecordingPolicyInput>(k: K, v: RecordingPolicyInput[K]) => setForm({ ...form, [k]: v });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = { ...form, organization_id: orgId, name: form.name.trim(), retention_days: Number(form.retention_days) };
      if (policy) {
        const { organization_id: _ignored, ...patch } = body;
        void _ignored;
        await api.patch(`/recording-policies/${policy.id}`, patch);
      } else {
        await api.post("/recording-policies", body);
      }
      toast.success(policy ? "Policy saved" : "Policy added", "Deploy changes to apply it to the phone system.");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={policy ? `Edit "${policy.name}"` : "New recording policy"}
      description="Which calls of an organization are recorded, what callers hear first, and how long recordings are kept."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="rec-policy-form" loading={busy} disabled={!orgId || !form.name.trim()}>{policy ? "Save" : "Add policy"}</Button></>}>
      <form id="rec-policy-form" className="stack stack--sm" onSubmit={submit}>
        {!policy && organizations.length > 1 ? (
          <SelectField label="Organization" required value={orgId} placeholder="Choose an organization" error={errors.fields.organization_id}
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={form.name} error={errors.fields.name} placeholder="e.g. Front office lines" onChange={(e) => set("name", e.target.value)} />
        <div className="field">
          <span className="field__label">Directions</span>
          <Checkbox label="Inbound (from outside)" checked={form.inbound} onChange={(e) => set("inbound", e.target.checked)} />
          <Checkbox label="Outbound (to outside)" checked={form.outbound} onChange={(e) => set("outbound", e.target.checked)} />
          <Checkbox label="Internal (phone to phone)" checked={form.internal} onChange={(e) => set("internal", e.target.checked)} />
        </div>
        <SelectField label="Which calls" value={form.scope}
          options={[{ value: "all", label: "Every call of the organization in these directions" }, { value: "selected", label: "Only calls of the phones, groups, queues and numbers chosen below" }]}
          onChange={(e) => set("scope", e.target.value as "all" | "selected")} />
        {selected ? (
          <div className="grid grid--2">
            <PickList label="Phones" error={errors.fields.extension_ids} value={form.extension_ids} onChange={(v) => set("extension_ids", v)}
              options={(extensions.data?.items ?? []).map((x) => ({ id: x.id, label: `${x.number} ${x.display_name}` }))} />
            <PickList label="Ring groups" error={errors.fields.ring_group_ids} value={form.ring_group_ids} onChange={(v) => set("ring_group_ids", v)}
              options={(groups.data?.items ?? []).map((x) => ({ id: x.id, label: `${x.number} ${x.name}` }))} />
            <PickList label="Queues" error={errors.fields.queue_ids} value={form.queue_ids} onChange={(v) => set("queue_ids", v)}
              options={(queues.data?.items ?? []).map((x) => ({ id: x.id, label: `${x.number} ${x.name}` }))} />
            <PickList label="Inbound numbers (DIDs)" error={errors.fields.inbound_route_ids} value={form.inbound_route_ids} onChange={(v) => set("inbound_route_ids", v)}
              options={(routes.data?.items ?? []).map((x) => ({ id: x.id, label: x.did }))} />
          </div>
        ) : null}
        <SelectField label="Announcement" value={form.announcement_prompt_id ?? ""} placeholder="None" error={errors.fields.announcement_prompt_id}
          help="Played to the caller before the call connects, for example “This call may be recorded”. Upload it under Telephony → Audio. Check what your district and the law require."
          options={(prompts.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))}
          onChange={(e) => set("announcement_prompt_id", e.target.value || null)} />
        <TextField label="Keep recordings (days)" type="number" min={1} max={3650} value={form.retention_days} error={errors.fields.retention_days}
          help="Recordings are deleted after this, unless held." onChange={(e) => set("retention_days", Number(e.target.value))} />
        <Switch label="Enabled" checked={form.is_enabled} onChange={(e) => set("is_enabled", e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function Policies() {
  const toast = useToast();
  const { can } = useSession();
  const list = useApiData<Page<RecordingPolicy>>("/recording-policies", { limit: 200 });
  const [editing, setEditing] = useState<RecordingPolicy | "new" | null>(null);
  const [removing, setRemoving] = useState<RecordingPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = can("recording_policies.write");
  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await api.del(`/recording-policies/${removing.id}`);
      toast.success("Policy removed", "Deploy changes to stop recording these calls.");
      setRemoving(null);
      list.reload();
    } catch (err) {
      toast.error("Not removed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const columns: Column<RecordingPolicy>[] = [
    { key: "name", header: "Policy", render: (p) => <><span className="table__primary">{p.name}</span><span className="table__secondary" style={{ display: "block" }}>{p.organization_name}</span></> },
    { key: "what", header: "Records", render: (p) => <>{directions(p)} · {p.scope === "all" ? "every call" : "chosen calls"}</> },
    { key: "keep", header: "Kept", render: (p) => `${p.retention_days} days` },
    { key: "state", header: "State", render: (p) => <>{p.is_enabled ? <Badge tone="ok">On</Badge> : <Badge tone="neutral">Off</Badge>}{p.problems.length ? <> <Badge tone="warn">{p.problems.length === 1 ? "1 note" : `${p.problems.length} notes`}</Badge></> : null}</> },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (p) => editable ? (
        <span className="row" style={{ gap: 4 }}>
          <IconButton size="sm" icon="settings" label={`Edit ${p.name}`} onClick={() => setEditing(p)} />
          <IconButton size="sm" icon="trash" label={`Remove ${p.name}`} onClick={() => setRemoving(p)} />
        </span>
      ) : null,
    },
  ];
  return (
    <Card title="Policies" subtitle="Nothing is recorded until a policy says so. Changes take effect when you deploy."
      actions={editable ? <Button icon="plus" onClick={() => setEditing("new")}>New policy</Button> : null} flush>
      <DataTable columns={columns} rows={list.data?.items} rowKey={(p) => p.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Recording policies" onRowClick={editable ? (p) => setEditing(p) : undefined} rowLabel={(p) => `Edit ${p.name}`}
        empty={<EmptyState icon="record" title="No calls are recorded" compact>Add a policy to record inbound, outbound or internal calls.</EmptyState>} />
      {list.data?.items.some((p) => p.problems.length) ? (
        <div style={{ padding: "0 16px 16px" }}>
          <Callout tone="warn" title="Notes">
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {list.data.items.flatMap((p) => p.problems.map((m) => <li key={`${p.id}${m}`}>{p.name}: {m}</li>))}
            </ul>
          </Callout>
        </div>
      ) : null}
      <PolicyDialog open={editing !== null} policy={editing && editing !== "new" ? editing : undefined} onClose={() => setEditing(null)} onSaved={list.reload} />
      <ConfirmDialog open={removing !== null} title={`Remove "${removing?.name ?? ""}"?`} confirmLabel="Remove" tone="danger" busy={busy} onConfirm={remove} onCancel={() => setRemoving(null)}>
        <p>These calls are no longer recorded once you deploy. Recordings already made are kept until their retention date.</p>
      </ConfirmDialog>
    </Card>
  );
}

function Recordings() {
  const toast = useToast();
  const { can } = useSession();
  const [offset, setOffset] = useState(0);
  const [playing, setPlaying] = useState<CallRecordingItem | null>(null);
  const list = useApiData<Page<CallRecordingItem>>("/recordings", { limit: LIMIT, offset });
  const manage = can("recordings.manage");
  const hold = async (r: CallRecordingItem) => {
    try {
      await api.post(`/recordings/${r.id}/hold`, { held: !r.held });
      toast.success(r.held ? "Hold released" : "Recording held", r.held ? "It will be deleted at its retention date." : "It will not be deleted until released.");
      list.reload();
    } catch (err) {
      toast.error("Not changed", errorMessage(err));
    }
  };
  const columns: Column<CallRecordingItem>[] = [
    { key: "when", header: "Call", render: (r) => <span className="nowrap">{formatDateTime(r.started_at ?? r.created_at)}</span> },
    { key: "dir", header: <span className="sr-only">Direction</span>, render: (r) => (r.direction ? DIRECTION[r.direction].label : "—") },
    { key: "from", header: "From", render: (r) => r.conference_name ? <span><Badge tone="neutral" icon="users">Conference</Badge> {r.conference_name}</span> : party(r.from_number, r.from_name) },
    { key: "to", header: "To", render: (r) => r.conference_name ? <span className="subtle">Whole room</span> : party(r.to_number, null) },
    { key: "len", header: "Length", render: (r) => <span className="mono">{clock(r.duration_seconds)}</span> },
    { key: "keep", header: "Deleted on", render: (r) => (r.held ? <Badge tone="info">Held</Badge> : r.delete_after ? <span className="nowrap">{formatDateTime(r.delete_after)}</span> : "—") },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (r) => (
        <span className="row" style={{ gap: 4 }}>
          <Button size="sm" icon="play" onClick={() => setPlaying(r)}>Listen</Button>
          {manage ? <Button size="sm" onClick={() => hold(r)}>{r.held ? "Release" : "Hold"}</Button> : null}
        </span>
      ),
    },
  ];
  return (
    <Card title="Recordings" subtitle="Every listening and download is written to the audit log." flush>
      <DataTable columns={columns} rows={list.data?.items} rowKey={(r) => r.id} loading={list.loading} error={list.error} onRetry={list.reload}
        caption="Recordings" empty={<EmptyState icon="record" title="No recordings" compact>Recordings appear a minute after a recorded call ends.</EmptyState>}
        pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null} />
      <Dialog open={playing !== null} onClose={() => setPlaying(null)} title="Recording" description={playing ? `${formatDateTime(playing.started_at ?? playing.created_at)} · ${formatBytes(playing.size_bytes)}` : undefined}>
        {playing ? <RecordingPlayer id={playing.id} /> : null}
      </Dialog>
    </Card>
  );
}

export default function RecordingPage() {
  const { can } = useSession();
  const canListen = can("recordings.read") || can("recordings.read_own");
  const [tab, setTab] = useState(canListen ? "recordings" : "policies");
  const tabs = [
    ...(canListen ? [{ id: "recordings", label: "Recordings" }] : []),
    ...(can("recording_policies.read") ? [{ id: "policies", label: "Policies" }] : []),
  ];
  return (
    <div className="stack">
      <PageHeader title="Call recording" description="What is recorded, for how long, and the recordings themselves." />
      {tabs.length > 1 ? <Tabs idBase="rec" active={tab} onChange={setTab} tabs={tabs} /> : null}
      <TabPanel idBase="rec" id="recordings" active={tab}><Recordings /></TabPanel>
      <TabPanel idBase="rec" id="policies" active={tab}><Policies /></TabPanel>
    </div>
  );
}
