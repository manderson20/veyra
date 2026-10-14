// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { MemberListEditor, membersFromIds, type MemberDraft } from "@/components/groups/MemberListEditor";
import { PAGING_ALLOWED_LABELS } from "@/components/paging/PagingZoneDialog";
import { Button, Callout, Checkbox, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { Extension, Page, PagePriority, PagingAllowed, PagingPage, PagingPageInput, PagingZone, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

export const PRIORITY_LABELS: Record<PagePriority, string> = { normal: "Normal", priority: "Priority (interrupts calls on Poly phones)", emergency: "Emergency" };

/** Create or edit a page (docs/PAGING_RECORDINGS.md §1): zones, live or recorded audio, number and policy. */
export function PageDialog({ open, onClose, page, onSaved }: { open: boolean; onClose: () => void; page?: PagingPage; onSaved: (p: PagingPage) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !page);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [number, setNumber] = useState("");
  const [zoneIds, setZoneIds] = useState<string[]>([]);
  const [audioId, setAudioId] = useState("");
  const [preTone, setPreTone] = useState(true);
  const [repeat, setRepeat] = useState("1");
  const [priority, setPriority] = useState<PagePriority>("normal");
  const [allowed, setAllowed] = useState<PagingAllowed>("everyone");
  const [members, setMembers] = useState<MemberDraft[]>([]);
  const [maxSeconds, setMaxSeconds] = useState("120");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = page?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const zones = useApiData<Page<PagingZone>>(open && effectiveOrg ? "/paging-zones" : null, { organization_id: effectiveOrg, limit: 100 });
  const audio = useApiData<Page<Prompt>>(open && effectiveOrg ? "/prompts" : null, { organization_id: effectiveOrg, limit: 200 });
  const extensions = useApiData<Page<Extension>>(open && effectiveOrg && allowed === "members" ? "/extensions" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(page?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(page?.name ?? "");
      setDescription(page?.description ?? "");
      setNumber(page?.number ?? "");
      setZoneIds(page?.zones.map((z) => z.id) ?? []);
      setAudioId(page?.audio?.id ?? "");
      setPreTone(page?.pre_tone ?? true);
      setRepeat(String(page?.repeat ?? 1));
      setPriority(page?.priority ?? "normal");
      setAllowed(page?.allowed ?? "everyone");
      setMembers(page ? membersFromIds(page.members) : []);
      setMaxSeconds(String(page?.max_seconds ?? 120));
      setEnabled(page?.is_enabled ?? true);
      errors.clear();
    }
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: PagingPageInput = {
        name: name.trim(),
        description: description.trim() || null,
        number: number.trim() || null,
        zones: zoneIds,
        audio_id: audioId || null,
        pre_tone: preTone,
        repeat: Number(repeat) || 1,
        priority,
        allowed,
        members: allowed === "members" ? members.map((m) => m.extension_id) : [],
        max_seconds: Number(maxSeconds) || 120,
        is_enabled: enabled,
      };
      const saved = page
        ? await api.patch<PagingPage>(`/pages/${page.id}`, body)
        : await api.post<PagingPage>("/pages", { organization_id: effectiveOrg, ...body });
      toast.success(page ? "Page saved" : `Page "${saved.name}" created`, "Deploy changes to make it dialable from phones.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const zoneList = zones.data?.items ?? [];
  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={page ? `Edit page "${page.name}"` : "New page"}
      description="A page sends audio into one or more zones: live from the phone that dials its number, or a recording started from Veyra, a bell or the API."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="page-form" loading={busy} disabled={!effectiveOrg || !name.trim()}>{page ? "Save changes" : "Create page"}</Button></>}>
      <form id="page-form" className="stack stack--sm" onSubmit={submit}>
        {!page && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setZoneIds([]); setAudioId(""); }} />
        ) : null}
        <div className="form-grid">
          <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. All call" onChange={(e) => setName(e.target.value)} />
          <TextField label="Number to dial (optional)" inputMode="numeric" value={number} error={errors.fields.number} help="From the numbering plan; leave blank for pages started only by Veyra." onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
        </div>
        <div className="stack stack--sm">
          <span className="field__label">Zones</span>
          {zoneList.length === 0 ? <p className="muted">No paging zones in this organization yet.</p> : null}
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            {zoneList.map((z) => (
              <Checkbox key={z.id} label={<span>{z.name} <span className="subtle">group {z.poly_group}</span></span>} checked={zoneIds.includes(z.id)}
                onChange={(e) => setZoneIds((ids) => (e.target.checked ? [...ids, z.id] : ids.filter((i) => i !== z.id)))} />
            ))}
          </div>
          {errors.fields.zones ? <p className="field__error">{errors.fields.zones}</p> : null}
        </div>
        <div className="form-grid">
          <SelectField label="Audio" value={audioId} error={errors.fields.audio_id} placeholder="Live: the caller's voice"
            help="A recording makes the page startable from Veyra, bells and the API."
            options={(audio.data?.items ?? []).map((p) => ({ value: p.id, label: `${p.name} (${Math.round(p.duration_seconds)} s)` }))} onChange={(e) => setAudioId(e.target.value)} />
          <TextField label="Repeat the recording" type="number" min={1} max={5} value={repeat} disabled={!audioId} error={errors.fields.repeat} onChange={(e) => setRepeat(e.target.value)} />
        </div>
        <div className="form-grid">
          <SelectField label="Priority" value={priority} options={(Object.keys(PRIORITY_LABELS) as PagePriority[]).map((p) => ({ value: p, label: PRIORITY_LABELS[p] }))} onChange={(e) => setPriority(e.target.value as PagePriority)} />
          <TextField label="Longest page (seconds)" type="number" min={5} max={600} value={maxSeconds} error={errors.fields.max_seconds} onChange={(e) => setMaxSeconds(e.target.value)} />
        </div>
        <SelectField label="Who may start it from a phone" value={allowed} options={(Object.keys(PAGING_ALLOWED_LABELS) as PagingAllowed[]).map((a) => ({ value: a, label: PAGING_ALLOWED_LABELS[a] }))} onChange={(e) => setAllowed(e.target.value as PagingAllowed)} />
        {allowed === "members" ? (
          <MemberListEditor label="Phones allowed to start it" members={members} extensions={extensions.data?.items ?? []} loading={extensions.loading} onChange={setMembers} error={errors.fields.members} emptyText="No phones yet." />
        ) : null}
        <TextArea label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="row" style={{ gap: 16 }}>
          <Checkbox label="Play a tone before the page" checked={preTone} onChange={(e) => setPreTone(e.target.checked)} />
          <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
