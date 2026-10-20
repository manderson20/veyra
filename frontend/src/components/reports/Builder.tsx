// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { clock } from "@/components/calls/format";
import { PickList } from "@/components/calls/PickList";
import { LineChart, StackedBars, type StackSeries } from "@/components/reports/Charts";
import { Button, Callout, Card, Checkbox, DataTable, Dialog, SelectField, Switch, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type {
  ReportDefinition,
  ReportGroup,
  ReportMeasure,
  ReportOptions,
  ReportResult,
  ReportSchedule,
  SavedReport,
} from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

export const EMPTY_DEFINITION: ReportDefinition = {
  organization_id: null,
  group_by: ["day"],
  measures: ["calls", "answered", "missed"],
  filters: {
    directions: [], outcomes: [], extension_ids: [], dids: [], trunk_ids: [], queues: [], ring_groups: [],
    caller_contains: null, min_talk_seconds: null, business_hours: "any", time_condition_id: null,
  },
  period: { kind: "last_7_days", from_date: null, to_date: null },
  show_as: "bars",
  sort_by: null,
  sort_desc: true,
  limit: 100,
  sl_seconds: 20,
};

const GROUPS: { value: ReportGroup; label: string }[] = [
  { value: "day", label: "Day" }, { value: "week", label: "Week" }, { value: "month", label: "Month" },
  { value: "hour", label: "Hour of day" }, { value: "weekday", label: "Weekday" },
  { value: "direction", label: "Direction" }, { value: "outcome", label: "Outcome" },
  { value: "answered_by", label: "Answered by" }, { value: "called_extension", label: "Called extension" },
  { value: "calling_extension", label: "Calling extension" }, { value: "did", label: "Number dialled (DID)" },
  { value: "trunk", label: "Trunk" }, { value: "queue", label: "Queue" }, { value: "ring_group", label: "Ring group" },
  { value: "caller", label: "Caller number" },
];
const MEASURES: { value: ReportMeasure; label: string }[] = [
  { value: "calls", label: "Calls" }, { value: "answered", label: "Answered" }, { value: "missed", label: "Missed" },
  { value: "voicemail", label: "Voicemail" }, { value: "answer_rate", label: "Answer rate" },
  { value: "avg_ring", label: "Average ring" }, { value: "total_ring", label: "Total ring" },
  { value: "avg_talk", label: "Average talk" }, { value: "total_talk", label: "Total talk" },
  { value: "within_sl", label: "Answered within service level" },
];
const PERIODS = [
  { value: "today", label: "Today" }, { value: "yesterday", label: "Yesterday" },
  { value: "last_7_days", label: "Last 7 days" }, { value: "last_30_days", label: "Last 30 days" },
  { value: "this_week", label: "This week" }, { value: "last_week", label: "Last week" },
  { value: "this_month", label: "This month" }, { value: "last_month", label: "Last month" },
  { value: "this_year", label: "This year" }, { value: "custom", label: "Custom dates" },
];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const SERIES_COLORS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)"];

export function formatMeasure(value: unknown, unit?: string): string {
  const n = Number(value ?? 0);
  if (unit === "seconds") return clock(n);
  if (unit === "percent") return `${n}%`;
  return String(n);
}

function activeFilters(d: ReportDefinition): number {
  const f = d.filters;
  return [f.directions.length, f.outcomes.length, f.extension_ids.length, f.dids.length, f.trunk_ids.length, f.queues.length,
    f.ring_groups.length, f.caller_contains ? 1 : 0, f.min_talk_seconds ? 1 : 0, f.business_hours !== "any" ? 1 : 0].filter(Boolean).length;
}

/** Rows → chart data: x is the first grouping; with two groupings the
    three largest values of the second become series and the rest "Other". */
export function chartData(result: ReportResult, measure: string): { data: Record<string, string | number>[]; series: StackSeries[] } {
  const groups = result.columns.filter((c) => c.kind === "group");
  if (groups.length === 1) {
    return {
      data: result.rows.map((r) => ({ x: r.group[0]!.label, v: Number(r[measure] ?? 0) })),
      series: [{ key: "v", label: result.columns.find((c) => c.key === measure)?.label ?? measure, color: SERIES_COLORS[0]! }],
    };
  }
  const totals = new Map<string, number>();
  for (const r of result.rows) totals.set(r.group[1]!.label, (totals.get(r.group[1]!.label) ?? 0) + Number(r[measure] ?? 0));
  const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k]) => k);
  const xs: string[] = [];
  const byX = new Map<string, Record<string, string | number>>();
  for (const r of result.rows) {
    const x = r.group[0]!.label;
    if (!byX.has(x)) { byX.set(x, { x }); xs.push(x); }
    const key = top.includes(r.group[1]!.label) ? `s${top.indexOf(r.group[1]!.label)}` : "other";
    const row = byX.get(x)!;
    row[key] = Number(row[key] ?? 0) + Number(r[measure] ?? 0);
  }
  const series: StackSeries[] = top.map((label, i) => ({ key: `s${i}`, label, color: SERIES_COLORS[i]! }));
  if (totals.size > 3) series.push({ key: "other", label: "Other", color: "var(--text-muted)" });
  return { data: xs.map((x) => byX.get(x)!), series };
}

function SaveDialog({ open, onClose, definition, saved, onSaved }: {
  open: boolean;
  onClose: () => void;
  definition: ReportDefinition;
  saved: SavedReport | null;
  onSaved: (r: SavedReport) => void;
}) {
  const toast = useToast();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const { session } = useSession();
  const [asNew, setAsNew] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [shared, setShared] = useState(true);
  const [scheduled, setScheduled] = useState(false);
  const [sched, setSched] = useState<ReportSchedule>({ frequency: "weekly", hour: 7, weekday: 0, day: 1, recipients: [] });
  const [recipients, setRecipients] = useState("");
  const [busy, setBusy] = useState(false);
  useOnChange(open, () => {
    if (!open) return;
    setAsNew(!saved);
    setName(saved?.name ?? "");
    setDescription(saved?.description ?? "");
    setShared(saved?.shared ?? true);
    setScheduled(!!saved?.schedule);
    setSched(saved?.schedule ?? { frequency: "weekly", hour: 7, weekday: 0, day: 1, recipients: [] });
    setRecipients((saved?.schedule?.recipients ?? (session?.user.email ? [session.user.email] : [])).join("\n"));
    errors.clear();
  });
  const orgId = definition.organization_id ?? saved?.organization_id ?? session?.user.home_organization_id ?? organizations[0]?.id ?? "";
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    const schedule = scheduled ? { ...sched, recipients: recipients.split(/[\s,;]+/).filter(Boolean) } : null;
    try {
      const body = { name: name.trim(), description: description.trim() || null, shared, schedule, definition: { ...definition, organization_id: null } };
      const r = saved && !asNew
        ? await api.patch<SavedReport>(`/saved-reports/${saved.id}`, body)
        : await api.post<SavedReport>("/saved-reports", { ...body, organization_id: orgId });
      toast.success("Report saved", r.next_run_at ? `Next email ${new Date(r.next_run_at).toLocaleString()}.` : undefined);
      onClose();
      onSaved(r);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} busy={busy} title={saved && !asNew ? `Save "${saved.name}"` : "Save report"}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="save-report-form" loading={busy} disabled={!name.trim() || !orgId}>Save</Button></>}>
      <form id="save-report-form" className="stack stack--sm" onSubmit={submit}>
        {saved ? <Checkbox label="Save as a new report" checked={asNew} onChange={(e) => setAsNew(e.target.checked)} /> : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Missed calls by office" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <Switch label="Shared with the organization" description="Everyone who may see reports can open it; only report editors change it." checked={shared} onChange={(e) => setShared(e.target.checked)} />
        <Switch label="Email it on a schedule" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
        {scheduled ? (
          <div className="stack stack--sm">
            <div className="grid grid--2">
              <SelectField label="How often" value={sched.frequency}
                options={[{ value: "daily", label: "Every day" }, { value: "weekly", label: "Every week" }, { value: "monthly", label: "Every month" }]}
                onChange={(e) => setSched({ ...sched, frequency: e.target.value as ReportSchedule["frequency"] })} />
              <SelectField label="At" value={String(sched.hour)} options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, "0")}:00` }))}
                onChange={(e) => setSched({ ...sched, hour: Number(e.target.value) })} />
              {sched.frequency === "weekly" ? (
                <SelectField label="On" value={String(sched.weekday)} options={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))}
                  onChange={(e) => setSched({ ...sched, weekday: Number(e.target.value) })} />
              ) : null}
              {sched.frequency === "monthly" ? (
                <SelectField label="On day" value={String(sched.day)} options={Array.from({ length: 28 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))}
                  onChange={(e) => setSched({ ...sched, day: Number(e.target.value) })} />
              ) : null}
            </div>
            <TextArea label="Email to" rows={3} value={recipients} error={errors.fields["schedule.recipients"] ?? errors.fields.schedule}
              help="One address per line. The CSV holds call data: send it only to people allowed to see it. Times are the organization's time zone."
              onChange={(e) => setRecipients(e.target.value)} />
          </div>
        ) : null}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}

export function ReportBuilder({ definition, setDefinition, saved, onSaved }: {
  definition: ReportDefinition;
  setDefinition: (d: ReportDefinition) => void;
  saved: SavedReport | null;
  onSaved: (r: SavedReport) => void;
}) {
  const toast = useToast();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions(true);
  const d = definition;
  const set = <K extends keyof ReportDefinition>(k: K, v: ReportDefinition[K]) => setDefinition({ ...d, [k]: v });
  const setFilter = <K extends keyof ReportDefinition["filters"]>(k: K, v: ReportDefinition["filters"][K]) => setDefinition({ ...d, filters: { ...d.filters, [k]: v } });
  const options = useApiData<ReportOptions>("/reports/options", { organization_id: d.organization_id ?? undefined });
  const [result, setResult] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const o = options.data;

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setResult(await api.post<ReportResult>("/reports/run", d));
    } catch (err) {
      setError(errorMessage(err));
      setResult(null);
    } finally {
      setRunning(false);
    }
  };
  const exportCsv = async () => {
    try {
      const text = await api.request<string>("/reports/run.csv", { method: "POST", body: d, raw: true });
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(saved?.name ?? "report").toLowerCase().replace(/[^a-z0-9]+/g, "-")}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error("Not exported", errorMessage(err));
    }
  };

  const groupCols = result?.columns.filter((c) => c.kind === "group") ?? [];
  const measureCols = result?.columns.filter((c) => c.kind === "measure") ?? [];
  type Row = ReportResult["rows"][number];
  const columns: Column<Row>[] = [
    ...groupCols.map((c, i) => ({ key: c.key, header: c.label, render: (r: Row) => r.group[i]?.label ?? "" })),
    ...measureCols.map((c) => ({ key: c.key, header: c.label, render: (r: Row) => <span className="mono">{formatMeasure(r[c.key], c.unit)}</span> })),
  ];
  const firstMeasure = measureCols[0]?.key;
  const chart = result && firstMeasure && groupCols.length > 0 && d.show_as !== "table" && result.rows.length > 0 ? chartData(result, firstMeasure) : null;
  const filtersOn = activeFilters(d);

  return (
    <div className="stack">
      <Card title={saved ? saved.name : "Build a report"} subtitle={saved?.description ?? "Choose how to group the calls, what to count, and which calls to include."}>
        <div className="stack">
          <div className="grid grid--4">
            {organizations.length > 1 ? (
              <SelectField label="Organization" value={d.organization_id ?? ""} placeholder="All organizations"
                options={organizations.map((x) => ({ value: x.id, label: x.name }))} onChange={(e) => set("organization_id", e.target.value || null)} />
            ) : null}
            <SelectField label="Period" value={d.period.kind} options={PERIODS}
              onChange={(e) => set("period", { ...d.period, kind: e.target.value as ReportDefinition["period"]["kind"] })} />
            {d.period.kind === "custom" ? (
              <>
                <TextField label="From" type="date" value={d.period.from_date ?? ""} onChange={(e) => set("period", { ...d.period, from_date: e.target.value || null })} />
                <TextField label="To" type="date" value={d.period.to_date ?? ""} onChange={(e) => set("period", { ...d.period, to_date: e.target.value || null })} />
              </>
            ) : null}
            <SelectField label="Group by" value={d.group_by[0] ?? ""} placeholder="No grouping (totals only)" options={GROUPS}
              onChange={(e) => set("group_by", e.target.value ? [e.target.value as ReportGroup, ...d.group_by.slice(1).filter((g) => g !== e.target.value)] : [])} />
            {d.group_by.length ? (
              <SelectField label="Then by" value={d.group_by[1] ?? ""} placeholder="Nothing" options={GROUPS.filter((g) => g.value !== d.group_by[0])}
                onChange={(e) => set("group_by", e.target.value ? [d.group_by[0]!, e.target.value as ReportGroup] : [d.group_by[0]!])} />
            ) : null}
            <SelectField label="Show as" value={d.show_as}
              options={[{ value: "table", label: "Table" }, { value: "bars", label: "Bars and table" }, { value: "line", label: "Line and table" }]}
              onChange={(e) => set("show_as", e.target.value as ReportDefinition["show_as"])} />
          </div>
          <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field__label">Measures</legend>
            <div className="row" style={{ flexWrap: "wrap", gap: "4px 16px" }}>
              {MEASURES.map((m) => (
                <Checkbox key={m.value} label={m.label} checked={d.measures.includes(m.value)}
                  onChange={(e) => set("measures", e.target.checked ? [...d.measures, m.value] : d.measures.filter((x) => x !== m.value))} />
              ))}
            </div>
          </fieldset>
          <details>
            <summary>Filters{filtersOn ? ` (${filtersOn} active)` : ""}</summary>
            <div className="stack stack--sm" style={{ marginTop: 12 }}>
              <div className="grid grid--2">
                <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
                  <legend className="field__label">Directions</legend>
                  {(["inbound", "outbound", "internal"] as const).map((v) => (
                    <Checkbox key={v} label={v[0]!.toUpperCase() + v.slice(1)} checked={d.filters.directions.includes(v)}
                      onChange={(e) => setFilter("directions", e.target.checked ? [...d.filters.directions, v] : d.filters.directions.filter((x) => x !== v))} />
                  ))}
                </fieldset>
                <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
                  <legend className="field__label">Outcomes</legend>
                  {(["answered", "missed", "voicemail", "busy", "abandoned", "failed", "blocked", "denied"] as const).map((v) => (
                    <Checkbox key={v} label={v[0]!.toUpperCase() + v.slice(1)} checked={d.filters.outcomes.includes(v)}
                      onChange={(e) => setFilter("outcomes", e.target.checked ? [...d.filters.outcomes, v] : d.filters.outcomes.filter((x) => x !== v))} />
                  ))}
                </fieldset>
                <PickList label="Extensions (either side)" options={o?.extensions ?? []} value={d.filters.extension_ids} onChange={(v) => setFilter("extension_ids", v)} />
                <PickList label="Numbers dialled (DIDs)" options={(o?.dids ?? []).map((x) => ({ id: x, label: x }))} value={d.filters.dids} onChange={(v) => setFilter("dids", v)} />
                <PickList label="Queues" options={o?.queues ?? []} value={d.filters.queues} onChange={(v) => setFilter("queues", v)} />
                <PickList label="Ring groups" options={o?.ring_groups ?? []} value={d.filters.ring_groups} onChange={(v) => setFilter("ring_groups", v)} />
                <PickList label="Trunks" options={o?.trunks ?? []} value={d.filters.trunk_ids} onChange={(v) => setFilter("trunk_ids", v)} />
                <div className="stack stack--sm">
                  <TextField label="Caller number contains" value={d.filters.caller_contains ?? ""} onChange={(e) => setFilter("caller_contains", e.target.value || null)} />
                  <TextField label="At least this much talk (seconds)" type="number" min={0} value={d.filters.min_talk_seconds ?? ""}
                    onChange={(e) => setFilter("min_talk_seconds", e.target.value ? Number(e.target.value) : null)} />
                </div>
              </div>
              <div className="grid grid--2">
                <SelectField label="Business hours" value={d.filters.business_hours}
                  options={[{ value: "any", label: "Any time" }, { value: "inside", label: "Only inside business hours" }, { value: "outside", label: "Only outside business hours" }]}
                  onChange={(e) => setFilter("business_hours", e.target.value as ReportDefinition["filters"]["business_hours"])} />
                {d.filters.business_hours !== "any" ? (
                  <SelectField label="Business hours are" value={d.filters.time_condition_id ?? ""} placeholder="Choose a time condition"
                    help="The hours and holidays of a time condition (Telephony → Time Conditions)."
                    options={(o?.time_conditions ?? []).map((t) => ({ value: t.id, label: t.label }))} onChange={(e) => setFilter("time_condition_id", e.target.value || null)} />
                ) : null}
              </div>
            </div>
          </details>
          <div className="grid grid--4">
            <SelectField label="Sort by" value={d.sort_by ?? ""} placeholder="Automatic"
              options={[{ value: "group", label: "The grouping" }, ...MEASURES.filter((m) => d.measures.includes(m.value))]}
              onChange={(e) => set("sort_by", e.target.value || null)} />
            <SelectField label="Order" value={d.sort_desc ? "desc" : "asc"} options={[{ value: "desc", label: "Highest first" }, { value: "asc", label: "Lowest first" }]}
              onChange={(e) => set("sort_desc", e.target.value === "desc")} />
            <TextField label="Show at most (rows)" type="number" min={1} max={1000} value={d.limit} onChange={(e) => set("limit", Number(e.target.value) || 100)} />
            {d.measures.includes("within_sl") ? (
              <TextField label="Service level (seconds)" type="number" min={1} max={600} value={d.sl_seconds} onChange={(e) => set("sl_seconds", Number(e.target.value) || 20)} />
            ) : null}
          </div>
          <div className="row">
            <Button variant="primary" icon="play" loading={running} disabled={d.measures.length === 0} onClick={run}>Run</Button>
            <Button icon="download" onClick={exportCsv} disabled={d.measures.length === 0}>Export CSV</Button>
            {can("reports.write") ? <Button icon="plus" onClick={() => setSaving(true)}>{saved ? "Save…" : "Save report…"}</Button> : null}
          </div>
          {error ? <Callout tone="danger">{error}</Callout> : null}
        </div>
      </Card>
      {result ? (
        <Card title="Result" subtitle={`${result.period.label} (${result.period.timezone})${result.truncated ? ` · first ${d.limit} rows` : ""}`} flush>
          {chart ? (
            <div style={{ padding: 16 }}>
              {d.show_as === "line"
                ? <LineChart data={chart.data} series={chart.series} xKey="x" xLabel={(x) => x} caption={`${measureCols[0]!.label} by ${groupCols[0]!.label}`} />
                : <StackedBars data={chart.data} series={chart.series} xKey="x" xLabel={(x) => x} caption={`${measureCols[0]!.label} by ${groupCols[0]!.label}`} xHeader={groupCols[0]!.label} />}
              <p className="subtle" style={{ margin: "4px 0 0" }}>The chart shows {measureCols[0]!.label.toLowerCase()}; the table shows every measure.</p>
            </div>
          ) : null}
          {groupCols.length ? (
            <DataTable columns={columns} rows={result.rows} rowKey={(r) => r.group.map((g) => g.key ?? "").join("|")} caption="Report"
              empty={<p className="subtle" style={{ padding: 16 }}>No calls match.</p>} />
          ) : null}
          <div className="row" style={{ padding: "12px 16px", flexWrap: "wrap", gap: "4px 24px", borderTop: "1px solid var(--border)" }}>
            <strong>Total</strong>
            {measureCols.map((c) => <span key={c.key}>{c.label}: <span className="mono">{formatMeasure(result.totals[c.key], c.unit)}</span></span>)}
          </div>
        </Card>
      ) : null}
      <SaveDialog open={saving} onClose={() => setSaving(false)} definition={d} saved={saved} onSaved={onSaved} />
    </div>
  );
}
