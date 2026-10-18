// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { DestinationPicker, useDestinationOptions } from "@/components/routing/DestinationPicker";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, DataTable, Dialog, EmptyState, PageHeader, Pagination, SearchInput, SelectField, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, API_BASE, errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { destinationBody, destinationComplete, destinationDraft, HANGUP, type DestinationDraft } from "@/lib/routing";
import type { CallerBlock, CallerBlockImportResult, CallerBlockPolicy, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

const LIMIT = 25;

export default function CallerBlocksPage() {
  const { can, session } = useSession();
  const toast = useToast();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [addOpen, setAddOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [removing, setRemoving] = useState<CallerBlock | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const editable = can("routing.write");
  const effectiveOrg = org || session?.user.home_organization_id || (organizations.length === 1 ? organizations[0]!.id : "");

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<CallerBlock>>("/caller-blocks", { q: debounced, organization_id: effectiveOrg || undefined, limit: LIMIT, offset });
  const policy = useApiData<CallerBlockPolicy>(effectiveOrg ? "/caller-blocks/policy" : null, { organization_id: effectiveOrg });
  const manyOrgs = organizations.length > 1;

  const remove = async () => {
    if (!removing) return;
    setRemoveBusy(true);
    try {
      await api.del(`/caller-blocks/${removing.id}`);
      toast.success(`${removing.number} unblocked`, "Takes effect at once.");
      setRemoving(null);
      list.reload();
      policy.reload();
    } catch (err) {
      toast.error("Could not unblock the number", errorMessage(err));
    } finally {
      setRemoveBusy(false);
    }
  };

  const columns: Column<CallerBlock>[] = [
    { key: "number", header: "Number", render: (b) => <span className="mono">{b.number}</span> },
    { key: "desc", header: "Note", render: (b) => b.description ? <span>{b.description}</span> : <span className="subtle">—</span> },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (b: CallerBlock) => <span>{b.organization_name}</span> }] : []),
    { key: "hits", header: "Blocked calls", render: (b) => b.hits ? <span>{b.hits}{b.last_hit_at ? <span className="subtle"> · last {formatRelative(b.last_hit_at)}</span> : null}</span> : <span className="subtle">none yet</span> },
    { key: "source", header: "Added", render: (b) => <Badge tone="outline">{b.source === "phone" ? "From a phone" : b.source === "csv" ? "Import" : "Interface"}</Badge> },
    ...(editable ? [{ key: "actions", header: "", render: (b: CallerBlock) => <Button size="sm" variant="ghost" icon="trash" onClick={(e) => { e.stopPropagation(); setRemoving(b); }} aria-label={`Unblock ${b.number}`}>Unblock</Button> }] : []),
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Blocked callers"
        description="Numbers the organization refuses on every inbound route: the call hears “no service” (or goes to the destination below). Add numbers here, import a list, or from any phone with *30 (enter a number) and *32 (block the last outside caller); *31 unblocks. Changes to numbers take effect at once; the anonymous-caller rule and the destination need a deployment."
        actions={editable ? <span className="row"><Button icon="upload" onClick={() => setImportOpen(true)} disabled={!effectiveOrg}>Import</Button><Button icon="download" onClick={() => { if (effectiveOrg) window.location.href = `${API_BASE}/caller-blocks/export?organization_id=${encodeURIComponent(effectiveOrg)}`; }} disabled={!effectiveOrg}>Export CSV</Button><Button variant="primary" icon="plus" onClick={() => setAddOpen(true)} disabled={!effectiveOrg}>Block a number</Button></span> : null}
      />
      <PendingChanges refreshKey={policy.data?.updated_at ?? undefined} />
      {manyOrgs ? (
        <Card>
          <SelectField label="Organization" value={effectiveOrg} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
        </Card>
      ) : null}
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card flush>
          <div className="table-toolbar">
            <SearchInput value={q} onChange={setQ} placeholder="Search by number or note" label="Search blocked callers" />
          </div>
          <DataTable
            columns={columns}
            rows={list.data?.items}
            rowKey={(b) => b.id}
            loading={list.loading}
            error={list.error}
            onRetry={list.reload}
            caption="Blocked callers"
            empty={<EmptyState icon="shield" title={debounced ? "No matching numbers" : "No blocked callers"}>{!debounced && editable ? "Block a number here or from a phone with *30; blocked calls are counted per number." : null}</EmptyState>}
            pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
          />
        </Card>
        {effectiveOrg ? <PolicyCard organizationId={effectiveOrg} policy={policy.data ?? null} reload={policy.reload} editable={editable} /> : null}
      </div>
      <AddDialog open={addOpen} organizationId={effectiveOrg} onClose={() => setAddOpen(false)} onAdded={() => { list.reload(); policy.reload(); }} />
      <ImportDialog open={importOpen} organizationId={effectiveOrg} onClose={() => setImportOpen(false)} onDone={() => { list.reload(); policy.reload(); }} />
      <ConfirmDialog open={removing !== null} title={`Unblock ${removing?.number ?? ""}?`} confirmLabel="Unblock" tone="danger" busy={removeBusy} onConfirm={remove} onCancel={() => setRemoving(null)}>
        <p>Calls from this number reach the organization again at once.</p>
      </ConfirmDialog>
    </div>
  );
}

function PolicyCard({ organizationId, policy, reload, editable }: { organizationId: string; policy: CallerBlockPolicy | null; reload: () => void; editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const options = useDestinationOptions(organizationId);
  const [anon, setAnon] = useState(false);
  const [dest, setDest] = useState<DestinationDraft>(HANGUP);
  const [busy, setBusy] = useState(false);
  useOnChange(policy, (p) => {
    if (p) {
      setAnon(p.block_anonymous);
      setDest(destinationDraft(p.destination, HANGUP));
    }
  });
  if (!policy) return <Card title="Rules"><p className="subtle">Loading…</p></Card>;
  const dirty = anon !== policy.block_anonymous || JSON.stringify(destinationBody(dest)) !== JSON.stringify(destinationBody(destinationDraft(policy.destination, HANGUP)));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      await api.put("/caller-blocks/policy", { organization_id: organizationId, block_anonymous: anon, destination: destinationBody(dest) });
      toast.success("Rules saved", "Deploy changes to apply them to the phone system.");
      reload();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Rules" subtitle="How blocked and withheld callers are handled.">
      <form className="stack stack--sm" onSubmit={save}>
        <dl className="dl">
          <dt>Blocked numbers</dt><dd>{policy.blocked_numbers}</dd>
          <dt>Blocked calls</dt><dd>{policy.total_hits}{policy.anonymous_hits ? ` (${policy.anonymous_hits} withheld)` : ""}</dd>
        </dl>
        <Checkbox label="Block callers who withhold their number" description="Anonymous, restricted or private caller IDs are refused too." checked={anon} disabled={!editable} onChange={(e) => setAnon(e.target.checked)} />
        <DestinationPicker label="Blocked calls go to" idBase="block-dest" draft={dest} onChange={setDest} options={options} allowHangup current={policy.destination} error={errors.fields.destination} disabled={!editable} />
        <p className="field__help" style={{ margin: 0 }}>“Hang up” plays “the number you have dialled is not in service” first.</p>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !destinationComplete(dest)}>Save rules</Button></div> : null}
      </form>
    </Card>
  );
}

function AddDialog({ open, organizationId, onClose, onAdded }: { open: boolean; organizationId: string; onClose: () => void; onAdded: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [number, setNumber] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => { if (open) { setNumber(""); setNote(""); errors.clear(); } });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<CallerBlock>("/caller-blocks", { organization_id: organizationId, number: number.trim(), description: note.trim() || null });
      toast.success(`${created.number} blocked`, "Takes effect at once.");
      onClose();
      onAdded();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Block a number"
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="block-add" loading={busy} disabled={!number.trim()}>Block</Button></>}>
      <form id="block-add" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Number" required autoFocus inputMode="tel" value={number} error={errors.fields.number} placeholder="As the caller ID shows it, e.g. 5735551234" onChange={(e) => setNumber(e.target.value)} />
        <TextField label="Note" value={note} error={errors.fields.description} placeholder="Optional: why it is blocked" onChange={(e) => setNote(e.target.value)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

function ImportDialog({ open, organizationId, onClose, onDone }: { open: boolean; organizationId: string; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CallerBlockImportResult | null>(null);
  useOnChange(open, () => { if (open) { setText(""); setResult(null); errors.clear(); } });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const r = await api.post<CallerBlockImportResult>("/caller-blocks/import", { organization_id: organizationId, text });
      setResult(r);
      toast.success(`${r.added} number${r.added === 1 ? "" : "s"} blocked`, r.updated ? `${r.updated} already blocked; notes updated.` : undefined);
      onDone();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title="Import blocked callers" description="One number per line, optionally followed by a comma and a note. A CSV exported from here or from FreePBX works as is."
      footer={<><Button onClick={onClose} disabled={busy}>{result ? "Close" : "Cancel"}</Button><Button variant="primary" type="submit" form="block-import" loading={busy} disabled={!text.trim()}>Import</Button></>}>
      <form id="block-import" className="stack stack--sm" onSubmit={submit}>
        <TextArea label="Numbers" rows={8} value={text} error={errors.fields.text} placeholder={"5735551234,Robocaller\n8005550199"} onChange={(e) => setText(e.target.value)} />
        {result?.skipped.length ? <Callout tone="warn" title={`${result.skipped.length} line${result.skipped.length === 1 ? "" : "s"} skipped`}>{result.skipped.join(", ")}</Callout> : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
