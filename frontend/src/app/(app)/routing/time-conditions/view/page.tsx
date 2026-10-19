// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import { EMPTY_TIME_CONDITION, TimeConditionFields, timeConditionBody, timeConditionDraft, timeConditionValid, type TimeConditionDraft } from "@/components/routing/TimeConditionFields";
import { Badge, Button, Callout, Card, Checkbox, ConfirmDialog, ErrorState, LoadingState, PageHeader, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { summarizeRanges } from "@/lib/routing";
import type { TimeCondition } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { describeHoliday } from "@/lib/holidays";

function TimeConditionView() {
  const id = useSearchParams().get("id");
  const router = useRouter();
  const { can } = useSession();
  const toast = useToast();
  const errors = useFormErrors();
  const tc = useApiData<TimeCondition>(id ? `/routing/time-conditions/${encodeURIComponent(id)}` : null);
  const { organizations } = useOrganizationOptions();
  const editable = can("routing.write");
  const [draft, setDraft] = useState<TimeConditionDraft>(EMPTY_TIME_CONDITION);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [changed, setChanged] = useState(0);
  const [temporary, setTemporary] = useState(true);
  const [overriding, setOverriding] = useState<"open" | "closed" | "clear" | null>(null);

  const orgTimezone = organizations.find((o) => o.id === tc.data?.organization_id)?.timezone;
  // Copy the record into the form when it arrives, and again once the organization's
  // time zone is known so an inherited zone shows as inherited.
  const loaded = tc.data;
  useOnChange(`${loaded?.id ?? ""}|${orgTimezone ?? ""}`, () => {
    if (loaded) setDraft(timeConditionDraft(loaded, orgTimezone));
  });

  if (!id) return <ErrorState title="No time condition selected" error={{ message: "Open a time condition from the list." }} />;
  if (tc.error) return <ErrorState title="Could not load time condition" error={tc.error} onRetry={tc.reload} />;
  if (!tc.data) return <LoadingState />;
  const t = tc.data;
  const dirty = JSON.stringify(timeConditionBody(draft)) !== JSON.stringify(timeConditionBody(timeConditionDraft(t, orgTimezone)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      tc.setData(await api.patch<TimeCondition>(`/routing/time-conditions/${t.id}`, timeConditionBody(draft)));
      setChanged((n) => n + 1);
      toast.success("Time condition saved", "If the engine configuration changed, Deploy changes appears in the top bar.");
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const override = async (state: "open" | "closed" | null) => {
    setOverriding(state ?? "clear");
    try {
      tc.setData(await api.post<TimeCondition>(`/routing/time-conditions/${t.id}/override`, { state, temporary }));
      toast.success(state ? `Forced ${state}` : "Back to the schedule", state ? (temporary ? "Until the schedule next changes state." : "Until you clear it here or from a phone.") : "Callers follow the schedule again.");
    } catch (err) {
      toast.error("Could not change the override", errorMessage(err));
    } finally {
      setOverriding(null);
    }
  };

  const remove = async () => {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.del(`/routing/time-conditions/${t.id}`);
      toast.success(`Time condition ${t.name} deleted`);
      router.push("/routing/time-conditions/");
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: "/routing/time-conditions/", label: "Time conditions" }}
        title={t.name}
        description={
          <span className="row">
            <span>{t.organization_name}</span>
            <Badge tone={t.open_now ? "ok" : "neutral"} icon={t.open_now ? "checkCircle" : "clock"}>{t.open_now ? "Open now" : "Closed now"}</Badge>
            <Badge tone="outline">{t.in_use_by ? `Used by ${t.in_use_by} ${t.in_use_by === 1 ? "route" : "routes"}` : "Not used"}</Badge>
          </span>
        }
        actions={editable ? <Button variant="danger" icon="trash" onClick={() => setDeleting(true)}>Delete</Button> : null}
      />
      <PendingChanges refreshKey={changed} />
      <div className="grid grid--2" style={{ alignItems: "start", gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <Card title="Schedule" subtitle={editable ? undefined : "You can view but not change this time condition."}>
          <form className="stack stack--sm" onSubmit={save}>
            <TimeConditionFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors.fields} timezonePlaceholder={orgTimezone} disabled={!editable} current={t} />
            {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
            {editable ? <div className="form-actions"><Button onClick={() => setDraft(timeConditionDraft(t, orgTimezone))} disabled={!dirty || busy}>Discard</Button><Button variant="primary" type="submit" loading={busy} disabled={!dirty || !timeConditionValid(draft)}>Save changes</Button></div> : null}
          </form>
        </Card>
        <div className="stack">
          <Card title="Override" subtitle="Force the condition open or closed right now; no deployment needed.">
            <dl className="dl">
              <dt>Schedule says</dt><dd><Badge tone={t.open_now ? "ok" : "neutral"}>{t.open_now ? "Open" : "Closed"}</Badge></dd>
              <dt>Callers get</dt><dd><Badge tone={t.effective_open ? "ok" : "neutral"} icon={t.override ? "alert" : undefined}>{t.effective_open ? "Open" : "Closed"}{t.override ? ` (forced${t.override_temporary ? ", until the schedule changes" : ", until cleared"})` : ""}</Badge></dd>
              {t.override ? <><dt>Forced by</dt><dd>{t.override_by ?? "—"}{t.override_at ? `, ${formatRelative(t.override_at)}` : ""}</dd></> : null}
              {t.code ? <><dt>Phone code</dt><dd><span className="mono">{t.code}</span>{t.has_pin ? " (PIN)" : ""}</dd></> : null}
            </dl>
            {editable ? (
              <div className="stack stack--xs" style={{ marginTop: 12 }}>
                <Checkbox label="Temporary: ends when the schedule next changes state" checked={temporary} onChange={(e) => setTemporary(e.target.checked)} />
                <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                  <Button size="sm" loading={overriding === "open"} disabled={overriding !== null || t.override === "open"} onClick={() => override("open")}>Force open</Button>
                  <Button size="sm" loading={overriding === "closed"} disabled={overriding !== null || t.override === "closed"} onClick={() => override("closed")}>Force closed</Button>
                  <Button size="sm" variant="ghost" loading={overriding === "clear"} disabled={overriding !== null || !t.override} onClick={() => override(null)}>Back to the schedule</Button>
                </div>
              </div>
            ) : null}
          </Card>
        <Card title="Information">
          <dl className="dl">
            <dt>Open hours</dt><dd>{summarizeRanges(t.ranges)}</dd>
            <dt>Holidays</dt><dd>{t.holidays.length ? <ul style={{ margin: 0, paddingLeft: "1.1em" }}>{t.holidays.map((h) => <li key={h}>{describeHoliday(h)}</li>)}</ul> : <span className="subtle">None</span>}</dd>
            <dt>Time zone</dt><dd><span className="mono">{t.timezone}</span>{orgTimezone && t.timezone === orgTimezone ? <span className="subtle"> (organization default)</span> : null}</dd>
            <dt>Organization</dt><dd>{t.organization_name}</dd>
            <dt>Created</dt><dd>{formatDateTime(t.created_at)}</dd>
            <dt>Updated</dt><dd>{formatRelative(t.updated_at)}</dd>
            <dt>Time condition ID</dt><dd className="mono">{t.id}</dd>
          </dl>
        </Card>
        </div>
      </div>
      <ConfirmDialog
        open={deleting}
        title={`Delete time condition ${t.name}?`}
        confirmLabel="Delete time condition"
        tone="danger"
        busy={deleteBusy}
        error={deleteError}
        onConfirm={remove}
        onCancel={() => { setDeleting(false); setDeleteError(null); }}
      >
        <p>{t.in_use_by ? `This time condition is used by ${t.in_use_by} inbound ${t.in_use_by === 1 ? "route" : "routes"}; remove it from them first or the deletion is refused.` : "No inbound route uses this time condition."}</p>
      </ConfirmDialog>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><TimeConditionView /></Suspense>;
}
