// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useMemo, useState } from "react";
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
  Icon,
  PageHeader,
  SelectField,
  StatusBadge,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { formatBytes, formatDateTime, formatDuration, formatRelative } from "@/lib/format";
import type { CaptureList, CaptureRow, CaptureTarget, CaptureTargets, SipDialog, SipMessage, SipSummary } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useBrowserStore } from "@/hooks/useBrowserStore";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";

const REFRESH_MS = 5_000;
const NOTICE_KEY = "veyra.captures.notice";

const STATE: Record<string, { status: "ok" | "degraded" | "failed" | "unavailable" | "unknown"; label: string }> = {
  starting: { status: "degraded", label: "Starting" },
  running: { status: "degraded", label: "Running" },
  finished: { status: "ok", label: "Finished" },
  stopped: { status: "ok", label: "Stopped" },
  failed: { status: "failed", label: "Failed" },
};

const TARGETS: { value: CaptureTarget; label: string }[] = [
  { value: "all_sip", label: "All SIP" },
  { value: "extension", label: "An extension (where its phone registers from)" },
  { value: "trunk", label: "A trunk" },
  { value: "address", label: "An address or network" },
];

function StartForm({ targets, limits, disabled, onStarted }: { targets: CaptureTargets | undefined; limits: CaptureList["limits"] | undefined; disabled: boolean; onStarted: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [target, setTarget] = useState<CaptureTarget>("all_sip");
  const [extensionId, setExtensionId] = useState("");
  const [trunkId, setTrunkId] = useState("");
  const [address, setAddress] = useState("");
  const [rtp, setRtp] = useState(false);
  const [minutes, setMinutes] = useState("2");
  const [mb, setMb] = useState("50");
  const [busy, setBusy] = useState(false);
  const maxMinutes = Math.floor((limits?.seconds[1] ?? 1800) / 60);
  const maxMb = limits?.mb[1] ?? 500;

  const start = async () => {
    setBusy(true);
    errors.clear();
    try {
      await api.post("/diagnostics/captures", {
        target,
        extension_id: target === "extension" ? extensionId || null : null,
        trunk_id: target === "trunk" ? trunkId || null : null,
        address: target === "address" ? address.trim() : null,
        rtp,
        duration_seconds: Math.round(Number(minutes) * 60),
        size_limit_mb: Number(mb),
      });
      toast.success("Capture started");
      onStarted();
    } catch (err) {
      errors.set(err);
      toast.error("Could not start the capture", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const extensions = targets?.extensions ?? [];
  const trunks = targets?.trunks ?? [];
  const chosenExt = extensions.find((e) => e.id === extensionId);
  return (
    <Card title="Start a capture" subtitle="Capturing begins a few seconds after Start, while the row shows “Starting”; reproduce the problem once it shows “Running”." actions={<Button variant="primary" icon="plus" onClick={start} loading={busy} disabled={disabled}>Start</Button>}>
      <div className="stack stack--sm">
        <div className="grid grid--2">
          <SelectField label="Capture" value={target} options={TARGETS} onChange={(e) => setTarget(e.target.value as CaptureTarget)} />
          {target === "extension" ? (
            <SelectField label="Extension" value={extensionId} placeholder="Choose an extension" error={errors.fields["extension_id"]}
              options={extensions.map((e) => ({ value: e.id, label: `${e.number} ${e.display_name}${e.hosts.length ? ` · ${e.hosts.join(", ")}` : " · not registered"}` }))}
              onChange={(e) => setExtensionId(e.target.value)}
              help={chosenExt && !chosenExt.hosts.length ? "No phone is registered for this extension right now; the capture needs an address." : "Traffic to and from the address the phone registers from, on the SIP ports."} />
          ) : target === "trunk" ? (
            <SelectField label="Trunk" value={trunkId} placeholder="Choose a trunk" error={errors.fields["trunk_id"]}
              options={trunks.map((t) => ({ value: t.id, label: `${t.name} · ${t.host}:${t.port}` }))} onChange={(e) => setTrunkId(e.target.value)}
              help="Traffic to and from the trunk's host on its port and the SIP ports." />
          ) : target === "address" ? (
            <TextField label="Address or network" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="192.168.1.20 or 10.0.0.0/8" spellCheck={false}
              error={errors.fields["address"]} help="An IP address, a host name or a network in CIDR notation, on the SIP ports." />
          ) : (
            <TextField label="Ports" value={(targets?.sip_ports ?? []).join(", ")} readOnly help="Every SIP transport this server listens on." />
          )}
        </div>
        <div className="grid grid--3">
          <TextField label="Duration (minutes)" type="number" min={1} max={maxMinutes} value={minutes} onChange={(e) => setMinutes(e.target.value)} error={errors.fields["duration_seconds"]} help={`Up to ${maxMinutes} minutes.`} />
          <TextField label="Size limit (MB)" type="number" min={1} max={maxMb} value={mb} onChange={(e) => setMb(e.target.value)} error={errors.fields["size_limit_mb"]} help={`Up to ${maxMb} MB; the capture stops when it is reached.`} />
          <Checkbox label="Include RTP (media)" checked={rtp} onChange={(e) => setRtp(e.target.checked)}
            description={`The RTP port range${targets ? ` ${targets.rtp_range[0]}–${targets.rtp_range[1]}` : ""}. Media is call content: include it only to diagnose audio problems.`} />
        </div>
      </div>
    </Card>
  );
}

function SipView({ capture, onClose }: { capture: CaptureRow | null; onClose: () => void }) {
  const summary = useApiData<SipSummary>(capture ? `/diagnostics/captures/${capture.id}/sip` : null);
  const [dialog, setDialog] = useState<string | null>(null); // reset by the key on <SipView>
  const d = summary.data;
  const messages = useMemo(() => (d?.messages ?? []).filter((m) => !dialog || (m.call_id ?? "") === dialog), [d, dialog]);
  const dialogColumns: Column<SipDialog>[] = [
    { key: "first", header: "Started", render: (x) => <span className="nowrap">{formatDateTime(x.first_at)}</span> },
    { key: "method", header: "Dialog", render: (x) => <span className="mono">{x.method ?? "—"}</span> },
    { key: "from", header: "From → To", render: (x) => <span className="table__secondary">{x.from ?? "—"} → {x.to ?? "—"}</span> },
    { key: "parties", header: "Between", render: (x) => <span className="mono">{x.parties.join(" ↔ ")}</span> },
    { key: "status", header: "Last answer", render: (x) => x.last_status ? <Badge tone={x.last_status < 300 ? "ok" : x.last_status < 400 ? "neutral" : "danger"}>{x.last_status} {x.last_reason ?? ""}</Badge> : <span className="subtle">none</span> },
    { key: "n", header: "Messages", render: (x) => x.messages },
  ];
  const messageColumns: Column<SipMessage>[] = [
    { key: "at", header: "Time", render: (m) => <span className="nowrap mono">{m.at.slice(11, 23)}</span> },
    { key: "what", header: "Message", render: (m) => m.kind === "request" ? <span className="mono">{m.method} {m.request_uri}</span> : <span className="mono">{m.status} {m.reason} <span className="table__secondary">({m.method})</span></span> },
    { key: "src", header: "From", render: (m) => <span className="mono">{m.src}:{m.sport}</span> },
    { key: "dst", header: "To", render: (m) => <span className="mono">{m.dst}:{m.dport}</span> },
    { key: "ua", header: "Agent", render: (m) => <span className="subtle">{m.user_agent ?? "—"}</span> },
  ];
  return (
    <Dialog open={!!capture} onClose={onClose} size="lg" title={capture ? `SIP in “${capture.label}”` : ""}
      description="One row per SIP message, grouped into dialogs by Call-ID. Pick a dialog to see only its messages.">
      {summary.error ? <Callout tone="danger" title="Could not read the capture">{errorMessage(summary.error)}</Callout> : null}
      {d ? (
        <div className="stack stack--sm">
          <p className="subtle">{d.packets_read} packets read, {d.messages.length} SIP messages in {d.dialogs.length} dialog{d.dialogs.length === 1 ? "" : "s"}.{d.truncated ? " The file is large; only the first part was read." : ""}</p>
          <DataTable columns={dialogColumns} rows={d.dialogs} rowKey={(x) => x.call_id} caption="SIP dialogs"
            onRowClick={(x) => setDialog(dialog === x.call_id ? null : x.call_id)} rowLabel={(x) => `Show messages of ${x.call_id}`}
            empty={<EmptyState compact icon="search" title="No SIP messages">Nothing in this capture starts a SIP message. For TLS transports the content is encrypted.</EmptyState>} />
          {dialog ? <p className="subtle">Messages of <span className="mono">{dialog}</span> · <button type="button" className="link" onClick={() => setDialog(null)}>show all</button></p> : null}
          {d.messages.length ? <DataTable columns={messageColumns} rows={messages} rowKey={(m, ) => `${m.at}|${m.src}|${m.sport}|${m.cseq}|${m.kind}`} caption="SIP messages" /> : null}
        </div>
      ) : !summary.error ? <p className="subtle">Reading the capture…</p> : null}
    </Dialog>
  );
}

export default function DiagnosticsPage() {
  const { can } = useSession();
  const toast = useToast();
  const manage = can("diagnostics.capture");
  const list = useApiData<CaptureList>("/diagnostics/captures");
  const targets = useApiData<CaptureTargets>(manage ? "/diagnostics/captures/targets" : null);
  const [noticeSeen, setNoticeSeen] = useBrowserStore(NOTICE_KEY, "");
  const [pendingDownload, setPendingDownload] = useState<CaptureRow | null>(null);
  const [remove, setRemove] = useState<CaptureRow | null>(null);
  const [sip, setSip] = useState<CaptureRow | null>(null);
  const [busy, setBusy] = useState(false);
  const reload = list.reload;
  const active = (list.data?.running ?? 0) > 0;
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [active, reload]);

  const downloadUrl = (c: CaptureRow) => `${API_BASE}/diagnostics/captures/${c.id}/download`;
  const download = (c: CaptureRow) => {
    if (!noticeSeen) { setPendingDownload(c); return; }
    window.location.assign(downloadUrl(c));
  };
  const stop = async (c: CaptureRow) => {
    setBusy(true);
    try {
      await api.post(`/diagnostics/captures/${c.id}/stop`);
      toast.success("Stopping the capture");
      setTimeout(reload, 1500);
    } catch (err) {
      toast.error("Could not stop the capture", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const doDelete = async () => {
    if (!remove) return;
    setBusy(true);
    try {
      await api.del(`/diagnostics/captures/${remove.id}`);
      toast.success("Capture deleted");
      setRemove(null);
      reload();
    } catch (err) {
      toast.error("Could not delete the capture", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<CaptureRow>[] = [
    { key: "when", header: "Started", render: (c) => <span><span className="table__primary" style={{ display: "block" }}>{formatDateTime(c.started_at)}</span><span className="table__secondary">{c.created_by}</span></span> },
    { key: "what", header: "Capture", render: (c) => <span><span style={{ display: "block" }}>{c.label}{c.rtp ? <> <Badge tone="warn">RTP</Badge></> : null}</span><span className="table__secondary mono" title={c.expression}>{c.expression}</span></span> },
    { key: "state", header: "State", render: (c) => <span className="row"><StatusBadge status={STATE[c.state]?.status ?? "unknown"} label={STATE[c.state]?.label ?? c.state} />{c.error ? <span className="table__secondary">{c.error}</span> : null}</span> },
    { key: "len", header: "Length", render: (c) => <span className="nowrap">{c.finished_at ? formatDuration(Math.max(0, (new Date(c.finished_at).getTime() - new Date(c.started_at).getTime()) / 1000)) : `${formatRelative(c.started_at)} · up to ${formatDuration(c.duration_seconds)}`}</span> },
    { key: "size", header: "Size", render: (c) => <span className="nowrap">{c.bytes ? formatBytes(c.bytes) : "—"}{c.packets !== null ? <span className="table__secondary"> · {c.packets} pkts</span> : null}</span> },
    {
      key: "actions", header: "", render: (c) => (
        <span className="row">
          {c.downloadable ? <Button size="sm" onClick={() => setSip(c)} icon="search">SIP</Button> : null}
          {manage && c.downloadable ? <Button size="sm" onClick={() => download(c)} icon="download">Download</Button> : null}
          {manage && (c.state === "running" || c.state === "starting") ? <Button size="sm" variant="danger" onClick={() => stop(c)} loading={busy}>Stop</Button> : null}
          {manage && c.state !== "running" && c.state !== "starting" ? <Button size="sm" variant="danger" onClick={() => setRemove(c)}>Delete</Button> : null}
        </span>
      ),
    },
  ];

  return (
    <div className="stack">
      <PageHeader title="Diagnostics" description="Packet captures of SIP (and, when asked for, RTP) taken on this server, with a SIP summary that needs no other tool. Captures can contain call content and personal data; they are kept for the retention period and every download is audited."
        actions={<Button icon="refresh" onClick={reload} loading={list.loading && !!list.data}>Refresh</Button>} />
      {manage ? <StartForm targets={targets.data} limits={list.data?.limits} disabled={!!list.data && list.data.running >= list.data.max_running} onStarted={reload} /> : null}
      {list.data && list.data.running >= list.data.max_running ? <Callout tone="info" title="Captures running">{list.data.max_running} captures run at a time. Stop one to start another.</Callout> : null}
      <Card title="Captures" flush>
        <DataTable columns={columns} rows={list.data?.captures} rowKey={(c) => c.id} loading={list.loading && !list.data} error={list.error} onRetry={reload} caption="Packet captures"
          empty={<EmptyState compact icon="search" title="No captures yet">{manage ? "Start one above: all SIP, one extension, a trunk or an address." : "No capture has been taken."}</EmptyState>} />
      </Card>
      <SipView key={sip?.id ?? "none"} capture={sip} onClose={() => setSip(null)} />
      <ConfirmDialog open={!!pendingDownload} title="Before you download" confirmLabel="Download" onCancel={() => setPendingDownload(null)}
        onConfirm={() => { setNoticeSeen(new Date().toISOString()); const c = pendingDownload; setPendingDownload(null); if (c) window.location.assign(downloadUrl(c)); }}>
        <p>A capture holds the raw network traffic it matched: SIP messages with phone numbers, names and addresses, and with RTP the audio of calls. Treat the file as personal data, keep it only as long as the problem takes, and delete it here when done. Downloads are recorded in the audit log. This notice is shown once per browser.</p>
      </ConfirmDialog>
      <ConfirmDialog open={!!remove} title={`Delete the capture “${remove?.label ?? ""}”`} confirmLabel="Delete" tone="danger" busy={busy} onCancel={() => setRemove(null)} onConfirm={doDelete}>
        <p>The file is removed from this server. Copies you downloaded stay with you.</p>
      </ConfirmDialog>
      {manage ? <p className="subtle"><Icon name="download" size={12} /> Downloaded files open in Wireshark (<span className="mono">.pcap</span>). From the console: <span className="mono">sudo veyra capture start --host 192.168.1.20</span>, <span className="mono">list</span>, <span className="mono">stop</span>, <span className="mono">delete</span>.</p> : null}
    </div>
  );
}
