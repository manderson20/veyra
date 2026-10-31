// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type ChangeEvent } from "react";
import { Badge, Button, Callout, Card, DataTable, EmptyState, PageHeader, SelectField, useToast, type Column } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

interface BulkKind { name: string; label: string; key: string; columns: string[]; permission: string }
interface BulkRow { row: number; key: string; action: "create" | "update" | "unchanged" | "error"; message: string | null; notes: string[] }
interface BulkResult { dry_run: boolean; counts: Record<string, number>; rows: BulkRow[] }

const ACTION: Record<BulkRow["action"], { tone: "ok" | "info" | "neutral" | "danger"; label: string }> = {
  create: { tone: "ok", label: "Create" },
  update: { tone: "info", label: "Update" },
  unchanged: { tone: "neutral", label: "No change" },
  error: { tone: "danger", label: "Error" },
};

/** Bulk CSV import and export (issue #41; docs/BULK_IMPORT.md): export or
 * download a template, check a file (dry run), then import it. */
export default function ImportPage() {
  const toast = useToast();
  const { can, session } = useSession();
  const { organizations } = useOrganizationOptions(true);
  const kinds = useApiData<BulkKind[]>("/bulk/kinds");
  const [kindName, setKindName] = useState("extensions");
  const [org, setOrg] = useState("");
  const [text, setText] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<BulkResult | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kind = kinds.data?.find((k) => k.name === kindName);
  const orgId = org || session?.user.home_organization_id || organizations[0]?.id || "";
  const allowed = kind ? can(kind.permission) : false;

  // From FreePBX (issue #42): a database dump becomes the files below.
  const [fpbx, setFpbx] = useState<{ csv: Record<string, string>; counts: Record<string, number>; warnings: string[] } | null>(null);
  const [fpbxBusy, setFpbxBusy] = useState(false);
  const [fpbxError, setFpbxError] = useState<string | null>(null);
  const [dumpFile, setDumpFile] = useState<File | null>(null);
  const [vmFile, setVmFile] = useState<File | null>(null);
  const [agentsFile, setAgentsFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [audioResult, setAudioResult] = useState<{ recordings: number; music_tracks: number; hold_music_sets: number; already_there: number; warnings: string[] } | null>(null);
  const importAudio = async () => {
    if (!audioFile || !orgId) return;
    setAudioBusy(true);
    setAudioError(null);
    setAudioResult(null);
    try {
      const form = new FormData();
      form.append("organization_id", orgId);
      form.append("file", audioFile);
      if (dumpFile) form.append("dump", dumpFile);
      setAudioResult(await api.upload("/bulk/freepbx/audio", form));
    } catch (err) {
      setAudioError(errorMessage(err));
    } finally {
      setAudioBusy(false);
    }
  };
  const convert = async () => {
    if (!dumpFile) return;
    setFpbxBusy(true);
    setFpbxError(null);
    setFpbx(null);
    try {
      const form = new FormData();
      form.append("file", dumpFile);
      if (vmFile) form.append("voicemail", vmFile);
      if (agentsFile) form.append("queue_agents", agentsFile);
      setFpbx(await api.upload("/bulk/freepbx/convert", form));
    } catch (err) {
      setFpbxError(errorMessage(err));
    } finally {
      setFpbxBusy(false);
    }
  };
  const loadConverted = (kindKey: string) => {
    if (!fpbx) return;
    setKindName(kindKey);
    setText(fpbx.csv[kindKey] ?? null);
    setFileName(`From FreePBX: ${kindKey.replace("_", " ")}`);
    setResult(null);
    setError(null);
  };

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    setResult(null);
    setError(null);
    if (!f) { setText(null); setFileName(""); return; }
    setFileName(f.name);
    setText(await f.text());
  };
  const run = async (dryRun: boolean) => {
    if (text === null || !kind) return;
    setBusy(dryRun ? "check" : "import");
    setError(null);
    try {
      const r = await api.post<BulkResult>(`/bulk/${kind.name}/import?organization_id=${encodeURIComponent(orgId)}&dry_run=${dryRun}`, { csv: text });
      setResult(r);
      if (!dryRun) {
        const done = (r.counts.create ?? 0) + (r.counts.update ?? 0);
        if (r.counts.error) toast.error(`${done} row${done === 1 ? "" : "s"} imported, ${r.counts.error} with errors`, "The rows with errors were not changed.");
        else toast.success(`${done} row${done === 1 ? "" : "s"} imported`, "Deploy the changes when you are ready.");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<BulkRow>[] = [
    { key: "row", header: "Line", render: (r) => <span className="mono">{r.row}</span> },
    { key: "key", header: kind?.key ?? "Key", render: (r) => <span className="mono">{r.key || "—"}</span> },
    { key: "action", header: result?.dry_run ? "Would" : "Result", render: (r) => <Badge tone={ACTION[r.action].tone}>{ACTION[r.action].label}</Badge> },
    { key: "message", header: "Details", render: (r) => <span>{r.message ?? r.notes.join("; ")}{r.message && r.notes.length ? ` (${r.notes.join("; ")})` : ""}</span> },
  ];
  const q = `organization_id=${encodeURIComponent(orgId)}`;
  const errors = result?.counts.error ?? 0;
  const changes = (result?.counts.create ?? 0) + (result?.counts.update ?? 0);

  return (
    <div className="stack">
      <PageHeader title="Import and export"
        description="Many extensions, users, inbound routes, shared inboxes, ring groups, queues, phone menus, time conditions or phones at once, as a CSV file. Export what exists (or a blank template), edit it in a spreadsheet, check it, then import it. Rows are matched on their first column: a match is updated, otherwise it is created. An empty cell keeps the value; a dash (-) clears it." />
      <Card title="1. Choose what">
        <div className="grid grid--2">
          <SelectField label="Kind" value={kindName} options={(kinds.data ?? []).map((k) => ({ value: k.name, label: k.label }))}
            onChange={(e) => { setKindName(e.target.value); setResult(null); }} />
          {organizations.length > 1 ? (
            <SelectField label="Organization" value={orgId} options={organizations.map((o) => ({ value: o.id, label: o.name }))}
              onChange={(e) => { setOrg(e.target.value); setResult(null); }} />
          ) : null}
        </div>
        {kind ? (
          <div className="stack stack--sm" style={{ marginTop: 12 }}>
            <p className="subtle" style={{ margin: 0 }}>Columns: <span className="mono">{kind.columns.join(", ")}</span></p>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/bulk/${kind.name}/export.csv?${q}`} download>Export {kind.label.toLowerCase()}</a>
              <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/bulk/${kind.name}/export.csv?${q}&template=true`} download>Blank template</a>
            </div>
          </div>
        ) : null}
      </Card>
      <Card title="From FreePBX" subtitle="Moving from FreePBX? Its extensions, ring groups, queues, IVR menus, time conditions and inbound routes become the files to check and import here.">
        <div className="stack stack--sm">
          <p className="subtle" style={{ margin: 0 }}>On the FreePBX server run <span className="mono">mysqldump asterisk &gt; asterisk.sql</span> (or <span className="mono">| gzip</span>), then choose the file. Nothing is saved until you import each file below, in this order: extensions, ring groups, queues, IVR menus, time conditions, inbound routes. Upload the IVR recordings to the audio library first, under the names they had in FreePBX. SIP passwords are not carried over. If FreePBX used 3-digit extensions, widen the numbering plan (Settings) first.</p>
          <div className="grid grid--2">
            <label className="field">
              <span className="field__label">FreePBX database dump</span>
              <input type="file" accept=".sql,.gz,.tgz,.tar,application/sql" onChange={(e) => setDumpFile(e.target.files?.[0] ?? null)} disabled={fpbxBusy} />
            </label>
            <label className="field">
              <span className="field__label">voicemail.conf (optional: keeps PINs and emails)</span>
              <input type="file" accept=".conf,text/plain" onChange={(e) => setVmFile(e.target.files?.[0] ?? null)} disabled={fpbxBusy} />
            </label>
            <label className="field">
              <span className="field__label">Queue agents (optional: output of <span className="mono">asterisk -rx &quot;database show QPENALTY&quot;</span>)</span>
              <input type="file" accept=".txt,text/plain" onChange={(e) => setAgentsFile(e.target.files?.[0] ?? null)} disabled={fpbxBusy} />
            </label>
          </div>
          <div><Button size="sm" variant="primary" onClick={() => void convert()} loading={fpbxBusy} disabled={!dumpFile}>Read the FreePBX files</Button></div>
          {fpbxBusy ? <p className="subtle" style={{ margin: 0 }}>Reading the dump…</p> : null}
          <div className="stack stack--sm">
            <p className="subtle" style={{ margin: 0 }}><strong>Recordings and hold music.</strong> Do this before checking the IVR menus. On the FreePBX server run <span className="mono">tar czf audio.tar.gz -C /var/lib/asterisk sounds/en/custom moh</span>. Choose the database dump above too, so recordings keep their FreePBX names. Nothing already in the library is changed, so you can run this again.</p>
            <label className="field">
              <span className="field__label">Audio archive</span>
              <input type="file" accept=".tar,.gz,.tgz" onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)} disabled={audioBusy} />
            </label>
            <div><Button size="sm" onClick={() => void importAudio()} loading={audioBusy} disabled={!audioFile || !orgId}>Import the audio</Button></div>
            {audioBusy ? <p className="subtle" style={{ margin: 0 }}>Uploading and converting; a large archive takes several minutes.</p> : null}
            {audioError ? <Callout tone="danger">{audioError}</Callout> : null}
            {audioResult ? (
              <Callout tone={audioResult.warnings.length ? "warn" : "ok"} title={`Imported ${audioResult.recordings} recordings, ${audioResult.music_tracks} music tracks and ${audioResult.hold_music_sets} hold music sets; ${audioResult.already_there} were already there`}>
                {audioResult.warnings.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{audioResult.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
              </Callout>
            ) : null}
          </div>
          {fpbxError ? <Callout tone="danger">{fpbxError}</Callout> : null}
          {fpbx ? (
            <>
              <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                {["extensions", "ring_groups", "queues", "ivr_menus", "time_conditions", "inbound_routes"].filter((k) => fpbx.csv[k]).map((k) => (
                  <Button key={k} size="sm" onClick={() => loadConverted(k)}>Check {fpbx.counts[k]} {k.replace(/_/g, " ")}</Button>
                ))}
              </div>
              {fpbx.warnings.length ? (
                <Callout tone="warn" title={`${fpbx.warnings.length} thing${fpbx.warnings.length === 1 ? "" : "s"} to do by hand`}>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>{fpbx.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                </Callout>
              ) : null}
            </>
          ) : null}
        </div>
      </Card>
      <Card title="2. Check and import" footer={allowed ? (
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <Button onClick={() => run(true)} loading={busy === "check"} disabled={text === null || !!busy}>Check the file</Button>
          <Button variant="primary" onClick={() => run(false)} loading={busy === "import"} disabled={!result?.dry_run || changes === 0 || !!busy}>
            Import {changes ? `${changes} row${changes === 1 ? "" : "s"}` : ""}
          </Button>
        </div>
      ) : undefined}>
        <div className="stack stack--sm">
          {!allowed && kind ? <Callout tone="warn">You cannot change {kind.label.toLowerCase()}; you can still export them.</Callout> : null}
          <label className="field">
            <span className="field__label">CSV file</span>
            <input type="file" accept=".csv,text/csv" onChange={pick} disabled={!allowed} />
          </label>
          {fileName ? <p className="subtle" style={{ margin: 0 }}>{fileName}</p> : null}
          <p className="subtle" style={{ margin: 0 }}>Checking runs every row through the same checks as the web pages and changes nothing. Importing applies the rows without errors; rows with errors are left out and listed.</p>
          {error ? <Callout tone="danger">{error}</Callout> : null}
          {result ? (
            <Callout tone={errors ? "warn" : "ok"} title={result.dry_run ? "Check finished" : "Import finished"}>
              {result.counts.create ?? 0} to create, {result.counts.update ?? 0} to update, {result.counts.unchanged ?? 0} unchanged, {errors} with errors.
              {result.dry_run && errors ? " Fix them in the file and check again, or import the others." : ""}
            </Callout>
          ) : null}
        </div>
      </Card>
      {result ? (
        <Card title="Rows" flush>
          <DataTable columns={columns} rows={result.rows} rowKey={(r) => String(r.row)} caption="Rows of the file"
            empty={<EmptyState compact icon="file" title="No rows" />} />
        </Card>
      ) : null}
    </div>
  );
}
