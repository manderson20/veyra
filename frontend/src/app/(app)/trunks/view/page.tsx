// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_TRUNK, TrunkAllFields, TrunkModeBadge, TrunkStatusBadge, trunkBody, trunkDirty, trunkDraft, type TrunkDraft } from "@/components/routing/TrunkFields";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { Trunk } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function TrunkView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const trunk = useApiData<Trunk>(id ? `/trunks/${encodeURIComponent(id)}` : null);
  const editable = can("trunks.write");
  const reload = trunk.reload;
  useEffect(() => {
    // live reachability
    const t = window.setInterval(reload, 15_000);
    return () => window.clearInterval(t);
  }, [reload]);
  const [draft, setDraft] = useState<TrunkDraft>(EMPTY_TRUNK);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  // Copy the record into the form when it first arrives (and after a save below),
  // not on the periodic status refresh, which would discard edits in progress.
  const loaded = trunk.data;
  useOnChange(loaded?.id, () => {
    if (loaded) setDraft(trunkDraft(loaded));
  });

  if (!id) return <ErrorState title="No trunk selected" error={{ message: "Open a trunk from the list." }} />;
  if (trunk.error) return <ErrorState title="Could not load trunk" error={trunk.error} onRetry={trunk.reload} />;
  if (!trunk.data) return <LoadingState />;
  const t = trunk.data;
  const dirty = trunkDirty(draft, t);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const saved = await api.patch<Trunk>(`/trunks/${t.id}`, trunkBody(draft));
      trunk.setData(saved);
      setDraft(trunkDraft(saved));
      setChanged((n) => n + 1);
      toast.success("Trunk saved", "If the engine configuration changed, Deploy changes appears in the top bar.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/trunks/${t.id}`);
      toast.success(`Trunk ${t.name} deleted`, "Deploy the configuration to remove it from the engine.");
      router.push("/trunks/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/trunks/", label: "SIP trunks" }}
        title={t.name}
        description={
          <span className="row">
            <span className="mono">{t.host}:{t.port} {t.transport.toUpperCase()}</span>
            <TrunkModeBadge mode={t.auth_mode} />
            <TrunkStatusBadge trunk={t} />
            {!t.has_password && t.auth_mode === "registration" ? <Badge tone="warn" icon="alert">No password</Badge> : null}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Settings" subtitle={editable ? undefined : "You can view but not change this trunk."}>
          <form className="stack" onSubmit={save}>
            <TrunkAllFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} disabled={!editable} hasPassword={t.has_password} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(trunkDraft(t))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty}>Save changes</Button></div> : null}
          </form>
        </Card>
        <Card title="Information">
          <dl className="dl">
            <dt>Status</dt><dd><TrunkStatusBadge trunk={t} />{t.status === null ? <span className="subtle" style={{ display: "block", marginTop: 4 }}>The engine does not report trunk status right now.</span> : t.qualify_frequency === 0 ? <span className="subtle" style={{ display: "block", marginTop: 4 }}>Qualify is off, so reachability is not checked.</span> : null}</dd>
            <dt>Engine name</dt><dd className="mono">trunk-{t.slug}</dd>
            <dt>Password</dt><dd>{t.has_password ? "Stored" : <span className="subtle">None</span>}</dd>
            <dt>Match addresses</dt><dd>{t.match_addresses.length ? t.match_addresses.map((a) => <span key={a} className="mono" style={{ display: "block" }}>{a}</span>) : <span className="subtle">{t.auth_mode === "ip" ? `Host (${t.host})` : "—"}</span>}</dd>
            <dt>Codecs</dt><dd>{t.codecs ? <span className="mono">{t.codecs.join(", ")}</span> : <span className="subtle">Installation default</span>}</dd>
            <dt>Created</dt><dd>{formatDateTime(t.created_at)}</dd>
            <dt>Updated</dt><dd>{formatRelative(t.updated_at)}</dd>
            <dt>Trunk ID</dt><dd className="mono">{t.id}</dd>
          </dl>
        </Card>
      </div>
      <ConfirmDialog
        open={deleting}
        title={`Delete trunk ${t.name}?`}
        confirmLabel="Delete trunk"
        tone="danger"
        typeToConfirm={t.name}
        busy={deleteBusy}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => { setDeleting(false); setDeleteError(null); }}
      >
        <p>Trunks used by an outbound or inbound route cannot be deleted; remove them from the routes first. Type <strong>{t.name}</strong> to confirm.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><TrunkView /></Suspense>;
}
