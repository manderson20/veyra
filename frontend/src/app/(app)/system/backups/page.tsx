// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusBadge,
  Switch,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";
import type { BackupRow, BackupSettings, BackupStatus, BackupSummary } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

const KIND: Record<string, string> = { scheduled: "Scheduled", manual: "Manual", upgrade: "Before upgrade" };

function SettingsCard({ s, manage, onSaved }: { s: BackupSettings; manage: boolean; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [enabled, setEnabled] = useState(s.enabled);
  const [time, setTime] = useState(s.time);
  const [daily, setDaily] = useState(String(s.keep.daily_days));
  const [weekly, setWeekly] = useState(String(s.keep.weekly_weeks));
  const [upgrades, setUpgrades] = useState(String(s.keep.upgrades));
  const [recordings, setRecordings] = useState(s.recordings);
  const [recipients, setRecipients] = useState(s.recipients.join("\n"));
  const [copyDir, setCopyDir] = useState(s.copy_dir);
  const [busy, setBusy] = useState(false);
  useOnChange(s, (v) => {
    setEnabled(v.enabled); setTime(v.time); setDaily(String(v.keep.daily_days)); setWeekly(String(v.keep.weekly_weeks));
    setUpgrades(String(v.keep.upgrades)); setRecordings(v.recordings); setRecipients(v.recipients.join("\n")); setCopyDir(v.copy_dir);
  });

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      await api.put("/backups/settings", {
        enabled, time, recordings, copy_dir: copyDir.trim(),
        keep: { daily_days: Number(daily), weekly_weeks: Number(weekly), upgrades: Number(upgrades) },
        recipients: recipients.split("\n").map((r) => r.trim()).filter(Boolean),
      });
      toast.success("Backup settings saved");
      onSaved();
    } catch (err) {
      errors.set(err);
      toast.error("Could not save the backup settings", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Settings" actions={manage ? <Button variant="primary" onClick={save} loading={busy}>Save</Button> : null}>
      <div className="stack stack--sm">
        <Switch label="Scheduled backups" checked={enabled} disabled={!manage} onChange={(e) => setEnabled(e.target.checked)}
          description="A backup every day at the time below, verified by a restore test before it counts." />
        <div className="grid grid--2">
          <TextField label="Time of day" value={time} disabled={!manage} onChange={(e) => setTime(e.target.value)} placeholder="02:30" help="Server local time, HH:MM." error={errors.fields["time"]} />
          <TextField label="Copy to directory" value={copyDir} disabled={!manage} onChange={(e) => setCopyDir(e.target.value)} placeholder="/mnt/nas/veyra"
            help="A mounted share (NFS, CIFS) that receives every backup; needs encryption below." error={errors.fields["copy_dir"]} />
        </div>
        <div className="grid grid--3">
          <TextField label="Keep daily for (days)" type="number" min={0} value={daily} disabled={!manage} onChange={(e) => setDaily(e.target.value)} />
          <TextField label="Then one per week for (weeks)" type="number" min={0} value={weekly} disabled={!manage} onChange={(e) => setWeekly(e.target.value)} />
          <TextField label="Keep pre-upgrade backups" type="number" min={0} value={upgrades} disabled={!manage} onChange={(e) => setUpgrades(e.target.value)} />
        </div>
        <Checkbox label="Include call recordings" checked={recordings} disabled={!manage} onChange={(e) => setRecordings(e.target.checked)}
          description="Recordings are the largest files; without them a restore keeps the recording records but not the audio." />
        <TextArea label="Encryption recipients (age public keys, one per line)" value={recipients} disabled={!manage} rows={3} spellCheck={false}
          onChange={(e) => setRecipients(e.target.value)} placeholder="age1…" error={errors.fields["recipients"]}
          help="Backups are encrypted to these keys with age; Veyra keeps no private key. Create one with age-keygen on a machine that is not this server, and keep it safe: without it a backup cannot be restored. SSH public keys (ssh-ed25519) work too." />
      </div>
    </Card>
  );
}

function Progress({ active, onFinished }: { active: boolean; onFinished: () => void }) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  useEffect(() => {
    if (!active) return;
    let stop = false;
    const poll = async () => {
      try {
        const s = await api.get<BackupStatus>("/backups/status");
        if (stop) return;
        setStatus(s);
        if (s.state !== "running") { onFinished(); return; }
      } catch { /* keep polling */ }
      if (!stop) setTimeout(poll, 2000);
    };
    poll();
    return () => { stop = true; };
  }, [active, onFinished]);
  if (!active || !status || status.state !== "running") return null;
  return <Callout tone="info" title="Backup running">{status.step ?? "Working"} · started {formatRelative(status.started_at)}</Callout>;
}

export default function BackupsPage() {
  const { can } = useSession();
  const toast = useToast();
  const manage = can("backups.manage");
  const settings = useApiData<BackupSettings>("/backups/settings");
  const list = useApiData<{ summary: BackupSummary; backups: BackupRow[] }>("/backups");
  const [running, setRunning] = useState(false);
  const [remove, setRemove] = useState<BackupRow | null>(null);
  const [busy, setBusy] = useState(false);

  const runNow = async () => {
    setBusy(true);
    try {
      await api.post("/backups/run");
      setRunning(true);
      toast.success("Backup started");
    } catch (err) {
      toast.error("Could not start the backup", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const doDelete = async () => {
    if (!remove) return;
    setBusy(true);
    try {
      await api.del(`/backups/${remove.id}`);
      toast.success("Backup deleted");
      setRemove(null);
      setTimeout(list.reload, 1500);
    } catch (err) {
      toast.error("Could not delete the backup", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const summary = list.data?.summary;
  const columns: Column<BackupRow>[] = [
    { key: "when", header: "Taken", render: (b) => <span><span className="table__primary" style={{ display: "block" }}>{formatDateTime(b.started_at)}</span><span className="table__secondary">{KIND[b.kind] ?? b.kind} · {b.created_by}</span></span> },
    { key: "state", header: "State", render: (b) => <StatusBadge status={b.state === "verified" ? "ok" : b.state === "running" ? "degraded" : b.state === "failed" ? "failed" : "unavailable"} label={b.state} /> },
    { key: "size", header: "Size", render: (b) => formatBytes(b.bytes) },
    { key: "parts", header: "Contents", render: (b) => <span className="subtle">{b.parts.map((p) => p.name.replace(/\.(tar|dump)$/, "")).join(", ") || "—"}</span> },
    { key: "enc", header: "Encrypted", render: (b) => b.encrypted ? <Badge tone="ok">age</Badge> : <Badge tone="warn">clear</Badge> },
    { key: "copies", header: "Copies", render: (b) => Object.entries(b.copies).length ? Object.entries(b.copies).map(([d, c]) => <Badge key={d} tone={c.state === "ok" ? "ok" : "danger"}>{c.state === "ok" ? "copied" : `copy failed`}</Badge>) : <span className="subtle">local only</span> },
    { key: "ver", header: "Version", render: (b) => <span className="mono">{b.version ?? "—"}</span> },
    { key: "actions", header: "", render: (b) => manage && b.state !== "running" && b.state !== "deleted" ? <Button size="sm" variant="danger" onClick={() => setRemove(b)}>Delete</Button> : null },
  ];

  return (
    <div className="stack">
      <PageHeader title="Backups" description="Database, configuration and secrets, engine configuration, prompts, hold music, firmware, templates, modules, voicemail and (optionally) recordings; each backup is restored into a scratch database before it counts."
        actions={manage ? <Button variant="primary" icon="plus" onClick={runNow} loading={busy} disabled={running}>Back up now</Button> : null} />
      <Progress active={running} onFinished={() => { setRunning(false); list.reload(); }} />
      {summary ? (
        <div className="grid grid--3">
          <Card title="Last good backup"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.last_good_at ? formatRelative(summary.last_good_at) : "Never"}</p>
            <p className="subtle">{summary.stale ? "No verified backup in the last two days." : `${summary.count} verified backup${summary.count === 1 ? "" : "s"} kept.`}</p></Card>
          <Card title="Encryption"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.encrypted ? "age" : "Off"}</p>
            <p className="subtle">{summary.encrypted ? "Backups leave this server encrypted." : "Local backups are root-only; set recipients before copying them anywhere."}</p></Card>
          <Card title="Schedule"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.enabled ? `Daily at ${settings.data?.time ?? ""}` : "Off"}</p>
            <p className="subtle">{summary.last_state === "failed" ? `Last run failed: ${summary.last_error}` : "Scheduled by the worker; runs as root."}</p></Card>
        </div>
      ) : null}
      {summary?.stale && summary.enabled ? <Callout tone="warn" title="No recent good backup">Run one now, or check the last error above.</Callout> : null}
      {settings.error ? <Card><ErrorState error={settings.error} onRetry={settings.reload} /></Card> : !settings.data ? <Card><LoadingState /></Card> : (
        <SettingsCard s={settings.data} manage={manage} onSaved={() => { settings.reload(); list.reload(); }} />
      )}
      <Card title="Backups" flush>
        {list.error ? <ErrorState compact error={list.error} onRetry={list.reload} /> : (
          <DataTable columns={columns} rows={(list.data?.backups ?? []).filter((b) => b.state !== "deleted")} rowKey={(b) => b.id} caption="Backups"
            empty={<EmptyState compact icon="database" title="No backups yet">{manage ? "Use “Back up now”, or wait for the schedule." : "No backup has been taken."}</EmptyState>} />
        )}
      </Card>
      <Card title="Restore">
        <p className="subtle">On a server with the same Veyra release installed (a fresh install is fine), as root:</p>
        <pre className="mono" style={{ margin: 0 }}>{"sudo veyra backup restore /var/backups/veyra/<backup>.tar.age --identity ~/veyra-backup-identity.txt"}</pre>
        <p className="subtle">The database, configuration and secrets, engine files, data and voicemail come back, migrations run when the backup is older, and the services restart. The instance identity, keys and certificates are part of the backup, so phones and a central console keep recognising the server. See docs/PRODUCTION_HARDENING.md §2.5.</p>
      </Card>
      <ConfirmDialog open={!!remove} title={`Delete the backup of ${remove ? formatDateTime(remove.started_at) : ""}`} confirmLabel="Delete" tone="danger" busy={busy}
        onCancel={() => setRemove(null)} onConfirm={doDelete}>
        <p>The files are removed from this server and from the copy directory. Keep at least one verified backup.</p>
      </ConfirmDialog>
    </div>
  );
}
