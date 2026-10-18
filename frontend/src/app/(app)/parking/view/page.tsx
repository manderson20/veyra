// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { EMPTY_PARKING_LOT, ParkingLotFields, parkingLotBody, parkingLotDraft, parkingLotValid, type ParkingLotDraft } from "@/components/callflow/ParkingLotFields";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationLabel } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { ParkingLot } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useSession } from "@/hooks/useSession";

function ParkingLotView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const item = useApiData<ParkingLot>(id ? `/parking-lots/${encodeURIComponent(id)}` : null);
  const editable = can("groups.write");
  const [draft, setDraft] = useState<ParkingLotDraft>(EMPTY_PARKING_LOT);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);

  useOnChange(item.data, (l) => {
    if (l) setDraft(parkingLotDraft(l));
  });

  if (!id) return <ErrorState title="No parking lot selected" error={{ message: "Open a lot from the list." }} />;
  if (item.error) return <ErrorState title="Could not load parking lot" error={item.error} onRetry={item.reload} />;
  if (!item.data) return <LoadingState />;
  const l = item.data;
  const dirty = JSON.stringify(parkingLotBody(draft)) !== JSON.stringify(parkingLotBody(parkingLotDraft(l)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      item.setData(await api.patch<ParkingLot>(`/parking-lots/${l.id}`, parkingLotBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Parking lot saved", "Deploy changes to apply it to the phone system.");
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
      await api.del(`/parking-lots/${l.id}`);
      toast.success(`Parking lot "${l.name}" deleted`, "Deploy the configuration to remove it from the phone system.");
      router.push("/parking/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/parking/", label: "Call parking" }}
        title={l.name}
        description={
          <span className="row">
            <span>{l.organization_name}</span>
            <Badge tone={l.is_enabled ? "ok" : "neutral"}>{l.is_enabled ? "Enabled" : "Disabled"}</Badge>
            {l.problems.length ? <Badge tone="warn" icon="alert">{l.problems.length} problem{l.problems.length === 1 ? "" : "s"}</Badge> : <Badge tone="ok" icon="checkCircle">Ready</Badge>}
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      {l.problems.length ? (
        <Callout tone="warn" title="Check this lot's settings">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{l.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Callout>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Parking lot" subtitle={editable ? undefined : "You can view but not change this lot."}>
          <form className="stack stack--sm" onSubmit={save}>
            <ParkingLotFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} organizationId={l.organization_id} current={l} disabled={!editable} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(parkingLotDraft(l))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !parkingLotValid(draft)}>Save</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="On the phones" subtitle="What users do with this lot.">
            <dl className="dl">
              <dt>Park a call</dt><dd>Transfer it to <span className="mono">{l.park_exten}</span>; the slot number is read back</dd>
              <dt>Pick a call up</dt><dd>Dial the slot (<span className="mono">{l.slot_first}</span> to <span className="mono">{l.slot_last}</span>) from any phone</dd>
              <dt>Line keys</dt><dd>A BLF key with a slot number lights while a call waits there</dd>
              <dt>Timeout</dt><dd>After {l.timeout_seconds} s the parker&apos;s phone rings for {l.return_ring_seconds} s, then <DestinationLabel d={l.timeout} /></dd>
            </dl>
          </Card>
          <Card title="Information">
            <dl className="dl">
              <dt>Context</dt><dd className="mono">{l.context}</dd>
              <dt>Organization</dt><dd>{l.organization_name}</dd>
              <dt>Created</dt><dd>{formatDateTime(l.created_at)}</dd>
              <dt>Updated</dt><dd>{formatRelative(l.updated_at)}</dd>
              <dt>Lot ID</dt><dd className="mono">{l.id}</dd>
            </dl>
          </Card>
        </div>
      </div>
      <ConfirmDialog open={deleting} title={`Delete the parking lot "${l.name}"?`} confirmLabel="Delete lot" tone="danger" busy={deleteBusy} error={deleteError} onConfirm={remove} onCancel={() => { setDeleting(false); setDeleteError(null); }}>
        <p>Its numbers become free again. The lot leaves the phone system at the next deployment.</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><ParkingLotView /></Suspense>;
}
