// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Badge, Button, Callout, Card, ConfirmDialog, DataTable, Dialog, EmptyState, IconButton, PageHeader, SelectField, Switch, TextArea, TextField, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { Page, PagingPage, Prompt } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

interface Trigger { name: string; group: string; description: string; fields: string[] }
interface Condition { field: string; equals?: string; contains?: string }
interface Action { type: "email" | "page"; to?: string[]; subject?: string; page_id?: string; audio_id?: string }
interface Rule {
  id: string; organization_id: string; name: string; enabled: boolean; trigger: string;
  conditions: Condition[]; actions: Action[]; cooldown_seconds: number;
  last_fired_at: string | null; fire_count: number; last_error: string | null; created_by: string;
  hook_url: string | null;
}
interface Run { id: string; event: string; status: string; results: { type: string; ok: boolean; detail: string }[]; created_at: string }

const HOOK = "hook";

/** Automation rules (issue #117; docs/INTEGRATIONS.md §3.8): "when X happens, do Y". */
export default function AutomationPage() {
  const { can } = useSession();
  const triggers = useApiData<Trigger[]>("/automation/triggers");
  const rules = useApiData<Rule[]>("/automation/rules");
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [shownUrl, setShownUrl] = useState<{ name: string; url: string } | null>(null);
  const [runsOf, setRunsOf] = useState<Rule | null>(null);
  const manage = can("webhooks.write");
  const label = (t: string) => t === HOOK ? "Request to the rule's address" : (triggers.data?.find((x) => x.name === t)?.description ?? t);

  const columns: Column<Rule>[] = [
    { key: "name", header: "Rule", render: (r) => <span><span className="table__primary" style={{ display: "block" }}>{r.name}</span><span className="table__secondary">{label(r.trigger)}{r.conditions.length ? ` · ${r.conditions.map((c) => `${c.field} ${c.equals !== undefined ? `= ${c.equals}` : `contains ${c.contains}`}`).join(", ")}` : ""}</span></span> },
    { key: "do", header: "Then", render: (r) => <span>{r.actions.map((a) => a.type === "email" ? `email ${(a.to ?? []).join(", ")}` : "start a page").join("; ")}</span> },
    { key: "state", header: "State", render: (r) => <span className="stack stack--sm"><Badge tone={!r.enabled ? "neutral" : r.last_error ? "warn" : "ok"}>{!r.enabled ? "Off" : r.last_error ? "Last run failed" : "On"}</Badge>{r.last_error ? <span className="subtle">{r.last_error}</span> : null}</span> },
    { key: "fired", header: "Fired", render: (r) => <span className="subtle">{r.fire_count ? `${r.fire_count} × · ${formatRelative(r.last_fired_at)}` : "Never"}</span> },
    { key: "runs", header: <span className="sr-only">Runs</span>, render: (r) => <Button size="sm" onClick={(e) => { e.stopPropagation(); setRunsOf(r); }}>Runs</Button> },
  ];

  return (
    <div className="stack">
      <PageHeader title="Automation"
        description="When something happens, do something: a missed call to the office emails a group, a door controller held open starts a page. Rules listen to the same events as webhooks, or to a request to their own address."
        actions={manage ? <Button variant="primary" icon="plus" onClick={() => setEditing("new")}>New rule</Button> : null} />
      {shownUrl ? (
        <Callout tone="info" title={`Address of “${shownUrl.name}”`}>
          <p style={{ margin: "0 0 8px" }}>Give this address to the device; it is shown once. The device sends a POST request, with an optional JSON body whose fields the conditions can test.</p>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}><code style={{ overflowWrap: "anywhere" }}>{shownUrl.url}</code><CopyButton text={shownUrl.url} /></div>
        </Callout>
      ) : null}
      <Card flush>
        <DataTable columns={columns} rows={rules.data} rowKey={(r) => r.id} loading={rules.loading} error={rules.error} onRetry={rules.reload}
          caption="Automation rules" onRowClick={manage ? (r) => setEditing(r) : undefined} rowLabel={(r) => `Edit ${r.name}`}
          empty={<EmptyState compact icon="activity" title="No rules yet">{manage ? "Create one: choose what it listens to, the conditions, and what it does." : "Nothing is automated yet."}</EmptyState>} />
      </Card>
      {editing ? (
        <RuleDialog rule={editing === "new" ? null : editing} triggers={triggers.data ?? []} onClose={() => setEditing(null)}
          onSaved={(r) => { setEditing(null); rules.reload(); if (r.hook_url) setShownUrl({ name: r.name, url: r.hook_url }); }} />
      ) : null}
      {runsOf ? <RunsDialog rule={runsOf} onClose={() => setRunsOf(null)} /> : null}
    </div>
  );
}

function RuleDialog({ rule, triggers, onClose, onSaved }: { rule: Rule | null; triggers: Trigger[]; onClose: () => void; onSaved: (r: Rule) => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const { session } = useSession();
  const { organizations } = useOrganizationOptions(true);
  const [org, setOrg] = useState(rule?.organization_id ?? session?.user.home_organization_id ?? "");
  const orgId = org || organizations[0]?.id || "";
  const [name, setName] = useState(rule?.name ?? "");
  const [trigger, setTrigger] = useState(rule?.trigger ?? "call.ended");
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [cooldown, setCooldown] = useState(String(rule?.cooldown_seconds ?? 60));
  const [conditions, setConditions] = useState<Condition[]>(rule?.conditions ?? []);
  const email = rule?.actions.find((a) => a.type === "email");
  const pageAction = rule?.actions.find((a) => a.type === "page");
  const [emailTo, setEmailTo] = useState((email?.to ?? []).join(", "));
  const [pageId, setPageId] = useState(pageAction?.page_id ?? "");
  const [audioId, setAudioId] = useState(pageAction?.audio_id ?? "");
  const [busy, setBusy] = useState<"save" | "delete" | "test" | "rotate" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const pages = useApiData<Page<PagingPage>>(orgId ? "/pages" : null, { organization_id: orgId, limit: 200 });
  const recordings = useApiData<Page<Prompt>>(orgId ? "/prompts" : null, { organization_id: orgId, limit: 200 });
  const fields = triggers.find((t) => t.name === trigger)?.fields ?? [];

  const actions = (): Action[] => {
    const out: Action[] = [];
    const to = emailTo.split(/[\s,;]+/).filter(Boolean);
    if (to.length) out.push({ type: "email", to });
    if (pageId) out.push({ type: "page", page_id: pageId, ...(audioId ? { audio_id: audioId } : {}) });
    return out;
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy("save");
    errors.clear();
    const body = {
      name: name.trim(), enabled, cooldown_seconds: Number(cooldown) || 0,
      conditions: conditions.filter((c) => c.field.trim()).map((c) => ({ field: c.field.trim(), ...(c.contains !== undefined ? { contains: c.contains } : { equals: c.equals ?? "" }) })),
      actions: actions(),
    };
    try {
      const saved = rule
        ? await api.patch<Rule>(`/automation/rules/${rule.id}`, body)
        : await api.post<Rule>("/automation/rules", { ...body, organization_id: orgId, trigger });
      toast.success(rule ? "Rule saved" : "Rule created");
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };
  const act = async (what: "test" | "rotate" | "delete") => {
    if (!rule) return;
    setBusy(what);
    errors.clear();
    try {
      if (what === "test") {
        await api.post(`/automation/rules/${rule.id}/test`);
        toast.success("Test run queued", "It runs within a few seconds; see Runs.");
      } else if (what === "rotate") {
        onSaved(await api.post<Rule>(`/automation/rules/${rule.id}/rotate-hook`));
        return;
      } else {
        await api.del(`/automation/rules/${rule.id}`);
        toast.success("Rule deleted");
        onSaved({ ...rule, hook_url: null });
        return;
      }
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(null);
    }
  };
  const valid = name.trim() && actions().length > 0 && (rule || orgId);

  return (
    <Dialog open onClose={onClose} busy={!!busy} size="lg" title={rule ? rule.name : "New rule"}
      footer={(
        <>
          {rule ? <Button variant="danger" onClick={() => setConfirmDelete(true)} disabled={!!busy}>Delete</Button> : null}
          {rule ? <Button onClick={() => act("test")} loading={busy === "test"} disabled={!!busy}>Test now</Button> : null}
          {rule?.trigger === HOOK ? <Button onClick={() => act("rotate")} loading={busy === "rotate"} disabled={!!busy}>New address</Button> : null}
          <Button onClick={onClose} disabled={!!busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="rule-form" loading={busy === "save"} disabled={!valid}>{rule ? "Save" : "Create rule"}</Button>
        </>
      )}>
      <form id="rule-form" className="stack stack--sm" onSubmit={submit}>
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="Missed calls to the office" onChange={(e) => setName(e.target.value)} />
        {!rule && organizations.length > 1 ? (
          <SelectField label="Organization" value={orgId} options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <SelectField label="When" value={trigger} disabled={!!rule} help={rule ? "The trigger of a rule does not change; create another rule instead." : trigger === HOOK ? "The rule gets its own secret address; a device calls it." : undefined}
          options={triggers.map((t) => ({ value: t.name, label: t.name === HOOK ? "A device calls the rule's address" : `${t.group}: ${t.description}` }))}
          onChange={(e) => { setTrigger(e.target.value); setConditions([]); }} />
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label" style={{ marginBottom: 8 }}>Only if</legend>
          <div className="stack stack--sm">
            {conditions.map((c, i) => (
              <div key={i} className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
                <TextField label={i === 0 ? "Field" : <span className="sr-only">Field</span>} list="rule-fields" value={c.field} placeholder={fields[0] ?? "field"} spellCheck={false}
                  onChange={(e) => setConditions(conditions.map((x, j) => j === i ? { ...x, field: e.target.value } : x))} />
                <SelectField label={i === 0 ? "Test" : <span className="sr-only">Test</span>} value={c.contains !== undefined ? "contains" : "equals"} options={[{ value: "equals", label: "is" }, { value: "contains", label: "contains" }]}
                  onChange={(e) => setConditions(conditions.map((x, j) => j === i ? (e.target.value === "contains" ? { field: x.field, contains: x.equals ?? x.contains ?? "" } : { field: x.field, equals: x.contains ?? x.equals ?? "" }) : x))} />
                <TextField label={i === 0 ? "Value" : <span className="sr-only">Value</span>} value={c.contains ?? c.equals ?? ""} placeholder={c.field === "outcome" ? "missed" : ""}
                  onChange={(e) => setConditions(conditions.map((x, j) => j === i ? (x.contains !== undefined ? { ...x, contains: e.target.value } : { ...x, equals: e.target.value }) : x))} />
                <IconButton icon="trash" size="sm" label="Remove the condition" onClick={() => setConditions(conditions.filter((_, j) => j !== i))} />
              </div>
            ))}
            <datalist id="rule-fields">{fields.map((f) => <option key={f} value={f} />)}</datalist>
            <div><Button size="sm" icon="plus" onClick={() => setConditions([...conditions, { field: "", equals: "" }])}>Add a condition</Button></div>
            {fields.length ? <p className="subtle" style={{ margin: 0 }}>Fields of this event: <span className="mono">{fields.join(", ")}</span>. All conditions must hold; text compares without case.</p> : null}
          </div>
        </fieldset>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label" style={{ marginBottom: 8 }}>Then</legend>
          <div className="stack stack--sm">
            <TextArea label="Email" rows={2} value={emailTo} placeholder="office@example.org, principal@example.org" help="Addresses told what happened (Settings → Email delivery must be on). Leave empty for no email." onChange={(e) => setEmailTo(e.target.value)} />
            <div className="grid grid--2">
              <SelectField label="Start a page" value={pageId} placeholder="No page" options={[{ value: "", label: "No page" }, ...(pages.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))]} onChange={(e) => setPageId(e.target.value)} />
              {pageId ? (
                <SelectField label="Recording" value={audioId} options={[{ value: "", label: "The page's own recording" }, ...(recordings.data?.items ?? []).map((p) => ({ value: p.id, label: p.name }))]} onChange={(e) => setAudioId(e.target.value)} />
              ) : null}
            </div>
          </div>
        </fieldset>
        <div className="grid grid--2">
          <TextField label="Quiet time (seconds)" type="number" min={0} max={86400} value={cooldown} help="After firing, the rule waits this long before it fires again." onChange={(e) => setCooldown(e.target.value)} />
          <Switch label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
      <ConfirmDialog open={confirmDelete} title={`Delete “${rule?.name ?? ""}”?`} confirmLabel="Delete rule" tone="danger" busy={busy === "delete"} onConfirm={() => act("delete")} onCancel={() => setConfirmDelete(false)}>
        <p>{rule?.trigger === HOOK ? "The device's address stops working." : "The rule stops firing."}</p>
      </ConfirmDialog>
    </Dialog>
  );
}

function RunsDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const runs = useApiData<Run[]>(`/automation/rules/${rule.id}/runs`);
  const columns: Column<Run>[] = [
    { key: "when", header: "When", render: (r) => <span className="nowrap">{formatRelative(r.created_at)}</span> },
    { key: "status", header: "Result", render: (r) => <Badge tone={r.status === "done" ? "ok" : r.status === "failed" ? "danger" : "info"}>{r.status}</Badge> },
    { key: "detail", header: "Details", render: (r) => <span>{r.results.map((x) => `${x.type}: ${x.detail}`).join("; ") || "—"}</span> },
  ];
  return (
    <Dialog open onClose={onClose} size="lg" title={`Runs of “${rule.name}”`} footer={<><Button onClick={runs.reload}>Refresh</Button><Button onClick={onClose}>Close</Button></>}>
      <DataTable columns={columns} rows={runs.data} rowKey={(r) => r.id} loading={runs.loading} error={runs.error} onRetry={runs.reload} caption="Runs"
        empty={<EmptyState compact icon="history" title="No runs yet" />} />
    </Dialog>
  );
}
