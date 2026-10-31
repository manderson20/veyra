// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
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
  ErrorState,
  Icon,
  LoadingState,
  PageHeader,
  StatusBadge,
  Switch,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatRelative } from "@/lib/format";
import type { BackupRow, BackupSettings, BackupStatus, BackupSummary } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";
import { DestinationsCard, RecordingArchiveCard } from "@/components/backups/DestinationsCard";

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
  const [busy, setBusy] = useState(false);
  useOnChange(s, (v) => {
    setEnabled(v.enabled); setTime(v.time); setDaily(String(v.keep.daily_days)); setWeekly(String(v.keep.weekly_weeks));
    setUpgrades(String(v.keep.upgrades)); setRecordings(v.recordings); setRecipients(v.recipients.join("\n"));
  });

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      await api.put("/backups/settings", {
        enabled, time, recordings,
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

interface DownloadState { state: "none" | "preparing" | "ready" | "failed"; filename: string | null; bytes: number | null; sha256: string | null; error: string | null }

/** Root prepares a copy the web service can read; then the browser downloads it (issue #348). */
interface RestoreState { id?: string; state: "none" | "running" | "finished" | "failed"; step?: string; stopped?: boolean; safety_backup?: string | null; backup?: string; error?: string | null; started_at?: string; finished_at?: string | null }

const RESTORE_RECENT_MS = 7 * 24 * 3600 * 1000;

function restoreConsoleHelp(state: RestoreState) {
  return state.safety_backup ? <p>The server&apos;s state just before the restore is in the safety backup <code>{state.safety_backup}</code>. On the console: <code>sudo veyra backup restore /var/backups/veyra/{state.safety_backup}.tar.age --identity &lt;your identity file&gt;</code> (leave out <code>.tar.age</code> and <code>--identity</code> if backups are not encrypted).</p> : null;
}

function LastRestore({ state }: { state: RestoreState }) {
  const [now] = useState(() => Date.now());
  if (state.state === "none" || state.state === "running" || !state.finished_at) return null;
  if (now - new Date(state.finished_at).getTime() > RESTORE_RECENT_MS) return null;
  if (state.state === "finished") {
    return <Callout tone="ok" title={`Restored ${formatRelative(state.finished_at)}`}>From <code>{state.backup}</code>. Backups taken after it stay on the server but are no longer listed.{state.safety_backup ? <> The state just before the restore is in <code>{state.safety_backup}</code>.</> : null}</Callout>;
  }
  return (
    <Callout tone="danger" title={`A restore failed ${formatRelative(state.finished_at)}`}>
      <p>{state.error}</p>
      {state.stopped ? restoreConsoleHelp(state) : <p>The server was not changed.</p>}
    </Callout>
  );
}

function RestoreDialog({ backup, onClose }: { backup: BackupRow; onClose: () => void }) {
  const [identity, setIdentity] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoreId, setRestoreId] = useState<string | null>(null);
  const [state, setState] = useState<RestoreState | null>(null);
  const done = state?.state === "finished" || state?.state === "failed";

  // From nginx, not the API: the API is stopped for most of a restore.
  useEffect(() => {
    if (!restoreId || done) return;
    const poll = async () => {
      try {
        const res = await fetch("/restore-status.json", { cache: "no-store" });
        if (!res.ok) return;
        const next = (await res.json()) as RestoreState;
        if (next.id === restoreId) setState(next);
      } catch {
        // nginx answers throughout; a lost request is retried.
      }
    };
    void poll();
    const id = setInterval(() => void poll(), 2000);
    return () => clearInterval(id);
  }, [restoreId, done]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await api.post<{ id: string }>(`/backups/${backup.id}/restore`, { identity: backup.encrypted ? identity : null, confirm });
      setIdentity("");
      setRestoreId(out.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (restoreId) {
    return (
      <Dialog open onClose={done ? onClose : () => undefined} title={state?.state === "finished" ? "Restore finished" : state?.state === "failed" ? "Restore failed" : "Restoring this server"}
        footer={state?.state === "finished" ? <a className={buttonClass("primary", "md")} href="/">Sign in again</a> : state?.state === "failed" ? <Button onClick={() => window.location.reload()}>Reload the page</Button> : null}>
        {state?.state === "finished" ? <p>The services are running again from the backup of {formatDateTime(backup.started_at)}. Check that phones register and make a test call.</p>
          : state?.state === "failed" ? (
            <div className="stack stack--sm">
              {state.stopped ? <Callout tone="danger" title="The server may be incomplete">The restore stopped partway, after the services were stopped. Veyra tried to start them again.</Callout> : <Callout tone="warn" title="Nothing was changed">The backup was refused before anything on the server was touched.</Callout>}
              {state.stopped ? restoreConsoleHelp(state) : null}
              <p className="subtle">Reload the page to see the reason on this page.</p>
            </div>
          ) : (
            <div className="stack stack--sm">
              <p><StatusBadge status="degraded" label={state?.step ?? "Starting"} /></p>
              <p className="subtle">Keep this page open. The rest of the web interface stops answering while the services are stopped. This can take a long time on a large backup.</p>
            </div>
          )}
      </Dialog>
    );
  }

  return (
    <Dialog open onClose={onClose} title="Restore this backup" description={formatDateTime(backup.started_at)}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" onClick={start} loading={busy} disabled={confirm !== "RESTORE" || (backup.encrypted && !identity.trim())}>Restore this server</Button></>}>
      <div className="stack stack--sm">
        <Callout tone="danger" title="This replaces everything on this server">The database, configuration, phone system files, data, voicemail and recordings go back to {formatDateTime(backup.started_at)}. Everything since then is lost, and everyone is signed out. Calls may drop.</Callout>
        <p>A safety backup of this server is taken first, and the chosen backup is checked. If either fails, nothing changes. The safety backup is kept on this server only.</p>
        {backup.encrypted ? <TextArea label="Age private key" help="From the identity file you keep off this server. It starts with AGE-SECRET-KEY-. It is used for this restore only and is not stored." rows={3} value={identity} onChange={(e) => setIdentity(e.target.value)} autoComplete="off" spellCheck={false} /> : null}
        <TextField label={<>Type <code>RESTORE</code> to confirm</>} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
        {error ? <Callout tone="danger" title="Not started">{error}</Callout> : null}
      </div>
    </Dialog>
  );
}

function BackupDownloadDialog({ backup, onClose }: { backup: BackupRow; onClose: () => void }) {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<DownloadState | null>(null);
  const [fetched, setFetched] = useState(false);
  const url = `/backups/${backup.id}/download`;
  useEffect(() => {
    if (!started || fetched) return;
    const t = window.setInterval(() => {
      void api.get<DownloadState>(url).then(setState).catch((err) => setError(errorMessage(err)));
    }, 2000);
    return () => window.clearInterval(t);
  }, [started, fetched, url]);
  const prepare = async () => {
    setError(null);
    try {
      await api.post(url, { allow_unencrypted: !backup.encrypted });
      setState(null);
      setStarted(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  const ready = started && state?.state === "ready";
  const failed = started && state?.state === "failed";
  return (
    <Dialog open onClose={onClose} title="Download this backup" description={formatDateTime(backup.started_at)}
      footer={<><Button onClick={onClose}>Close</Button>{!started ? <Button variant="primary" onClick={prepare}>{backup.encrypted ? "Prepare download" : "Prepare anyway"}</Button> : null}{ready ? <a className={buttonClass("primary", "md")} href={`${API_BASE}${url}/file`} download onClick={() => setFetched(true)}><Icon name="download" size={14} /> Download {state.bytes != null ? formatBytes(state.bytes) : ""}</a> : null}</>}>
      <div className="stack stack--sm">
        {!backup.encrypted ? <Callout tone="danger" title="This backup is not encrypted">It holds the server&apos;s secrets, including the installation key and every password, in the clear. Anyone with the file can read them. Turn on encryption in the settings on this page unless you have a safe place for it.</Callout> : <p>This backup is encrypted. Restoring it needs your private age key.</p>}
        {error ? <Callout tone="danger">{error}</Callout> : null}
        {started && !state?.filename && !failed ? <p className="subtle">Preparing the download. A large backup takes a few minutes.</p> : null}
        {failed ? <Callout tone="danger">{state?.error ?? "The download could not be prepared."}</Callout> : null}
        {ready ? <><p className="mono" style={{ overflowWrap: "anywhere", margin: 0 }}>{state.filename}</p><p className="subtle" style={{ margin: 0 }}>SHA-256, to check the file arrived whole:</p><p className="mono" style={{ overflowWrap: "anywhere", margin: 0 }}>{state.sha256}</p><p className="subtle" style={{ margin: 0 }}>The prepared copy is removed from the server when the download ends, so it can be downloaded once. If yours fails, close this and download again.</p></> : null}
      </div>
    </Dialog>
  );
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
  const [downloading, setDownloading] = useState<BackupRow | null>(null);
  const [restoring, setRestoring] = useState<BackupRow | null>(null);
  const lastRestore = useApiData<RestoreState>("/backups/restore");
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
    { key: "copies", header: "Copies", render: (b) => Object.entries(b.copies).length ? <span className="row" style={{ gap: 4, flexWrap: "wrap" }}>{Object.entries(b.copies).map(([d, c]) => <Badge key={d} tone={c.state === "ok" ? "ok" : "danger"}>{c.name ?? "copy"}: {c.state === "ok" ? "ok" : "failed"}</Badge>)}</span> : <span className="subtle">local only</span> },
    { key: "ver", header: "Version", render: (b) => <span className="mono">{b.version ?? "—"}</span> },
    { key: "actions", header: "", render: (b) => manage && b.state !== "running" && b.state !== "deleted" ? <span className="row" style={{ gap: 4 }}>{b.state === "verified" ? <><Button size="sm" icon="download" onClick={() => setDownloading(b)}>Download</Button><Button size="sm" onClick={() => setRestoring(b)}>Restore</Button></> : null}<Button size="sm" variant="danger" onClick={() => setRemove(b)}>Delete</Button></span> : null },
  ];

  return (
    <div className="stack">
      <PageHeader title="Backups" description="Database, configuration and secrets, engine configuration, prompts, hold music, firmware, templates, modules, voicemail and (optionally) recordings; each backup is restored into a scratch database before it counts."
        actions={manage ? <Button variant="primary" icon="plus" onClick={runNow} loading={busy} disabled={running}>Back up now</Button> : null} />
      {lastRestore.data ? <LastRestore state={lastRestore.data} /> : null}
      <Progress active={running} onFinished={() => { setRunning(false); list.reload(); }} />
      {summary ? (
        <div className="grid grid--3">
          <Card title="Last good backup"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.last_good_at ? formatRelative(summary.last_good_at) : "Never"}</p>
            <p className="subtle">{summary.stale ? "No verified backup in the last two days." : `${summary.count} verified backup${summary.count === 1 ? "" : "s"} kept.`}</p></Card>
          <Card title="Encryption"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.encrypted ? "age" : "Off"}</p>
            <p className="subtle">{summary.encrypted ? "Backups leave this server encrypted." : "Local backups are root-only; set recipients before adding a destination."}</p></Card>
          <Card title="Schedule"><p className="metric__value" style={{ fontSize: "var(--text-lg)" }}>{summary.enabled ? `Daily at ${settings.data?.time ?? ""}` : "Off"}</p>
            <p className="subtle">{summary.last_state === "failed" ? `Last run failed: ${summary.last_error}` : "Scheduled by the worker; runs as root."}</p></Card>
        </div>
      ) : null}
      {summary?.stale && summary.enabled ? <Callout tone="warn" title="No recent good backup">Run one now, or check the last error above.</Callout> : null}
      {settings.error ? <Card><ErrorState error={settings.error} onRetry={settings.reload} /></Card> : !settings.data ? <Card><LoadingState /></Card> : (
        <>
          <SettingsCard s={settings.data} manage={manage} onSaved={() => { settings.reload(); list.reload(); }} />
          <DestinationsCard settings={settings.data} manage={manage} onChanged={settings.reload} />
          <RecordingArchiveCard settings={settings.data} manage={manage} />
        </>
      )}
      <Card title="Backups" flush>
        {list.error ? <ErrorState compact error={list.error} onRetry={list.reload} /> : (
          <DataTable columns={columns} rows={(list.data?.backups ?? []).filter((b) => b.state !== "deleted")} rowKey={(b) => b.id} caption="Backups"
            empty={<EmptyState compact icon="database" title="No backups yet">{manage ? "Use “Back up now”, or wait for the schedule." : "No backup has been taken."}</EmptyState>} />
        )}
      </Card>
      {downloading ? <BackupDownloadDialog backup={downloading} onClose={() => setDownloading(null)} /> : null}
      {restoring ? <RestoreDialog backup={restoring} onClose={() => { setRestoring(null); lastRestore.reload(); }} /> : null}
      <Card title="Restore">
        <p className="subtle">To go back to a backup kept on this server, choose <strong>Restore</strong> in its row above. To restore a file on a server that does not list it (a fresh install is fine), on a server with the same Veyra release or newer, as root:</p>
        <pre className="mono" style={{ margin: 0 }}>{"sudo veyra backup restore /var/backups/veyra/<backup>.tar.age --identity ~/veyra-backup-identity.txt"}</pre>
        <p className="subtle">The database, configuration and secrets, engine files, data and voicemail come back, migrations run when the backup is older, and the services restart. The instance identity, keys and certificates are part of the backup, so phones and a central console keep recognising the server. The guide <Link href="/help/backups/">Backups and restore</Link> has the steps.</p>
      </Card>
      <ConfirmDialog open={!!remove} title={`Delete the backup of ${remove ? formatDateTime(remove.started_at) : ""}`} confirmLabel="Delete" tone="danger" busy={busy}
        onCancel={() => setRemove(null)} onConfirm={doDelete}>
        <p>The files are removed from this server and from every destination. Keep at least one verified backup.</p>
      </ConfirmDialog>
    </div>
  );
}
