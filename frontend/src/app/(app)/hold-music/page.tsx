// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, Dialog, EmptyState, IconButton, PageHeader, SelectField, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { moveItem } from "@/lib/routing";
import type { HoldMusicInput, HoldMusicSet, Page, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const minutes = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

function SetDialog({ open, onClose, set, onSaved }: { open: boolean; onClose: () => void; set?: HoldMusicSet; onSaved: () => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !set);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [random, setRandom] = useState(false);
  const [source, setSource] = useState<"tracks" | "stream">("tracks");
  const [stream, setStream] = useState("");
  const [tracks, setTracks] = useState<string[]>([]);
  const [adding, setAdding] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = set?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const library = useApiData<Page<Prompt>>(open && effectiveOrg ? "/prompts" : null, { organization_id: effectiveOrg, limit: 200 });

  useOnChange(open, () => {
    if (open) {
      setOrg(set?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(set?.name ?? "");
      setDescription(set?.description ?? "");
      setRandom(set?.random ?? false);
      setSource(set?.stream_url ? "stream" : "tracks");
      setStream(set?.stream_url ?? "");
      setTracks(set?.tracks.map((t) => t.prompt_id) ?? []);
      setAdding("");
      setShowAll(false);
      errors.clear();
    }
  });

  const recordings = library.data?.items ?? [];
  const byId = new Map(recordings.map((p) => [p.id, p]));
  const known = new Map((set?.tracks ?? []).map((t) => [t.prompt_id, t.name]));
  const candidates = recordings.filter((p) => !tracks.includes(p.id) && (showAll || p.kind === "music"));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: HoldMusicInput = { name: name.trim(), description: description.trim() || null, random, tracks, stream_url: source === "stream" ? stream.trim() || null : null };
      if (set) await api.patch<HoldMusicSet>(`/hold-music/${set.id}`, body);
      else await api.post<HoldMusicSet>("/hold-music", { organization_id: effectiveOrg, ...body });
      toast.success(set ? "Hold music set saved" : "Hold music set created", "Deploy changes to apply it to the phone system.");
      onClose();
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={set ? `Edit "${set.name}"` : "New hold music set"}
      description="Recordings from the audio library, played in order (or shuffled) to callers on hold, waiting in a queue, or ringing a group set to play music."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="hold-music-form" loading={busy} disabled={!effectiveOrg || !name.trim() || (source === "stream" && !stream.trim())}>{set ? "Save changes" : "Create set"}</Button></>}>
      <form id="hold-music-form" className="stack stack--sm" onSubmit={submit}>
        {!set && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setTracks([]); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Main office" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        <SelectField label="Source" value={source} options={[{ value: "tracks", label: "Recordings from the audio library" }, { value: "stream", label: "An internet radio stream" }]}
          onChange={(e) => setSource(e.target.value as "tracks" | "stream")} />
        {source === "stream" ? (
          <TextField label="Stream address" required value={stream} error={errors.fields.stream_url} spellCheck={false} placeholder="https://stream.example.org/live.mp3"
            help="An MP3, AAC or Ogg station, decoded by ffmpeg on the server and reconnected when it drops. Use a station you are licensed to play to callers." onChange={(e) => setStream(e.target.value)} />
        ) : null}
        {source === "tracks" ? (<>
        <div className="field">
          <span className="field__label">Recordings</span>
          {tracks.length === 0 ? <p className="subtle">No recordings yet: callers would hear silence.</p> : (
            <ol className="list-plain">
              {tracks.map((id, i) => {
                const p = byId.get(id);
                const label = p?.name ?? known.get(id) ?? "Recording";
                return (
                  <li key={id} className="list-row">
                    <span>
                      <span>{i + 1}. {label}</span>
                      {p ? <span className="subtle" style={{ display: "block" }}>{minutes(p.duration_seconds)}{p.license ? ` · ${p.license}` : " · licence not recorded"}</span> : null}
                    </span>
                    <span className="row" style={{ gap: 4 }}>
                      <IconButton size="sm" icon="chevronUp" label={`Move ${label} up`} disabled={i === 0} onClick={() => setTracks(moveItem(tracks, i, i - 1))} />
                      <IconButton size="sm" icon="chevronDown" label={`Move ${label} down`} disabled={i === tracks.length - 1} onClick={() => setTracks(moveItem(tracks, i, i + 1))} />
                      <IconButton size="sm" icon="trash" label={`Remove ${label}`} onClick={() => setTracks(tracks.filter((t) => t !== id))} />
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
          <div className="row" style={{ alignItems: "flex-end" }}>
            <SelectField label={<span className="sr-only">Add a recording</span>} value={adding}
              placeholder={library.loading ? "Loading the library…" : candidates.length ? "Choose a recording to add" : showAll ? "No more recordings" : "No more hold music recordings"}
              options={candidates.map((p) => ({ value: p.id, label: `${p.name} (${minutes(p.duration_seconds)})` }))} onChange={(e) => setAdding(e.target.value)} />
            <Button icon="plus" disabled={!adding} onClick={() => { setTracks([...tracks, adding]); setAdding(""); }}>Add</Button>
          </div>
          <Checkbox label="Offer every recording, not only those marked as hold music" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          {errors.fields.tracks ? <p className="field__error" role="alert">{errors.fields.tracks}</p> : null}
          <p className="subtle">Upload music under <Link href="/prompts/">Telephony → Audio</Link> with the kind “Hold music”.</p>
        </div>
        <Checkbox label="Shuffle" description="Play the recordings in a random order instead of the listed one." checked={random} onChange={(e) => setRandom(e.target.checked)} />
        </>) : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function HoldMusicPage() {
  const { can } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [org, setOrg] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<HoldMusicSet | undefined>();
  const [deleting, setDeleting] = useState<HoldMusicSet | undefined>();
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const list = useApiData<Page<HoldMusicSet>>("/hold-music", { organization_id: org || undefined, limit: 100 });
  const editable = can("ivr.write");
  const manyOrgs = organizations.length > 1;
  const saved = () => { list.reload(); setChanged((n) => n + 1); };
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/hold-music/${deleting.id}`);
      toast.success(`Hold music set "${deleting.name}" deleted`);
      setDeleting(undefined);
      saved();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<HoldMusicSet>[] = [
    { key: "name", header: "Set", render: (s) => <span><span className="table__primary" style={{ display: "block" }}>{s.name}</span><span className="table__secondary mono">{s.class_name}</span></span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (s: HoldMusicSet) => <span>{s.organization_name}</span> }] : []),
    { key: "tracks", header: "Recordings", render: (s) => s.stream_url ? <span>Stream<span className="table__secondary" style={{ display: "block", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>{s.stream_url}</span></span> : <span>{s.tracks.length}<span className="table__secondary" style={{ display: "block" }}>{minutes(s.tracks.reduce((n, t) => n + t.duration_seconds, 0))}{s.random ? " · shuffled" : ""}</span></span> },
    { key: "use", header: "Used by", render: (s) => s.in_use_by ? <span>{s.in_use_by}</span> : <span className="subtle">—</span> },
    { key: "status", header: "Status", render: (s) => s.problems.length ? <Badge tone="warn" icon="alert">{s.problems[0]}</Badge> : <Badge tone="ok">Ready</Badge> },
    { key: "actions", header: "", render: (s) => editable ? (
      <span className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
        <Button size="sm" onClick={(e) => { e.stopPropagation(); setEditing(s); }}>Edit</Button>
        <Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setDeleting(s); }} aria-label={`Delete ${s.name}`} />
      </span>
    ) : null },
  ];
  return (
    <div className="stack">
      <PageHeader title="Hold music"
        description="Sets of recordings played to callers on hold and in queues. Choose an organization's default set on its page, and a set per call queue or ring group; anything without a set plays the built-in music."
        actions={editable ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New hold music set</Button> : null} />
      <PendingChanges refreshKey={changed + (list.data?.total ?? 0)} />
      <Callout tone="neutral" title="Music licensing">Commercial music played to callers usually needs a public performance licence. The built-in music and Creative Commons or public-domain recordings do not; the licence recorded with each upload is shown in the set.</Callout>
      <Card flush>
        {manyOrgs ? <div className="table-toolbar"><SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} /></div> : null}
        <DataTable columns={columns} rows={list.data?.items} rowKey={(s) => s.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Hold music sets"
          onRowClick={editable ? (s) => setEditing(s) : undefined} rowLabel={(s) => `Edit hold music set ${s.name}`}
          empty={<EmptyState icon="audio" title="No hold music sets yet">{editable ? "Upload music to the audio library, then group it into a set here. Until then callers hear the built-in music." : null}</EmptyState>} />
      </Card>
      <SetDialog open={createOpen} onClose={() => setCreateOpen(false)} onSaved={saved} />
      <SetDialog open={!!editing} set={editing} onClose={() => setEditing(undefined)} onSaved={saved} />
      <ConfirmDialog open={!!deleting} title={`Delete the hold music set "${deleting?.name ?? ""}"?`} confirmLabel="Delete" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>The recordings stay in the audio library. Organizations, queues and ring groups using the set must be changed first.</p>
      </ConfirmDialog>
    </div>
  );
}
