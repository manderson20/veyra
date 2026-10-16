// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Button, Callout, Checkbox, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { HaFencing, HaJoinTokenCreated, HaStatus, HaSwitchoverCheck } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

// ----------------------------------------------------------------- enable

export function EnableDialog({ open, status, onClose, onDone }: { open: boolean; status: HaStatus; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [name, setName] = useState(status.service.name || "");
  const [address, setAddress] = useState(status.service.address || "");
  const [prefix, setPrefix] = useState(String(status.service.prefix || 24));
  const [iface, setIface] = useState(status.service.interface || "");
  const [synchronous, setSynchronous] = useState(false);
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => errors.clear());

  const submit = async () => {
    setBusy(true);
    errors.clear();
    try {
      await api.post("/ha/enable", { name: name.trim(), address: address.trim(), prefix: Number(prefix), interface: iface.trim(), synchronous });
      toast.success("Enabling high availability", "PostgreSQL restarts once; the page follows the steps.");
      onDone();
      onClose();
    } catch (err) {
      errors.set(err);
      toast.error("Could not enable high availability", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Enable high availability" busy={busy} size="lg"
      description="This server becomes the primary of a two-node pair. A second server joins afterwards with the join token from this page."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" onClick={submit} loading={busy} disabled={!name || !address || !iface}>Enable</Button></>}>
      <div className="stack stack--sm">
        <Callout tone="warn" title="What changes">
          PostgreSQL is reconfigured for replication and restarted once (calls in progress are not affected; the web interface reconnects). The HTTPS certificate is reissued for the service name and both node names; if the certificate authority had to be widened, phones and browsers that trust it must trust the new copy.
        </Callout>
        <TextField label="Service name" value={name} onChange={(e) => setName(e.target.value)} required
          help="The name phones and browsers will use; it must resolve to the service address." placeholder="veyra.example.org" error={errors.fields["name"]} />
        <div className="grid grid--2">
          <TextField label="Service address" value={address} onChange={(e) => setAddress(e.target.value)} required placeholder="172.16.2.10"
            help="A free address on the nodes' shared network segment." error={errors.fields["address"]} />
          <TextField label="Prefix length" type="number" min={8} max={32} value={prefix} onChange={(e) => setPrefix(e.target.value)} error={errors.fields["prefix"]} />
        </div>
        <TextField label="Interface" value={iface} onChange={(e) => setIface(e.target.value)} required placeholder="ens18"
          help="The network interface on this server that carries the service address." error={errors.fields["interface"]} />
        <Switch label="Synchronous replication" checked={synchronous} onChange={(e) => setSynchronous(e.target.checked)}
          description="Off (recommended): the primary never waits for the standby. On: every write waits for the standby, and writes block while the standby is down." />
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- join token

export function JoinTokenDialog({ token, onClose }: { token: HaJoinTokenCreated | null; onClose: () => void }) {
  return (
    <Dialog open={!!token} onClose={onClose} title="Add a node" description="Copy the command now: the token is shown once and expires in 24 hours." size="lg"
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      {token ? (
        <div className="stack stack--sm">
          <p className="subtle">On the new server, with the same Veyra release unpacked, run:</p>
          <span className="row" style={{ gap: 8, alignItems: "flex-start" }}>
            <code className="mono" style={{ wordBreak: "break-all", flex: 1, display: "block", padding: "var(--space-3)", background: "var(--surface-2)", borderRadius: "var(--radius)" }}>{token.command}</code>
            <CopyButton text={token.command} />
          </span>
          <dl className="dl">
            <dt>Primary</dt><dd><code className="mono">{token.primary_url}</code></dd>
            <dt>Fingerprint</dt><dd><code className="mono">{token.fingerprint ?? "—"}</code> <span className="subtle">(this node&apos;s key; compare it on the new server)</span></dd>
            <dt>Expires</dt><dd>{formatDateTime(token.expires_at)}</dd>
          </dl>
          <p className="subtle">The installer copies the credentials and certificates, takes a copy of the database and starts replication. Asterisk is installed but stays stopped on the standby.</p>
        </div>
      ) : null}
    </Dialog>
  );
}

// ----------------------------------------------------------------- switchover

export function SwitchoverDialog({ open, target, onClose, onDone }: { open: boolean; target: string | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const check = useApiData<HaSwitchoverCheck>(open && target ? "/ha/switchover-check" : null, { target: target ?? "" });
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  useOnChange(open, () => setTyped(""));

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/ha/switchover", { target });
      toast.success(`Switching over to ${target}`, "Calls in progress end; phones re-register within their expiry.");
      onDone();
      onClose();
    } catch (err) {
      toast.error("Switchover not started", errorMessage(err));
      check.reload();
    } finally {
      setBusy(false);
    }
  };

  const ok = !!check.data?.ok;
  return (
    <Dialog open={open} onClose={onClose} title={`Switch over to ${target ?? ""}`} busy={busy}
      description="A planned switchover: the standby becomes the primary while both nodes are up."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="danger" onClick={submit} loading={busy} disabled={!ok || typed !== (target ?? "")}>Switch over</Button></>}>
      <div className="stack stack--sm">
        <Callout tone="warn" title="Calls in progress end">
          Asterisk stops on the current primary and starts on {target}. Phones re-register within their registration expiry; trunks re-register at once. Takes about a minute.
        </Callout>
        {check.loading && !check.data ? <p className="subtle">Checking preconditions…</p> : check.data ? (
          check.data.ok ? <Callout tone="ok" title="Preconditions met">Both nodes online and on the same version, replication streaming with little lag, file sync fresh, nothing else in progress.</Callout> : (
            <Callout tone="danger" title="Not possible now">
              <ul style={{ margin: 0, paddingLeft: "1.2em" }}>{check.data.problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </Callout>
          )
        ) : null}
        <TextField label={<>Type <code>{target}</code> to confirm</>} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- failover

export function FailoverDialog({ open, status, onClose, onDone }: { open: boolean; status: HaStatus; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [confirmed, setConfirmed] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => { setConfirmed(false); setTyped(""); });
  const peer = status.peer;
  const fencing = status.fencing.configured;

  const submit = async () => {
    setBusy(true);
    try {
      await api.post("/ha/failover", { confirm_fenced: confirmed });
      toast.success("Failing over", "This node is becoming the primary.");
      onDone();
      onClose();
    } catch (err) {
      toast.error("Failover not started", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Fail over to this node" busy={busy}
      description="Only when the primary is down. Two primaries would both take calls and write the database."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="danger" onClick={submit} loading={busy} disabled={(!fencing && !confirmed) || typed !== "FAIL OVER"}>Fail over</Button></>}>
      <div className="stack stack--sm">
        <dl className="dl">
          <dt>Primary</dt><dd>{peer?.node_name ?? "unknown"} · last heartbeat {peer?.last_heartbeat_at ? formatDateTime(peer.last_heartbeat_at) : "never"}</dd>
          <dt>Replication at that moment</dt><dd>{status.replication?.replay_lsn ?? "—"} {status.replication?.replay_at ? `(replayed ${formatDateTime(status.replication.replay_at)})` : ""}</dd>
          <dt>Possible data loss</dt><dd>Writes after the last replayed transaction and files changed since the last sync ({status.sync?.last_success_at ? formatDateTime(status.sync.last_success_at) : "never"}).</dd>
        </dl>
        {fencing ? (
          <Callout tone="info" title="Fencing is configured">The old primary&apos;s VM is stopped through Proxmox before this node is promoted; if that fails, the failover stops.</Callout>
        ) : (
          <Checkbox label={`I confirm ${peer?.node_name ?? "the primary"} is powered off or disconnected`} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
            description="No fencing is configured: your confirmation is recorded in the audit log." />
        )}
        <TextField label={<>Type <code>FAIL OVER</code> to confirm</>} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- fencing

export function FencingDialog({ open, nodes, onClose, onSaved }: { open: boolean; nodes: string[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const current = useApiData<HaFencing>(open ? "/ha/fencing" : null);
  const [enabled, setEnabled] = useState(false);
  const [url, setUrl] = useState("");
  const [tokenId, setTokenId] = useState("");
  const [secret, setSecret] = useState("");
  const [pveNode, setPveNode] = useState("");
  const [vms, setVms] = useState<Record<string, string>>({});
  const [verify, setVerify] = useState(true);
  const [caPem, setCaPem] = useState("");
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<string | null>(null);
  useOnChange(current.data, (f) => {
    if (!f) return;
    setEnabled(f.enabled); setUrl(f.url); setTokenId(f.token_id); setPveNode(f.pve_node); setVerify(f.verify_tls); setCaPem(f.ca_pem);
    setVms(Object.fromEntries(Object.entries(f.vms).map(([k, v]) => [k, String(v.vmid)])));
    setSecret("");
  });

  const body = () => ({
    enabled, url: url.trim(), token_id: tokenId.trim(), token_secret: secret || null, pve_node: pveNode.trim(), verify_tls: verify, ca_pem: caPem,
    vms: Object.fromEntries(Object.entries(vms).filter(([, v]) => v.trim()).map(([k, v]) => [k, { vmid: Number(v) }])),
  });

  const save = async () => {
    setBusy(true);
    errors.clear();
    try {
      await api.put("/ha/fencing", body());
      toast.success("Fencing settings saved");
      onSaved();
      onClose();
    } catch (err) {
      errors.set(err);
      toast.error("Could not save fencing", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setBusy(true);
    setTest(null);
    try {
      await api.put("/ha/fencing", body());
      const r = await api.post<{ ok: boolean; status?: string; error?: string; node?: string }>("/ha/fencing/test");
      setTest(r.ok ? `Proxmox answers: VM of ${r.node} is ${r.status}` : `Failed: ${r.error}`);
    } catch (err) {
      setTest(`Failed: ${errorMessage(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Fencing (Proxmox VE)" busy={busy} size="lg"
      description="Before a failover, the standby stops the old primary's virtual machine through the Proxmox API, so it can never come back as a second primary."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button onClick={runTest} loading={busy} disabled={!url || !tokenId}>Save and test</Button><Button variant="primary" onClick={save} loading={busy}>Save</Button></>}>
      <div className="stack stack--sm">
        <Switch label="Fence through Proxmox before a failover" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <TextField label="Proxmox API" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://pve.example.org:8006" error={errors.fields["url"]} />
        <div className="grid grid--2">
          <TextField label="API token id" value={tokenId} onChange={(e) => setTokenId(e.target.value)} placeholder="veyra@pve!fencing" help="Needs VM.PowerMgmt on both VMs." error={errors.fields["token_id"]} />
          <TextField label="API token secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={current.data?.has_secret ? "(kept)" : ""} autoComplete="new-password" help="Stored encrypted with the installation key." />
        </div>
        <TextField label="Proxmox node" value={pveNode} onChange={(e) => setPveNode(e.target.value)} placeholder="pve1" help="The Proxmox host that runs both VMs (per-VM hosts are not supported)." />
        <div className="grid grid--2">
          {nodes.map((n) => (
            <TextField key={n} label={`VM id of ${n}`} type="number" value={vms[n] ?? ""} onChange={(e) => setVms({ ...vms, [n]: e.target.value })} placeholder="101" />
          ))}
        </div>
        <Switch label="Verify the Proxmox certificate" checked={verify} onChange={(e) => setVerify(e.target.checked)} description="Off only for a self-signed Proxmox certificate you cannot paste below." />
        <TextArea label="Proxmox CA certificate (PEM, optional)" value={caPem} onChange={(e) => setCaPem(e.target.value)} rows={3} spellCheck={false} />
        {test ? <Callout tone={test.startsWith("Failed") ? "danger" : "ok"}>{test}</Callout> : null}
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- sync options

export function SyncField({ status, onChanged }: { status: HaStatus; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const recordings = status.sync?.recordings ?? true;
  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      await api.put("/ha/sync", { recordings: on });
      onChanged();
    } catch (err) {
      toast.error("Could not change the file sync", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Switch label="Include call recordings in the file sync" checked={recordings} disabled={busy} onChange={(e) => toggle(e.target.checked)}
      description="Recordings are the largest files; without them a failover loses access to recordings made on the old primary until it is back." />
  );
}

export const REPLICATION_OPTIONS = [
  { value: "async", label: "Asynchronous (recommended)" },
  { value: "sync", label: "Synchronous" },
];

export function ReplicationModeField({ status, onChanged }: { status: HaStatus; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const value = status.service.synchronous ? "sync" : "async";
  const change = async (v: string) => {
    setBusy(true);
    try {
      const { name, address, prefix, interface: iface } = status.service;
      await api.put("/ha/service", { name, address, prefix, interface: iface, synchronous: v === "sync" });
      toast.success(v === "sync" ? "Synchronous replication on" : "Asynchronous replication");
      onChanged();
    } catch (err) {
      toast.error("Could not change the replication mode", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <SelectField label="Replication" value={value} disabled={busy} onChange={(e) => change(e.target.value)} options={REPLICATION_OPTIONS}
      help={value === "sync" ? "Every write waits for the standby. While the standby is down, writes block: turning this off is the recovery." : "The primary never waits for the standby; a failover may lose the last moments of writes."} />
  );
}
