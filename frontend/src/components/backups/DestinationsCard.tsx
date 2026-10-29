// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Badge, Button, Callout, Card, ConfirmDialog, Dialog, EmptyState, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { BackupDestination, BackupDestinationTest, BackupSettings } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";

type Kind = BackupDestination["kind"];

const KINDS: { value: Kind; title: string; text: string }[] = [
  { value: "directory", title: "Folder", text: "A share mounted on this server (NFS or Windows/SMB), such as a NAS." },
  { value: "sftp", title: "SFTP server", text: "Any server reachable over SSH: a NAS, a Linux server, a hosting provider." },
  { value: "s3", title: "S3-compatible storage", text: "Amazon S3, Backblaze B2, Wasabi, Cloudflare R2, MinIO and others." },
];

const KIND_LABEL: Record<Kind, string> = { directory: "Folder", sftp: "SFTP", s3: "S3" };

interface Draft {
  kind: Kind;
  name: string;
  enabled: boolean;
  ownKeep: boolean;
  daily: string;
  weekly: string;
  upgrades: string;
  path: string;
  host: string;
  port: string;
  username: string;
  endpoint: string;
  bucket: string;
  region: string;
  prefix: string;
  access_key_id: string;
  secret_access_key: string;
  addressing: "path" | "virtual";
}

function draftOf(d: BackupDestination | null, keep: BackupSettings["keep"]): Draft {
  const k = d?.keep ?? keep;
  return {
    kind: d?.kind ?? "directory",
    name: d?.name ?? "",
    enabled: d?.enabled ?? true,
    ownKeep: !!d?.keep,
    daily: String(k.daily_days),
    weekly: String(k.weekly_weeks),
    upgrades: String(k.upgrades),
    path: d?.path ?? "",
    host: d?.host ?? "",
    port: String(d?.port ?? 22),
    username: d?.username ?? "",
    endpoint: d?.endpoint ?? "",
    bucket: d?.bucket ?? "",
    region: d?.region ?? "",
    prefix: d?.prefix ?? "",
    access_key_id: d?.access_key_id ?? "",
    secret_access_key: "",
    addressing: d?.addressing ?? "path",
  };
}

function bodyOf(f: Draft): Record<string, unknown> {
  const common = {
    kind: f.kind,
    name: f.name.trim(),
    enabled: f.enabled,
    keep: f.ownKeep ? { daily_days: Number(f.daily), weekly_weeks: Number(f.weekly), upgrades: Number(f.upgrades) } : null,
  };
  if (f.kind === "directory") return { ...common, path: f.path.trim() };
  if (f.kind === "sftp") return { ...common, host: f.host.trim(), port: Number(f.port) || 22, username: f.username.trim(), path: f.path.trim() || "." };
  return {
    ...common,
    endpoint: f.endpoint.trim(),
    bucket: f.bucket.trim(),
    region: f.region.trim(),
    prefix: f.prefix.trim(),
    access_key_id: f.access_key_id.trim(),
    addressing: f.endpoint.trim() ? f.addressing : "virtual",
    ...(f.secret_access_key ? { secret_access_key: f.secret_access_key } : {}),
  };
}

function DestinationDialog({ open, dest, settings, onClose, onSaved }: {
  open: boolean;
  dest: BackupDestination | null;
  settings: BackupSettings;
  onClose: () => void;
  onSaved: (d: BackupDestination) => void;
}) {
  const errors = useFormErrors();
  const [f, setF] = useState<Draft>(() => draftOf(dest, settings.keep));
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Draft>) => setF((x) => ({ ...x, ...patch }));
  // Veyra's SSH key, created the first time an SFTP destination is set up.
  const ssh = useApiData<{ public_key: string }>(open && f.kind === "sftp" ? "/backups/ssh-key" : null);
  const sshKey = ssh.data?.public_key ?? (ssh.error ? "" : null);

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      const body = bodyOf(f);
      const saved = dest
        ? await api.put<BackupDestination>(`/backups/destinations/${dest.id}`, body)
        : await api.post<BackupDestination>("/backups/destinations", body);
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={dest ? `Edit ${dest.name}` : "Add a backup destination"} size="lg" busy={busy}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" onClick={save} loading={busy}>{dest ? "Save" : "Add"}</Button></>}>
      <div className="stack">
        {!dest ? (
          <div className="choice-tiles" role="radiogroup" aria-label="Kind of destination">
            {KINDS.map((k) => (
              <button key={k.value} type="button" role="radio" aria-checked={f.kind === k.value} className="choice-tile" onClick={() => set({ kind: k.value })}>
                <strong>{k.title}</strong>
                <span className="subtle">{k.text}</span>
              </button>
            ))}
          </div>
        ) : null}
        <TextField label="Name" value={f.name} placeholder={f.kind === "s3" ? "Off-site storage" : f.kind === "sftp" ? "District NAS" : "NAS share"} onChange={(e) => set({ name: e.target.value })} help="How the destination is shown here and in alerts." />
        {f.kind === "directory" ? (
          <>
            <TextField label="Folder" required value={f.path} placeholder="/mnt/nas/veyra" spellCheck={false} error={errors.fields.path}
              help="An absolute path on this server. Mount the share first (for example in /etc/fstab), so it is there after a restart." onChange={(e) => set({ path: e.target.value })} />
            <Callout tone="neutral">Veyra writes there as root. If the share is not mounted at backup time, the copy fails, an alert is raised, and the next backup copies what is missing.</Callout>
          </>
        ) : null}
        {f.kind === "sftp" ? (
          <>
            <div className="form-grid">
              <TextField label="Server" required value={f.host} placeholder="nas.example.org" spellCheck={false} onChange={(e) => set({ host: e.target.value })} />
              <TextField label="Port" inputMode="numeric" value={f.port} onChange={(e) => set({ port: e.target.value.replace(/\D/g, "").slice(0, 5) })} />
              <TextField label="User name" required value={f.username} placeholder="veyra" spellCheck={false} onChange={(e) => set({ username: e.target.value })} />
              <TextField label="Folder on the server" value={f.path} placeholder="backups" spellCheck={false} help="Relative to the user's home folder, or absolute. Created if missing." onChange={(e) => set({ path: e.target.value })} />
            </div>
            <div className="stack stack--sm">
              <strong>Veyra signs in with its own SSH key</strong>
              <p className="subtle" style={{ margin: 0 }}>Add this public key to the user&apos;s <span className="mono">~/.ssh/authorized_keys</span> on the server (on a Synology or QNAP: enable SFTP and add the key to the user). No password is stored.</p>
              {sshKey ? <span className="row" style={{ gap: 6, alignItems: "flex-start" }}><code className="mono" style={{ wordBreak: "break-all" }}>{sshKey}</code><CopyButton text={sshKey} /></span> : <span className="subtle">{sshKey === "" ? "Could not load the key." : "Loading the key…"}</span>}
              <p className="subtle" style={{ margin: 0 }}>After saving, use <strong>Test</strong>: the first test shows the server&apos;s host key for you to confirm.</p>
            </div>
          </>
        ) : null}
        {f.kind === "s3" ? (
          <>
            <div className="form-grid">
              <TextField label="Endpoint" value={f.endpoint} placeholder="https://s3.us-west-002.backblazeb2.com" spellCheck={false} error={errors.fields.endpoint}
                help="Empty for Amazon S3. Backblaze B2: https://s3.<region>.backblazeb2.com · Wasabi: https://s3.<region>.wasabisys.com · R2: https://<account>.r2.cloudflarestorage.com" onChange={(e) => set({ endpoint: e.target.value })} />
              <TextField label="Region" value={f.region} placeholder="us-east-1" spellCheck={false} help="As the storage names it (R2: auto)." onChange={(e) => set({ region: e.target.value })} />
              <TextField label="Bucket" required value={f.bucket} spellCheck={false} onChange={(e) => set({ bucket: e.target.value })} />
              <TextField label="Folder in the bucket" value={f.prefix} placeholder="pbx1" spellCheck={false} help="Optional prefix, so several servers can share a bucket." onChange={(e) => set({ prefix: e.target.value })} />
              <TextField label="Access key ID" required value={f.access_key_id} spellCheck={false} autoComplete="off" onChange={(e) => set({ access_key_id: e.target.value })} />
              <TextField label={dest?.has_secret ? "New secret access key (blank keeps the saved one)" : "Secret access key"} required={!dest?.has_secret} type="password" autoComplete="off" value={f.secret_access_key} onChange={(e) => set({ secret_access_key: e.target.value })} />
            </div>
            {f.endpoint.trim() ? (
              <SelectField label="Addressing" value={f.addressing} options={[{ value: "path", label: "Path style (endpoint/bucket) — most S3-compatible storage" }, { value: "virtual", label: "Virtual host (bucket.endpoint)" }]} onChange={(e) => set({ addressing: e.target.value as Draft["addressing"] })} />
            ) : null}
            <Callout tone="neutral" title="A key for Veyra only">Create an access key that can only list, write and delete in this bucket (or this folder of it). Veyra stores the secret encrypted and never shows it again. Old copies are removed by Veyra&apos;s keep policy; a bucket lifecycle rule is not needed.</Callout>
          </>
        ) : null}
        <Switch label="Same keep policy as on this server" checked={!f.ownKeep} onChange={(e) => set({ ownKeep: !e.target.checked })}
          description={f.ownKeep ? "This destination keeps its own number of backups, for example more history off-site." : `Daily for ${settings.keep.daily_days} days, then weekly for ${settings.keep.weekly_weeks} weeks, and the last ${settings.keep.upgrades} pre-upgrade backups.`} />
        {f.ownKeep ? (
          <div className="grid grid--3">
            <TextField label="Keep daily for (days)" inputMode="numeric" value={f.daily} onChange={(e) => set({ daily: e.target.value.replace(/\D/g, "") })} />
            <TextField label="Then one per week for (weeks)" inputMode="numeric" value={f.weekly} onChange={(e) => set({ weekly: e.target.value.replace(/\D/g, "") })} />
            <TextField label="Keep pre-upgrade backups" inputMode="numeric" value={f.upgrades} onChange={(e) => set({ upgrades: e.target.value.replace(/\D/g, "") })} />
          </div>
        ) : null}
        <Switch label="Copy backups here" checked={f.enabled} onChange={(e) => set({ enabled: e.target.checked })} description="Off: Veyra stops copying here but keeps the destination." />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </div>
    </Dialog>
  );
}

function TestDialog({ dest, onClose, onChanged }: { dest: BackupDestination; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [result, setResult] = useState<BackupDestinationTest | null>(null);
  const [busy, setBusy] = useState(true);
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    api.post<BackupDestinationTest>(`/backups/destinations/${dest.id}/test`)
      .then((r) => { if (live) setResult(r); })
      .catch((err: unknown) => { if (live) setResult({ state: "failed", message: errorMessage(err) }); })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [dest.id, round]);
  const again = () => { setBusy(true); setResult(null); setRound((n) => n + 1); };
  const trust = async () => {
    if (!result?.host_key) return;
    setBusy(true);
    try {
      await api.post(`/backups/destinations/${dest.id}/host-key`, { host_key: result.host_key });
      toast.success("Host key confirmed");
      onChanged();
      again();
    } catch (err) {
      toast.error("Could not confirm the host key", errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} title={`Test ${dest.name}`} busy={busy}
      footer={<>{result?.state === "host_key" ? <Button variant="primary" onClick={trust} loading={busy}>This is the server&apos;s key</Button> : <Button onClick={again} disabled={busy}>Test again</Button>}<Button onClick={onClose}>Close</Button></>}>
      {busy && !result ? <p className="subtle">Testing {dest.target}…</p> : null}
      {result?.state === "ok" ? <Callout tone="ok" title="It works">{result.message}</Callout> : null}
      {result?.state === "failed" ? <Callout tone="danger" title="It does not work yet">{result.message}</Callout> : null}
      {result?.state === "host_key" ? (
        <div className="stack stack--sm">
          <p>This is the first connection to <strong>{dest.host}</strong>. Check that its host key is the one the server shows, so Veyra never sends a backup to a server pretending to be yours:</p>
          <code className="mono" style={{ wordBreak: "break-all" }}>{result.fingerprint}</code>
          <p className="subtle">On the server, as root: <span className="mono">ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</span> (or the ecdsa or rsa key, whichever type is shown above).</p>
        </div>
      ) : null}
    </Dialog>
  );
}

/** Where backups are copied (docs/PRODUCTION_HARDENING.md §2.7). */
export function DestinationsCard({ settings, manage, onChanged }: { settings: BackupSettings; manage: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState<BackupDestination | null | "new">(null);
  const [testing, setTesting] = useState<BackupDestination | null>(null);
  const [removing, setRemoving] = useState<BackupDestination | null>(null);
  const [busy, setBusy] = useState(false);
  const list = settings.destinations;
  const clearText = !settings.recipients.length && list.some((d) => d.kind !== "directory" && d.enabled);

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await api.del(`/backups/destinations/${removing.id}`);
      toast.success("Destination removed");
      setRemoving(null);
      onChanged();
    } catch (err) {
      toast.error("Could not remove the destination", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Destinations" subtitle="Every verified backup is also copied to these places. A copy that fails raises an alert and is retried with the next backup."
      actions={manage && list.length < 5 ? <Button icon="plus" onClick={() => setEditing("new")}>Add a destination</Button> : null}>
      <div className="stack stack--sm">
        {clearText ? <Callout tone="warn" title="Backups leave this server unencrypted">They hold the configuration and its secrets. Add an encryption recipient in Settings above before copying them off the server.</Callout> : null}
        {list.length === 0 ? <EmptyState compact icon="database" title="Only on this server">Add a NAS folder, an SFTP server or S3-compatible storage, so a backup survives the loss of this server.</EmptyState> : null}
        {list.map((d) => (
          <div key={d.id} className="row row--between" style={{ gap: 12, flexWrap: "wrap", padding: "var(--space-2) 0", borderBottom: "1px solid var(--border)" }}>
            <div style={{ minWidth: 0 }}>
              <div className="row" style={{ gap: 8 }}>
                <strong>{d.name}</strong>
                <Badge tone="neutral">{KIND_LABEL[d.kind]}</Badge>
                {!d.enabled ? <Badge tone="warn">Off</Badge> : null}
                {d.kind === "sftp" && !d.host_key ? <Badge tone="warn">Host key not confirmed</Badge> : null}
                {d.last ? <Badge tone={d.last.state === "ok" ? "ok" : "danger"}>{d.last.state === "ok" ? `copied ${formatRelative(d.last.at)}` : "last copy failed"}</Badge> : <Badge tone="neutral">no copy yet</Badge>}
              </div>
              <span className="subtle mono" style={{ wordBreak: "break-all" }}>{d.target}</span>
              {d.last?.state === "failed" && d.last.error ? <p className="subtle" style={{ margin: "4px 0 0", color: "var(--danger)" }}>{d.last.error}</p> : null}
              {d.last?.state === "ok" && typeof d.last.count === "number" ? <p className="subtle" style={{ margin: "4px 0 0" }}>{d.last.count} backup{d.last.count === 1 ? "" : "s"} there{d.keep ? " (own keep policy)" : ""}.</p> : null}
            </div>
            {manage ? (
              <div className="row" style={{ gap: 6 }}>
                <Button size="sm" onClick={() => setTesting(d)}>Test</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(d)}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={() => setRemoving(d)}>Remove</Button>
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {editing !== null ? (
        <DestinationDialog key={editing === "new" ? "new" : editing.id} open dest={editing === "new" ? null : editing} settings={settings}
          onClose={() => setEditing(null)}
          onSaved={(d) => { const wasNew = editing === "new"; setEditing(null); onChanged(); toast.success(wasNew ? "Destination added" : "Destination saved"); if (wasNew && d.kind !== "directory") setTesting(d); }} />
      ) : null}
      {testing ? <TestDialog key={testing.id} dest={testing} onClose={() => setTesting(null)} onChanged={onChanged} /> : null}
      <ConfirmDialog open={!!removing} title={`Remove ${removing?.name ?? ""}?`} confirmLabel="Remove" tone="danger" busy={busy} onCancel={() => setRemoving(null)} onConfirm={remove}>
        <p>Veyra stops copying backups there. The copies already made stay where they are.</p>
      </ConfirmDialog>
    </Card>
  );
}
