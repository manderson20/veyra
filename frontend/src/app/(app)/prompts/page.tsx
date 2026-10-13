// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, Dialog, EmptyState, IconButton, PageHeader, Pagination, SearchInput, SelectField, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";
import { formatSeconds } from "@/lib/routing";
import type { Page, Prompt, Recording } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;
const ACCEPT = "audio/wav,audio/x-wav,audio/wave,.wav";

/** Plays one audio URL at a time; a second click stops it. */
function usePlayer() {
  const [playing, setPlaying] = useState<string | null>(null);
  const ref = useRef<HTMLAudioElement | null>(null);
  const toggle = (key: string, url: string) => {
    if (playing === key) {
      ref.current?.pause();
      setPlaying(null);
      return;
    }
    ref.current?.pause();
    const el = new Audio(url);
    el.onended = () => setPlaying((p) => (p === key ? null : p));
    el.onerror = () => setPlaying((p) => (p === key ? null : p));
    ref.current = el;
    setPlaying(key);
    void el.play().catch(() => setPlaying(null));
  };
  useEffect(() => () => ref.current?.pause(), []);
  return { playing, toggle };
}

export default function PromptsPage() {
  const { can, session } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const player = usePlayer();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<Prompt | null>(null);
  const [deleting, setDeleting] = useState<Prompt | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Prompt>>("/prompts", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const recordings = useApiData<Recording[]>("/prompts/recordings", { organization_id: org || undefined });
  const manyOrgs = organizations.length > 1;
  const editable = can("ivr.write");
  const defaultOrg = org || (organizations.length === 1 ? organizations[0]!.id : session?.user.home_organization_id ?? "");

  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/prompts/${deleting.id}`);
      toast.success(`Prompt "${deleting.name}" deleted`);
      setDeleting(null);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };

  const columns: Column<Prompt>[] = [
    {
      key: "play",
      header: <span className="sr-only">Play</span>,
      width: "48px",
      render: (p) => p.file_present ? <IconButton icon={player.playing === p.id ? "stop" : "play"} label={player.playing === p.id ? `Stop ${p.name}` : `Play ${p.name}`} size="sm" onClick={() => player.toggle(p.id, `/api/v1/prompts/${p.id}/audio`)} /> : <Badge tone="danger" icon="alert">No file</Badge>,
    },
    {
      key: "name",
      header: "Prompt",
      render: (p) => (
        <span>
          <span className="table__primary" style={{ display: "block" }}>{p.name}</span>
          <span className="table__secondary">{p.description ?? <span className="mono">{p.slug}</span>}</span>
        </span>
      ),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (p: Prompt) => <span>{p.organization_name}</span> }] : []),
    { key: "len", header: "Length", render: (p) => <span className="mono">{formatSeconds(p.duration_seconds)}</span> },
    { key: "source", header: "Source", render: (p) => <Badge tone="outline" icon={p.source === "recording" ? "mic" : "upload"}>{p.source === "recording" ? "Recorded from a phone" : "Uploaded"}</Badge> },
    { key: "use", header: "Used by", render: (p) => p.in_use_by ? <span>{p.in_use_by} menu{p.in_use_by === 1 ? "" : "s"}</span> : <span className="subtle">—</span> },
    ...(editable ? [{
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      render: (p: Prompt) => (
        <span className="row" style={{ justifyContent: "flex-end" }}>
          <Button size="sm" icon="settings" onClick={() => setEditing(p)}>Edit</Button>
          <IconButton icon="trash" label={`Delete ${p.name}`} size="sm" disabled={p.in_use_by > 0} onClick={() => { setDeleteError(null); setDeleting(p); }} />
        </span>
      ),
    }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Prompts"
        description="Audio that IVR menus play. Upload a WAV file (it is converted to the phone system's format), or dial *95 from a phone to record one, then name it here."
        actions={editable ? <Button variant="primary" icon="upload" onClick={() => setUploadOpen(true)}>Upload prompt</Button> : null}
      />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by name or description" label="Search prompts" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(p) => p.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Prompts"
          empty={<EmptyState icon="audio" title={debounced || org ? "No matching prompts" : "No prompts yet"}>{!debounced && !org && editable ? "Upload a WAV file, or record one from a phone with *95 and adopt it below." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <RecordingsCard recordings={recordings.data} loading={recordings.loading} error={recordings.error} onRetry={recordings.reload} editable={editable} player={player}
        onChanged={() => { recordings.reload(); list.reload(); }} />
      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} organizationId={defaultOrg} organizations={organizations} onCreated={() => list.reload()} />
      <EditPromptDialog prompt={editing} onClose={() => setEditing(null)} onSaved={() => list.reload()} />
      <ConfirmDialog open={deleting !== null} title={`Delete the prompt "${deleting?.name}"?`} confirmLabel="Delete prompt" tone="danger" busy={deleteBusy} error={deleteError}
        onConfirm={remove} onCancel={() => { setDeleting(null); setDeleteError(null); }}>
        <p>The audio file is removed from the server. Menus cannot use a deleted prompt, so prompts in use cannot be deleted.</p>
      </ConfirmDialog>
    </div>
  );
}

function UploadDialog({ open, onClose, organizationId, organizations, onCreated }: {
  open: boolean;
  onClose: () => void;
  organizationId: string;
  organizations: { id: string; name: string }[];
  onCreated: (p: Prompt) => void;
}) {
  const toast = useToast();
  const errors = useFormErrors();
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (open) {
      setOrg(organizationId);
      setName("");
      setDescription("");
      setFile(null);
      errors.clear();
    }
  });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    errors.clear();
    try {
      const form = new FormData();
      form.set("organization_id", org);
      form.set("name", name.trim());
      if (description.trim()) form.set("description", description.trim());
      form.set("file", file);
      const created = await api.upload<Prompt>("/prompts", form);
      toast.success(`Prompt "${created.name}" uploaded`, `${formatSeconds(created.duration_seconds)} long, converted for the phone system.`);
      onCreated(created);
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Upload a prompt"
      description="A WAV file (PCM, 8 or 16 bit, mono or stereo, up to 48 kHz, at most 10 MB and 5 minutes). It is converted to 8 kHz mono, the format phones hear."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="prompt-upload" loading={busy} disabled={!org || !name.trim() || !file}>Upload</Button></>}>
      <form id="prompt-upload" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={org} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Main greeting" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} placeholder="What the prompt says, for the people who edit menus" onChange={(e) => setDescription(e.target.value)} />
        <TextField label="WAV file" required type="file" accept={ACCEPT} error={errors.fields.file} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function EditPromptDialog({ prompt, onClose, onSaved }: { prompt: Prompt | null; onClose: () => void; onSaved: (p: Prompt) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  useOnChange(prompt, (p) => {
    setName(p?.name ?? "");
    setDescription(p?.description ?? "");
    setFile(null);
    errors.clear();
  });
  if (!prompt) return <Dialog open={false} onClose={onClose} title="" />;
  const dirty = name.trim() !== prompt.name || (description.trim() || null) !== prompt.description;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      let saved = prompt;
      if (dirty) saved = await api.patch<Prompt>(`/prompts/${prompt.id}`, { name: name.trim(), description: description.trim() || null });
      if (file) {
        const form = new FormData();
        form.set("file", file);
        saved = await api.upload<Prompt>(`/prompts/${prompt.id}/audio`, form, "PUT");
      }
      toast.success(`Prompt "${saved.name}" saved`, file ? "The new audio plays at once; menus keep pointing at this prompt." : undefined);
      onSaved(saved);
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} busy={busy} title={`Edit "${prompt.name}"`}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="prompt-edit" loading={busy} disabled={!name.trim() || (!dirty && !file)}>Save</Button></>}>
      <form id="prompt-edit" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} help={<>File name <span className="mono">{prompt.slug}.wav</span> stays the same.</>} onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        <TextField label="Replace the audio" type="file" accept={ACCEPT} error={errors.fields.file} help={`Current recording: ${formatSeconds(prompt.duration_seconds)}, ${formatBytes(prompt.size_bytes)}, ${prompt.source === "recording" ? "recorded from a phone" : "uploaded"} ${formatRelative(prompt.updated_at)}.`} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function RecordingsCard({ recordings, loading, error, onRetry, editable, player, onChanged }: {
  recordings: Recording[] | undefined;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  editable: boolean;
  player: ReturnType<typeof usePlayer>;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [adopting, setAdopting] = useState<Recording | null>(null);
  const [deleting, setDeleting] = useState<Recording | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/prompts/recordings/${encodeURIComponent(deleting.file)}`, { organization_id: deleting.organization_id });
      toast.success("Recording discarded");
      setDeleting(null);
      onChanged();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const columns: Column<Recording>[] = [
    {
      key: "play",
      header: <span className="sr-only">Play</span>,
      width: "48px",
      render: (r) => <IconButton icon={player.playing === r.file ? "stop" : "play"} label={player.playing === r.file ? "Stop" : "Play recording"} size="sm"
        onClick={() => player.toggle(r.file, `/api/v1/prompts/recordings/${encodeURIComponent(r.file)}/audio?organization_id=${encodeURIComponent(r.organization_id)}`)} />,
    },
    { key: "when", header: "Recorded", render: (r) => <span>{formatDateTime(r.recorded_at)}<span className="table__secondary" style={{ display: "block" }}>{r.organization_name}</span></span> },
    { key: "ext", header: "From extension", render: (r) => <span className="mono">{r.extension_number}</span> },
    { key: "len", header: "Length", render: (r) => <span className="mono">{formatSeconds(r.duration_seconds)}</span> },
    ...(editable ? [{
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      render: (r: Recording) => (
        <span className="row" style={{ justifyContent: "flex-end" }}>
          <Button size="sm" variant="primary" icon="check" onClick={() => setAdopting(r)}>Name and keep</Button>
          <IconButton icon="trash" label="Discard recording" size="sm" onClick={() => { setDeleteError(null); setDeleting(r); }} />
        </span>
      ),
    }] : []),
  ];
  return (
    <Card title="Recordings from phones" subtitle="Dial *95, record after the tone, press # to stop, then 1 to keep (2 listens again, 3 re-records). Recordings appear here to be named or discarded." flush>
      <DataTable columns={columns} rows={recordings} rowKey={(r) => `${r.organization_id}/${r.file}`} loading={loading} error={error} onRetry={onRetry} caption="Recordings from phones"
        empty={<EmptyState icon="mic" title="No recordings waiting" compact>Record one from any phone with *95.</EmptyState>} />
      <AdoptDialog recording={adopting} onClose={() => setAdopting(null)} onAdopted={onChanged} />
      <ConfirmDialog open={deleting !== null} title="Discard this recording?" confirmLabel="Discard" tone="danger" busy={busy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(null); setDeleteError(null); }}>
        <p>The file is deleted from the server.</p>
      </ConfirmDialog>
    </Card>
  );
}

function AdoptDialog({ recording, onClose, onAdopted }: { recording: Recording | null; onClose: () => void; onAdopted: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(recording, () => { setName(""); setDescription(""); errors.clear(); });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!recording) return;
    setBusy(true);
    errors.clear();
    try {
      const p = await api.post<Prompt>(`/prompts/recordings/${encodeURIComponent(recording.file)}/adopt`, { organization_id: recording.organization_id, name: name.trim(), description: description.trim() || null });
      toast.success(`Prompt "${p.name}" created from the recording`);
      onAdopted();
      onClose();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={recording !== null} onClose={onClose} busy={busy} title="Name the recording" description={recording ? `Recorded from extension ${recording.extension_number}, ${formatSeconds(recording.duration_seconds)} long. It becomes a prompt that menus can play.` : undefined}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="adopt-form" loading={busy} disabled={!name.trim()}>Create prompt</Button></>}>
      <form id="adopt-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. After-hours greeting" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
