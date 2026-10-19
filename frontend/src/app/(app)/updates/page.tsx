// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Callout,
  Icon,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  SelectField,
  Switch,
  TextArea,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { browserTimeZone, timeZones } from "@/lib/timezones";
import type {
  AvailableUpdate,
  CentralNotice,
  MaintenanceWindow,
  Page,
  SystemPackages,
  UpdateCheck,
  UpdateDetail,
  UpdateHistoryItem,
  UpdateMode,
  UpdatePolicies,
  UpdatePolicy,
  UpdateSource,
  UpgradeStatus,
  HaStatus,
} from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const MODES: { value: UpdateMode; label: string; help: string }[] = [
  { value: "manual", label: "Manual only", help: "Veyra never checks automatically. An administrator checks, downloads and installs." },
  { value: "notify", label: "Notify", help: "Check on a schedule and email the update recipients. Nothing is downloaded or installed by itself." },
  { value: "download_approve", label: "Download, install on approval", help: "Download new releases automatically; an administrator approves the installation." },
  { value: "auto_install_window", label: "Install automatically in a maintenance window", help: "Download, and install the chosen categories in the maintenance window when no call is in progress. Other releases wait for approval." },
];

const CHECK_OUTCOME: Record<string, { tone: "ok" | "neutral" | "danger" | "warn"; label: string }> = {
  ok: { tone: "ok", label: "Succeeded" },
  not_configured: { tone: "neutral", label: "No update source" },
  failed: { tone: "danger", label: "Failed" },
  rejected: { tone: "warn", label: "Rejected" },
};

const STATE: Record<string, { tone: "ok" | "neutral" | "danger" | "warn" | "info"; label: string }> = {
  available: { tone: "neutral", label: "Available" },
  downloaded: { tone: "info", label: "Downloaded" },
  approved: { tone: "warn", label: "Approved" },
  installing: { tone: "warn", label: "Installing" },
  installed: { tone: "ok", label: "Installed" },
  failed: { tone: "danger", label: "Failed" },
  superseded: { tone: "neutral", label: "Superseded" },
};

const DAYS = [
  ["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"],
] as const;

function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  return bytes > 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export default function UpdatesPage() {
  const { can } = useSession();
  const toast = useToast();
  const policies = useApiData<UpdatePolicies>("/updates/policies");
  const latest = useApiData<UpdateCheck | null>("/updates/checks/latest");
  const available = useApiData<AvailableUpdate[]>("/updates/available");
  const packages = useApiData<SystemPackages>("/updates/system-packages");
  const [histOffset, setHistOffset] = useState(0);
  const history = useApiData<Page<UpdateHistoryItem>>("/updates/history", { limit: 10, offset: histOffset });
  const central = useApiData<CentralNotice>("/central/notice");
  const [checking, setChecking] = useState(false);
  const [review, setReview] = useState<string | null>(null);
  const manage = can("updates.manage");

  // An approved "install now" or a running installation: watch its progress
  // and refresh the list until it is over (the worker starts the upgrade
  // within a minute of the approval; the list state goes approved →
  // installing → installed / failed).
  const pending = (available.data ?? []).find((u) => u.state === "installing" || (u.state === "approved" && u.install_when === "now"));
  const pendingId = pending?.id;
  const reloadAvailable = available.reload;
  useEffect(() => {
    if (!pendingId) return;
    const t = window.setInterval(reloadAvailable, 5000);
    return () => window.clearInterval(t);
  }, [pendingId, reloadAvailable]);
  const reloadHistory = history.reload;
  const progress = useInstallProgress(pending, () => { reloadAvailable(); reloadHistory(); });
  // HA-aware updates (docs/HIGH_AVAILABILITY.md §12).
  const ha = useApiData<HaStatus>(can("ha.read") ? "/ha/status" : null);
  const [standbyBusy, setStandbyBusy] = useState(false);
  const standbyCandidate = (available.data ?? []).find((u) => u.component === "veyra_core" && ["downloaded", "available"].includes(u.state));
  const installOnStandby = async (version: string) => {
    setStandbyBusy(true);
    try {
      await api.post("/ha/standby-upgrade", { version });
      toast.success(`Installing ${version} on the standby`, "Watch System → High availability for its version to change, then switch over.");
      ha.reload();
    } catch (err) {
      toast.error("Could not start the standby upgrade", errorMessage(err));
    } finally {
      setStandbyBusy(false);
    }
  };

  const checkNow = async () => {
    setChecking(true);
    try {
      const r = await api.post<UpdateCheck>("/updates/check");
      latest.setData(r);
      available.reload();
      if (r.outcome === "ok") toast.success("Update check complete", r.message ?? undefined);
      else if (r.outcome === "not_configured") toast.info("No update source configured", r.message ?? undefined);
      else toast.error("Update check failed", r.message ?? undefined);
    } catch (err) {
      toast.error("Update check failed", errorMessage(err));
    } finally {
      setChecking(false);
    }
  };

  const availableColumns: Column<AvailableUpdate>[] = [
    { key: "target", header: "Component", render: (u) => <span className="table__primary">{u.target === "veyra" ? "Veyra" : u.target}</span> },
    { key: "version", header: "Version", render: (u) => <span className="mono">{u.current_version ?? "?"} → {u.version}</span> },
    { key: "category", header: "Type", render: (u) => <Badge tone={u.category === "security" ? "danger" : u.category === "bugfix" ? "warn" : "info"}>{u.category}</Badge> },
    {
      key: "state", header: "State", render: (u) => (
        <span className="stack stack--sm">
          <Badge tone={STATE[u.state]?.tone ?? "neutral"}>{STATE[u.state]?.label ?? u.state}{u.state === "approved" ? (u.install_when === "window" ? " · maintenance window" : " · starting") : ""}</Badge>
          {u.error ? <span className="subtle">{u.error}</span> : null}
        </span>
      ),
    },
    { key: "found", header: "Found", render: (u) => <span className="subtle">{formatRelative(u.created_at)}</span> },
    {
      key: "actions", header: <span className="sr-only">Actions</span>, render: (u) => (
        u.component === "veyra_core" && !["installed"].includes(u.state)
          ? <Button size="sm" onClick={() => setReview(u.id)}>{manage && ["available", "failed", "downloaded"].includes(u.state) ? "Review and install" : "Details"}</Button>
          : null
      ),
    },
  ];
  const historyColumns: Column<UpdateHistoryItem>[] = [
    { key: "target", header: "Component", render: (h) => h.target },
    { key: "version", header: "Version", render: (h) => <span className="mono">{h.from_version ?? "?"} → {h.to_version}</span> },
    { key: "outcome", header: "Result", render: (h) => <Badge tone={h.outcome === "success" ? "ok" : h.outcome === "running" ? "info" : "danger"}>{h.outcome}</Badge> },
    { key: "by", header: "Started by", render: (h) => h.initiated_by },
    { key: "when", header: "Started", render: (h) => <span className="subtle nowrap">{formatDateTime(h.started_at)}</span> },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Updates"
        description="Veyra releases are signed. They are downloaded and verified here, and installed when you approve them or inside your maintenance window."
        actions={manage ? <Button icon="refresh" onClick={checkNow} loading={checking}>Check now</Button> : null}
      />

      {central.data?.managed.updates ? (
        <Callout tone="info" title="Managed by the central console">
          {central.data.console_name ?? "The central console"} sets the update policy, source and recipients of this installation; changes made here are replaced at its next check-in. Under System → Central management you can take the update policy back.
        </Callout>
      ) : null}

      {ha.data?.ha_enabled && ha.data.local.role === "primary" ? (
        <Callout tone="info" title="Update the standby first">
          {ha.data.peer ? <>The standby {ha.data.peer.node_name} runs <span className="mono">{ha.data.peer.software_version ?? "an unknown version"}</span>. </> : null}
          Order for a pair: 1. install the release on the standby, 2. switch over to it, 3. install on the old primary (now the standby), 4. optionally switch back. The standby gets the artifact through the file sync.
          {manage && standbyCandidate ? <> <Button size="sm" onClick={() => installOnStandby(standbyCandidate.version)} loading={standbyBusy}>Install {standbyCandidate.version} on the standby</Button></> : null}
        </Callout>
      ) : null}

      {progress.active ? (
        <Callout tone={progressTone(progress)} title={progressTitle(progress)}>
          <InstallProgressBody progress={progress} />
        </Callout>
      ) : null}

      <Card title="Available updates" flush>
        <DataTable columns={availableColumns} rows={available.data} rowKey={(u) => u.id} loading={available.loading} error={available.error} onRetry={available.reload}
          caption="Available updates" empty={<EmptyState compact icon="checkCircle" title="No updates found">No updates were found as of the last check.</EmptyState>} />
      </Card>

      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Last check">
          {latest.error ? <ErrorState compact error={latest.error} onRetry={latest.reload} /> : latest.loading && latest.data === undefined ? <LoadingState /> : !latest.data ? (
            <EmptyState compact icon="clock" title="Never checked">{manage ? "Use “Check now” to check for updates." : "No update check has run yet."}</EmptyState>
          ) : (
            <dl className="dl">
              <dt>Result</dt><dd><Badge tone={CHECK_OUTCOME[latest.data.outcome]?.tone ?? "neutral"}>{CHECK_OUTCOME[latest.data.outcome]?.label ?? latest.data.outcome}</Badge></dd>
              <dt>When</dt><dd>{formatDateTime(latest.data.checked_at)}</dd>
              <dt>Details</dt><dd>{latest.data.message ?? "—"}</dd>
              {latest.data.source ? <><dt>Source</dt><dd className="mono">{latest.data.source}</dd></> : null}
            </dl>
          )}
        </Card>
        <SourceCard editable={manage} onSaved={() => policies.reload()} />
      </div>

      <section aria-labelledby="policies-title" className="stack stack--sm">
        <div>
          <h2 className="card__title" id="policies-title">Update policies</h2>
          <p className="muted">Each component has its own policy. Modules update from the module catalog; operating system packages are listed below and applied with the package manager.</p>
        </div>
        {policies.error ? <Card><ErrorState error={policies.error} onRetry={policies.reload} /></Card> : !policies.data ? <Card><LoadingState /></Card> : (
          policies.data.items.map((p) => (
            <PolicyCard key={p.component} policy={p} availableModes={policies.data?.available_modes ?? []} editable={manage}
              onSaved={(np) => policies.setData(policies.data ? { ...policies.data, items: policies.data.items.map((x) => (x.component === np.component ? { ...np, label: x.label } : x)) } : undefined)} />
          ))
        )}
      </section>

      <SystemPackagesCard data={packages.data} error={packages.error} onRetry={packages.reload} />

      <Card title="Update history" flush>
        <DataTable columns={historyColumns} rows={history.data?.items} rowKey={(h) => h.id} loading={history.loading} error={history.error} onRetry={history.reload}
          caption="Update history" empty={<EmptyState compact icon="history" title="No updates have been applied" />}
          pagination={history.data && history.data.total > 0 ? <Pagination total={history.data.total} limit={10} offset={histOffset} onChange={setHistOffset} /> : null} />
      </Card>

      {review ? (
        <ReviewDialog id={review} editable={manage} progress={progress} onClose={() => setReview(null)}
          onChanged={() => { available.reload(); }} />
      ) : null}
    </div>
  );
}

/** Elapsed time as m:ss (installs take a minute or two). */
function elapsedLabel(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function secondsBetween(from: string | null | undefined, to: number): number | null {
  const t = from ? Date.parse(from) : NaN;
  return Number.isFinite(t) ? Math.max(0, Math.round((to - t) / 1000)) : null;
}

type StageState = "done" | "current" | "later";

/** One stage of an installation on the timeline below. */
function Stage({ state, title, note, index }: { state: StageState; title: string; note?: ReactNode; index: number }) {
  const cls = ["stepper__item", state === "done" && "stepper__item--done", state === "later" && "stepper__item--later"].filter(Boolean).join(" ");
  return (
    <li className={cls} aria-current={state === "current" ? "step" : undefined} style={{ alignItems: "flex-start" }}>
      <span className="stepper__marker" aria-hidden="true">{state === "done" ? <Icon name="check" size={12} strokeWidth={3} /> : index}</span>
      <span>
        {title}
        {note ? <span className="subtle" style={{ display: "block", fontWeight: "normal" }}>{note}</span> : null}
      </span>
    </li>
  );
}

/** What the page and the review dialog know about an installation. */
type InstallProgressModel = {
  status: UpgradeStatus | null;
  /** The API did not answer: Veyra is restarting during the upgrade. */
  unreachable: boolean;
  now: number;
  /** Something to show: a pending or running installation, or the outcome of the one just watched. */
  active: boolean;
  version: string;
  outcome: "succeeded" | "failed" | null;
};

/** Progress of an installation, live from the approval: the stages before
 * the installer prints anything (queued for the worker, release verified and
 * unpacked by the root unit) come from `pending`, the installer's step and
 * output from the runner's status file; both are polled every 3 seconds, and
 * the API's restart during the upgrade reads as "restarting", not as an
 * error. One poller per page; the review dialog shows the same model. */
function useInstallProgress(listed: AvailableUpdate | undefined, onFinished: () => void): InstallProgressModel {
  const toast = useToast();
  const [status, setStatus] = useState<UpgradeStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [watching, setWatching] = useState(!!listed);
  const [now, setNow] = useState(() => Date.now());
  const finished = useRef(onFinished);
  useEffect(() => { finished.current = onFinished; }, [onFinished]);

  useOnChange(!!listed, (a) => { if (a) setWatching(true); });

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      try {
        const s = await api.get<UpgradeStatus>("/updates/status");
        if (stop) return;
        setUnreachable(false);
        setNow(Date.now());
        if (s.pending) setWatching(true);
        setStatus((prev) => {
          if (prev?.run?.state === "running" && s.run && s.run.state !== "running") {
            if (s.run.state === "succeeded") toast.success(`Veyra ${s.run.version} installed`, "Reload the page to use the new version.");
            else toast.error("The upgrade failed", s.run.error ?? undefined);
            finished.current();
          }
          return s;
        });
      } catch {
        if (!stop) { setUnreachable(true); setNow(Date.now()); }
      }
    };
    void poll();
    if (!watching) return () => { stop = true; };
    const t = window.setInterval(poll, 3000);
    return () => { stop = true; window.clearInterval(t); };
  }, [watching, toast]);

  const pending = status?.pending ?? null;
  const run = status?.run ?? null;
  const active = !!pending || (!!run && (watching || run.state === "running"));
  // succeeded | failed once the list has caught up
  const outcome = !pending && run ? (run.state === "succeeded" ? "succeeded" : run.state === "failed" ? "failed" : null) : null;
  return { status, unreachable, now, active, version: pending?.version ?? run?.version ?? listed?.version ?? "", outcome };
}

function progressTitle(p: InstallProgressModel): string {
  return p.outcome === "succeeded" ? `Veyra ${p.version} is installed`
    : p.outcome === "failed" ? `Installing Veyra ${p.version} failed`
      : `Installing Veyra ${p.version}`;
}

function progressTone(p: InstallProgressModel): "ok" | "danger" | "info" {
  return p.outcome === "failed" ? "danger" : p.outcome === "succeeded" ? "ok" : "info";
}

/** The timeline, the installer's live output and the outcome; the page shows
 * it in a callout, the review dialog in place of the release's details. */
function InstallProgressBody({ progress, reloadButton = true, fill = false }: { progress: InstallProgressModel; reloadButton?: boolean; fill?: boolean }) {
  const { status, unreachable, now, outcome } = progress;
  const logRef = useRef<HTMLPreElement>(null);

  // The log keeps showing its newest line.
  const run = status?.run ?? null;
  const lines = run?.log_tail ?? [];
  const lastLine = lines[lines.length - 1];
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastLine, lines.length]);

  const pending = status?.pending ?? null;
  const phase = pending?.phase ?? (run?.state === "running" ? "running" : null);

  // Stage states along the timeline.
  const order = ["queued", "starting", "running", "finishing"] as const;
  const at = (p: typeof order[number]) => {
    if (outcome) return "done" as StageState;
    const cur = phase === "window" ? -1 : order.indexOf((phase ?? "running") as typeof order[number]);
    const i = order.indexOf(p);
    return i < cur ? "done" : i === cur ? "current" : "later";
  };
  const approvedAt = pending?.approved_at ?? null;
  const total = secondsBetween(approvedAt ?? run?.started_at, outcome && run?.finished_at ? Date.parse(run.finished_at) : now);
  const sinceWorker = secondsBetween(pending?.worker_last_pass_at, now);
  const interval = pending?.worker_interval_seconds ?? 60;
  const waitLeft = sinceWorker === null ? null : Math.max(0, interval - sinceWorker);
  const installerSteps = lines.filter((l) => l.startsWith("==> ")).map((l) => l.slice(4));

  // In the dialog the output pane takes the remaining height and is the only
  // thing that scrolls; on the page it has a fixed height.
  const grow = fill ? { flex: "1 1 auto", minHeight: 0 } : {};
  return (
    <div className="stack stack--sm" style={fill ? { flex: "1 1 auto", minHeight: 0 } : undefined}>
      <p>
        {unreachable ? <strong>Veyra is restarting; this page reconnects by itself.</strong> : null}
        {unreachable ? " " : ""}
        {total !== null ? <>{outcome ? "Took" : "Running for"} {elapsedLabel(total)}{approvedAt ? " since the approval" : ""}. </> : null}
        Calls are not affected.
      </p>
      <ol className="stepper" aria-label="Installation stages">
        <Stage index={1} state="done" title="Approved"
          note={pending?.approved_by || approvedAt ? <>{pending?.approved_by ? `by ${pending.approved_by}` : ""}{approvedAt ? ` at ${formatDateTime(approvedAt)}` : ""}</> : undefined} />
        {phase === "window" ? (
          <Stage index={2} state="current" title="Waiting for the maintenance window"
            note={pending?.next_window ? `Next window ${formatDateTime(pending.next_window)}; starts when no call is in progress.` : "Starts in the next window when no call is in progress."} />
        ) : (
          <Stage index={2} state={at("queued")} title="Pre-checks passed, upgrade service started"
            note={at("queued") === "current"
              ? `The approval did not start the upgrade service directly; the background worker will, on its next pass (every ${interval} s${waitLeft !== null ? `, in about ${waitLeft} s` : ""}), after the pre-checks (disk space, modules, no other upgrade).`
              : pending?.install_started_at ? `at ${formatDateTime(pending.install_started_at)}` : undefined} />
        )}
        <Stage index={3} state={at("starting")} title="Release verified and unpacked"
          note={at("starting") === "current" ? "The upgrade service checks the signature, size and checksum of the downloaded release and unpacks it into a private directory." : undefined} />
        <Stage index={4} state={at("running")} title="Installer running"
          note={run && run.state === "running" ? <>Step: <strong>{run.step}</strong></>
            : outcome ? `${installerSteps.length || "all"} steps` : undefined} />
        <Stage index={5} state={outcome ? "done" : at("finishing")} title={outcome === "failed" ? "Failed" : "Finished"}
          note={outcome === "succeeded" && run?.finished_at ? `at ${formatDateTime(run.finished_at)}`
            : at("finishing") === "current" ? "The new version is recording the result and sending the notification." : undefined} />
      </ol>
      {outcome === "succeeded" && reloadButton ? (
        <p><Button size="sm" onClick={() => window.location.reload()}>Reload the page</Button> to use the new version.</p>
      ) : null}
      {run?.error ? <p>{run.error}</p> : null}
      {pending?.error ? <p>{pending.error}</p> : null}
      {run?.log_file ? <p className="subtle" style={{ flex: "0 0 auto", margin: 0 }}>Full log on the server: <code>{run.log_file}</code></p> : null}
      {lines.length ? (
        <details open={outcome !== "succeeded"} style={fill ? { display: "flex", flexDirection: "column", overflow: "hidden", ...grow } : undefined}>
          <summary>Installer output{run?.state === "running" ? " (live)" : ""}</summary>
          <pre ref={logRef} className="mono" style={{ ...(fill ? { ...grow, maxHeight: "60vh" } : { maxHeight: 240 }), overflow: "auto", whiteSpace: "pre-wrap", margin: 0 }}>{lines.join("\n")}</pre>
        </details>
      ) : null}
    </div>
  );
}

function SourceCard({ editable, onSaved }: { editable: boolean; onSaved: () => void }) {
  const toast = useToast();
  const source = useApiData<UpdateSource>("/updates/source");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [removeToken, setRemoveToken] = useState(false);
  const [recipients, setRecipients] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useOnChange(source.data, (s) => {
    if (!s) return;
    setUrl(s.url);
    setToken("");
    setRemoveToken(false);
    setRecipients(s.recipients.join(", "));
  });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.put<UpdateSource>("/updates/source", {
        url: url.trim(),
        token: removeToken ? "" : token.trim() ? token.trim() : null,
        recipients: recipients.split(/[\s,;]+/).filter(Boolean),
      });
      source.setData(saved);
      onSaved();
      toast.success("Update source saved");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (source.error) return <Card title="Update source"><ErrorState compact error={source.error} onRetry={source.reload} /></Card>;
  if (!source.data) return <Card title="Update source"><LoadingState /></Card>;
  const s = source.data;
  return (
    <Card title="Update source" footer={editable ? <Button variant="primary" size="sm" onClick={save} loading={busy}>Save</Button> : undefined}>
      <div className="stack stack--sm">
        <p className="muted">The address of the signed release information (for example <code>…/stable.json</code>). Only releases signed by an official Veyra key are accepted.</p>
        <TextField label="Metadata address" value={url} disabled={!editable} placeholder={s.env_url || "https://…/stable.json"}
          help={s.env_url && !url ? `Empty: the server's setting is used (${s.env_url}).` : undefined}
          onChange={(e) => setUrl(e.target.value)} />
        <TextField label="Access token" type="password" autoComplete="off" value={token} disabled={!editable || removeToken}
          placeholder={s.token_set ? "Saved (enter a new one to replace it)" : "Not needed for a public source"}
          help="A read-only token for a private source (sent only to the source, never shown again)."
          onChange={(e) => setToken(e.target.value)} />
        {s.token_set && editable ? <Checkbox label="Remove the saved token" checked={removeToken} onChange={(e) => setRemoveToken(e.target.checked)} /> : null}
        <TextArea label="Email notifications to" rows={2} value={recipients} disabled={!editable}
          help="Addresses told when a release is available, downloaded, installed or failed (System → Settings → Email must be on)."
          onChange={(e) => setRecipients(e.target.value)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Card>
  );
}

function ReviewDialog({ id, editable, progress, onClose, onChanged }: {
  id: string; editable: boolean; progress: InstallProgressModel; onClose: () => void; onChanged: () => void;
}) {
  const toast = useToast();
  const detail = useApiData<UpdateDetail>(`/updates/available/${id}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "Install now" keeps the dialog open on the installation's progress, with
  // a reload button at the end; closing it leaves the page's callout.
  const [installing, setInstalling] = useState(false);

  const act = async (what: "download" | "now" | "window" | "cancel") => {
    setBusy(what);
    setError(null);
    try {
      if (what === "download") {
        await api.post(`/updates/available/${id}/download`);
        toast.success("Downloaded and verified");
      } else if (what === "cancel") {
        await api.post(`/updates/available/${id}/cancel`);
        toast.info("Approval withdrawn");
      } else {
        await api.post(`/updates/available/${id}/approve`, { when: what });
        onChanged();
        if (what === "now") {
          toast.success("Installation started");
          setInstalling(true);
        } else {
          toast.success("Will install in the next maintenance window");
          onClose();
        }
        return;
      }
      detail.reload();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const d = detail.data;
  const blocked = d ? d.checks.some((c) => !c.ok) : true;
  // Opened again while an installation of this release runs: show it too.
  const showProgress = installing
    || (!!d && progress.active && progress.version === d.version && ["approved", "installing", "installed"].includes(d.state));
  if (showProgress) {
    const title = progress.active ? progressTitle(progress) : `Installing Veyra ${d?.version ?? ""}`;
    return (
      <Dialog open onClose={onClose} size="lg" scroll="inner" title={title}
        description="This window follows the installation live. Calls are not affected."
        footer={(
          <>
            <Button onClick={onClose}>Close</Button>
            {progress.outcome === "succeeded" ? <Button variant="primary" icon="refresh" onClick={() => window.location.reload()}>Reload the page</Button> : null}
          </>
        )}>
        {progress.active ? <InstallProgressBody progress={progress} reloadButton={false} fill /> : <LoadingState label="Starting the installation…" />}
      </Dialog>
    );
  }
  const footer = d && editable ? (
    <>
      <Button onClick={onClose} disabled={!!busy}>Close</Button>
      {["available", "failed"].includes(d.state) ? <Button variant="primary" onClick={() => act("download")} loading={busy === "download"}>Download and verify</Button> : null}
      {d.state === "downloaded" ? (
        <>
          {d.window ? <Button onClick={() => act("window")} loading={busy === "window"} disabled={blocked || !!busy}>Install in maintenance window</Button> : null}
          <Button variant="primary" onClick={() => act("now")} loading={busy === "now"} disabled={blocked || !!busy}>Install now</Button>
        </>
      ) : null}
      {d.state === "approved" ? <Button variant="danger" onClick={() => act("cancel")} loading={busy === "cancel"}>Withdraw approval</Button> : null}
    </>
  ) : <Button onClick={onClose}>Close</Button>;

  return (
    <Dialog open onClose={onClose} busy={!!busy} size="lg" title={d ? `Veyra ${d.version}` : "Update"}
      description={d ? `From ${d.current_version ?? "?"} · ${d.category} · ${d.channel} channel` : undefined} footer={footer}>
      {detail.error ? <ErrorState compact error={detail.error} onRetry={detail.reload} /> : !d ? <LoadingState /> : (
        <div className="stack stack--sm">
          <dl className="dl">
            <dt>State</dt><dd><Badge tone={STATE[d.state]?.tone ?? "neutral"}>{STATE[d.state]?.label ?? d.state}</Badge>{d.approved_by ? <span className="subtle"> · approved by {d.approved_by}</span> : null}</dd>
            <dt>Download</dt><dd>{formatSize(d.size)}{d.downloaded_at ? ` · verified ${formatRelative(d.downloaded_at)}` : ""}</dd>
            <dt>Service impact</dt><dd>{d.service_impact || "The web interface and API restart (usually under a minute). Calls are not affected."}</dd>
            {d.window ? <><dt>Maintenance window</dt><dd>{d.window.days.join(", ")} {d.window.start} for {d.window.duration_minutes} min ({d.window.timezone}){d.next_window ? ` · next ${formatDateTime(d.next_window)}` : ""}</dd></> : null}
          </dl>
          {d.release_notes ? (
            <div>
              <h3 className="card__title">Release notes</h3>
              <p style={{ whiteSpace: "pre-wrap" }}>{d.release_notes}</p>
            </div>
          ) : null}
          <div>
            <h3 className="card__title">Checks</h3>
            <ul className="stack stack--sm" style={{ listStyle: "none", padding: 0 }}>
              {d.checks.map((c) => (
                <li key={c.key}><Badge tone={c.ok ? "ok" : "danger"}>{c.ok ? "OK" : "Blocked"}</Badge> {c.message}</li>
              ))}
            </ul>
          </div>
          <p className="subtle">
            Installing runs the release&apos;s own upgrade on the server: the database and configuration are backed up first,
            the release is verified again against the official signing key, and a failed database step restores the previous version.
          </p>
          {d.error ? <Callout tone="danger">{d.error}</Callout> : null}
          {error ? <Callout tone="danger">{error}</Callout> : null}
        </div>
      )}
    </Dialog>
  );
}

function SystemPackagesCard({ data, error, onRetry }: { data: SystemPackages | undefined; error: unknown; onRetry: () => void }) {
  const columns: Column<SystemPackages["packages"][number]>[] = [
    { key: "name", header: "Package", render: (p) => <span className="mono">{p.name}</span> },
    { key: "version", header: "Version", render: (p) => <span className="mono">{p.from ?? "?"} → {p.version}</span> },
    {
      key: "kind", header: "Type", render: (p) => (
        <>
          {p.security ? <Badge tone="danger">security</Badge> : null}{" "}
          {p.telephony ? <Badge tone="warn">restarts Asterisk</Badge> : null}
        </>
      ),
    },
  ];
  return (
    <Card title="Operating system packages" flush
      subtitle={data?.checked_at ? `${data.counts.total} upgradable (${data.counts.security} security) · checked ${formatRelative(data.checked_at)}` : "Checked daily by the worker"}>
      {data?.error ? <div style={{ padding: "0 var(--space-4)" }}><Callout tone="warn">{data.error}</Callout></div> : null}
      <DataTable columns={columns} rows={data?.packages.slice(0, 50)} rowKey={(p) => p.name} loading={!data && !error} error={error} onRetry={onRetry}
        caption="Upgradable operating system packages"
        empty={<EmptyState compact icon="checkCircle" title="Up to date">{data?.checked_at ? "No package upgrades are waiting." : "Not checked yet."}</EmptyState>} />
      <p className="subtle" style={{ padding: "var(--space-3) var(--space-4)" }}>
        Shown only: apply them on the server with <code>sudo apt upgrade</code> or unattended-upgrades. Upgrading Asterisk restarts it and drops calls in progress.
      </p>
    </Card>
  );
}

function PolicyCard({ policy, availableModes, editable, onSaved }: {
  policy: UpdatePolicy; availableModes: UpdateMode[]; editable: boolean; onSaved: (p: UpdatePolicy) => void;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<UpdateMode>(policy.mode);
  const [channel, setChannel] = useState(policy.channel);
  const [checkEnabled, setCheckEnabled] = useState(policy.check_enabled);
  const [interval, setInterval_] = useState(String(policy.check_interval_hours));
  const [notify, setNotify] = useState(policy.notify_admins);
  const [categories, setCategories] = useState<string[]>(policy.auto_install_categories);
  const [window_, setWindow] = useState<MaintenanceWindow | null>(policy.maintenance_window);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useOnChange(policy, (p) => {
    setMode(p.mode);
    setChannel(p.channel);
    setCheckEnabled(p.check_enabled);
    setInterval_(String(p.check_interval_hours));
    setNotify(p.notify_admins);
    setCategories(p.auto_install_categories);
    setWindow(p.maintenance_window);
  });

  const core = policy.component === "veyra_core";
  const external = policy.component === "operating_system" || policy.component === "telephony_engine";
  const allowedModes = core ? availableModes : availableModes.filter((m) => m === "manual" || m === "notify");
  const dirty = mode !== policy.mode || channel !== policy.channel || checkEnabled !== policy.check_enabled
    || interval !== String(policy.check_interval_hours) || notify !== policy.notify_admins
    || JSON.stringify(categories) !== JSON.stringify(policy.auto_install_categories)
    || JSON.stringify(window_) !== JSON.stringify(policy.maintenance_window);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.put<UpdatePolicy>(`/updates/policies/${policy.component}`, {
        mode, channel, check_enabled: checkEnabled, check_interval_hours: Number(interval), notify_admins: notify,
        auto_download: false,
        auto_install_categories: mode === "auto_install_window" ? categories : [],
        require_approval: true,
        maintenance_window: core ? window_ : null,
      });
      onSaved({ ...saved, label: policy.label });
      toast.success("Policy saved", policy.label);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (list: string[], v: string, on: boolean) => (on ? [...list, v] : list.filter((x) => x !== v));
  const modeHelp = MODES.find((m) => m.value === mode)?.help;
  return (
    <Card title={policy.label} subtitle={`Last changed ${formatRelative(policy.updated_at)}`}
      footer={editable ? <Button variant="primary" size="sm" onClick={save} loading={busy} disabled={!dirty}>Save policy</Button> : undefined}>
      <div className="stack stack--sm">
        {external ? (
          <Callout tone="neutral">Applied with the server&apos;s package manager; the upgradable packages are listed under “Operating system packages”.</Callout>
        ) : null}
        <div className="form-grid">
          <SelectField label="Update behaviour" value={mode} disabled={!editable} help={modeHelp}
            options={MODES.map((m) => ({ value: m.value, label: allowedModes.includes(m.value) ? m.label : `${m.label} (Veyra only)`, disabled: !allowedModes.includes(m.value) }))}
            onChange={(e) => setMode(e.target.value as UpdateMode)} />
          <SelectField label="Release channel" value={channel} disabled={!editable}
            help={channel === "stable" ? "Recommended for production." : "Pre-release software. Not recommended for production systems."}
            options={[{ value: "stable", label: "Stable" }, { value: "beta", label: "Beta" }, { value: "development", label: "Development" }]}
            onChange={(e) => setChannel(e.target.value as UpdatePolicy["channel"])} />
        </div>
        <div className="form-grid">
          <Switch label="Check for updates automatically" checked={checkEnabled} disabled={!editable || external || mode === "manual"} onChange={(e) => setCheckEnabled(e.target.checked)} />
          <TextField label="Check every (hours)" type="number" min={1} max={720} value={interval} disabled={!editable || !checkEnabled || mode === "manual"} onChange={(e) => setInterval_(e.target.value)} />
        </div>
        <Switch label="Notify administrators" checked={notify} disabled={!editable} onChange={(e) => setNotify(e.target.checked)} />
        {core ? (
          <fieldset className="stack stack--sm" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="card__title">Maintenance window</legend>
            <Switch label="Use a maintenance window" checked={!!window_} disabled={!editable}
              description="Approved updates can wait for it; in automatic mode, chosen categories install in it when no call is in progress."
              onChange={(e) => setWindow(e.target.checked ? { days: ["sat"], start: "02:00", duration_minutes: 120, timezone: browserTimeZone() } : null)} />
            {window_ ? (
              <>
                <div className="row" role="group" aria-label="Days">
                  {DAYS.map(([v, l]) => (
                    <Checkbox key={v} label={l} checked={window_.days.includes(v)} disabled={!editable}
                      onChange={(e) => setWindow({ ...window_, days: toggle(window_.days, v, e.target.checked) })} />
                  ))}
                </div>
                <div className="form-grid">
                  <TextField label="Starts at" type="time" value={window_.start} disabled={!editable} onChange={(e) => setWindow({ ...window_, start: e.target.value })} />
                  <TextField label="Length (minutes)" type="number" min={30} max={720} value={String(window_.duration_minutes)} disabled={!editable}
                    onChange={(e) => setWindow({ ...window_, duration_minutes: Number(e.target.value) })} />
                  <SelectField label="Time zone" value={window_.timezone} disabled={!editable}
                    options={timeZones().map((z) => ({ value: z, label: z }))} onChange={(e) => setWindow({ ...window_, timezone: e.target.value })} />
                </div>
              </>
            ) : null}
            {mode === "auto_install_window" ? (
              <div className="row" role="group" aria-label="Install automatically">
                <span className="muted">Install automatically:</span>
                {(["security", "bugfix", "feature"] as const).map((c) => (
                  <Checkbox key={c} label={c === "bugfix" ? "Bug fixes" : c === "security" ? "Security" : "Features"} checked={categories.includes(c)} disabled={!editable}
                    onChange={(e) => setCategories(toggle(categories, c, e.target.checked))} />
                ))}
              </div>
            ) : null}
          </fieldset>
        ) : null}
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </div>
    </Card>
  );
}
