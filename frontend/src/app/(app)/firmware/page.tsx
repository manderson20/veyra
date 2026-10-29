// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, SelectField, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { FirmwareImage } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function UploadDialog({ open, onClose, onUploaded }: { open: boolean; onClose: () => void; onUploaded: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [manufacturer, setManufacturer] = useState("");
  // The manufacturers Veyra has templates for: a profile only offers an image
  // whose manufacturer matches its template's exactly.
  const catalog = useApiData<{ manufacturers: { name: string; models: string[] }[] }>(open ? "/provisioning/models" : null);
  const [version, setVersion] = useState("");
  const [models, setModels] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => { if (open) { setVersion(""); setModels(""); setNotes(""); setFile(null); errors.clear(); } });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    errors.clear();
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("manufacturer", manufacturer.trim());
      form.append("version", version.trim());
      form.append("models", models.trim());
      form.append("notes", notes.trim());
      const image = await api.upload<FirmwareImage>("/provisioning/firmware", form);
      toast.success(`Firmware ${image.version} uploaded`, "Assign it to a device profile to roll it out.");
      onClose();
      onUploaded();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Upload a firmware image"
      description="The vendor's firmware file, as it comes from the vendor (for example the sip.ld file for Poly VVX, or the .rom or .bin file for Yealink and Grandstream). Up to 512 MB; the file keeps its name because phones request it by name."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="fw-form" loading={busy} disabled={!file || !version.trim() || !manufacturer.trim()}>Upload</Button></>}>
      <form id="fw-form" className="stack stack--sm" onSubmit={submit}>
        <div className="field">
          <label className="field__label" htmlFor="fw-file">File</label>
          <input id="fw-file" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          {errors.fields.file ? <p className="field__error">{errors.fields.file}</p> : null}
        </div>
        <div className="form-grid">
          <SelectField label="Manufacturer" required value={manufacturer} error={errors.fields.manufacturer} placeholder="Choose"
            options={(catalog.data?.manufacturers ?? []).map((m) => ({ value: m.name, label: m.name }))} onChange={(e) => setManufacturer(e.target.value)} />
          <TextField label="Version" required value={version} error={errors.fields.version} placeholder="e.g. 6.4.5.1234" onChange={(e) => setVersion(e.target.value)} />
        </div>
        <TextField label="Models" value={models} error={errors.fields.models} placeholder="VVX 411, VVX 450" help="Comma-separated; leave blank when the image fits every model of the manufacturer." onChange={(e) => setModels(e.target.value)} />
        <TextArea label="Notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function EditDialog({ image, onClose, onSaved }: { image: FirmwareImage; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [models, setModels] = useState(image.models.join(", "));
  const [notes, setNotes] = useState(image.notes ?? "");
  const [busy, setBusy] = useState(false);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.patch(`/provisioning/firmware/${image.id}`, { models: models.split(",").map((m) => m.trim()).filter(Boolean), notes: notes.trim() || null });
      toast.success(`Firmware ${image.version} saved`);
      onSaved();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={onClose} busy={busy} title={`Edit ${image.manufacturer} ${image.version}`}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="fw-edit-form" loading={busy}>Save</Button></>}>
      <form id="fw-edit-form" className="stack stack--sm" onSubmit={save}>
        <TextField label="Models" value={models} error={errors.fields.models} placeholder="VVX 411, VVX 450" help="Comma-separated; blank when the image fits every model of the manufacturer." onChange={(e) => setModels(e.target.value)} />
        <TextArea label="Notes" rows={3} value={notes} error={errors.fields.notes} onChange={(e) => setNotes(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export default function FirmwarePage() {
  const { can } = useSession();
  const toast = useToast();
  const list = useApiData<{ items: FirmwareImage[] }>("/provisioning/firmware");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleting, setDeleting] = useState<FirmwareImage | undefined>();
  const [editing, setEditing] = useState<FirmwareImage | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const editable = can("provisioning.write");
  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/provisioning/firmware/${deleting.id}`);
      toast.success(`Firmware ${deleting.version} deleted`);
      setDeleting(undefined);
      list.reload();
    } catch (err) {
      setDeleteError(errorMessage(err));
    } finally {
      setDeleteBusy(false);
    }
  };
  const columns: Column<FirmwareImage>[] = [
    { key: "version", header: "Firmware", render: (f) => <span><span className="table__primary" style={{ display: "block" }}>{f.manufacturer} {f.version}</span><span className="table__secondary mono">{f.filename}</span></span> },
    { key: "models", header: "Models", render: (f) => f.models.length ? f.models.join(", ") : <span className="subtle">All models</span> },
    { key: "size", header: "Size", render: (f) => size(f.size) },
    { key: "use", header: "Assigned to", render: (f) => <span>{f.profiles} profile{f.profiles === 1 ? "" : "s"}, {f.devices} phone{f.devices === 1 ? "" : "s"}</span> },
    { key: "uploaded", header: "Uploaded", render: (f) => <span>{formatDateTime(f.created_at)}{f.uploaded_by ? <span className="table__secondary" style={{ display: "block" }}>by {f.uploaded_by}</span> : null}</span> },
    { key: "sha", header: "SHA-256", render: (f) => <span className="mono" title={f.sha256}>{f.sha256.slice(0, 12)}…</span> },
    ...(editable ? [{ key: "actions", header: "", render: (f: FirmwareImage) => (
      <span className="row" style={{ gap: 4 }}>
        <Button size="sm" variant="ghost" onClick={() => setEditing(f)}>Edit</Button>
        <Button size="sm" variant="ghost" icon="trash" aria-label={`Delete ${f.version}`} disabled={f.profiles + f.devices > 0} onClick={() => setDeleting(f)} />
      </span>
    ) }] : []),
  ];
  return (
    <div className="stack">
      <PageHeader title="Firmware" description="Vendor firmware images served to phones. Assign an image to a device profile (or one phone); phones compare versions at their next check and update."
        actions={editable ? <Button variant="primary" icon="upload" onClick={() => setUploadOpen(true)}>Upload firmware</Button> : null} />
      <Card flush>
        <DataTable columns={columns} rows={list.data?.items} rowKey={(f) => f.id} loading={list.loading} error={list.error} onRetry={list.reload} caption="Firmware images"
          empty={<EmptyState icon="update" title="No firmware uploaded">{editable ? "Upload the vendor's firmware file for the phones you manage, then assign it in a device profile." : null}</EmptyState>} />
      </Card>
      {editing ? <EditDialog key={editing.id} image={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); list.reload(); }} /> : null}
      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={() => list.reload()} />
      <ConfirmDialog open={!!deleting} title={`Delete firmware ${deleting?.version ?? ""}?`} confirmLabel="Delete" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(undefined); setDeleteError(null); }}>
        <p>Phones that already run this version are not affected.</p>
      </ConfirmDialog>
    </div>
  );
}
