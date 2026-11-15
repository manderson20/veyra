// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Card, Checkbox, ErrorState, LoadingState, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { CallerNameSettings } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";

interface Draft {
  enabled: boolean;
  url: string;
  header_name: string;
  header_value: string;
  clear_header_value: boolean;
  json_field: string;
  timeout_ms: string;
  cache_minutes: string;
}

function draftOf(s: CallerNameSettings): Draft {
  return {
    enabled: s.enabled,
    url: s.url ?? "",
    header_name: s.header_name ?? "",
    header_value: "",
    clear_header_value: false,
    json_field: s.json_field ?? "",
    timeout_ms: String(s.timeout_ms),
    cache_minutes: String(s.cache_minutes),
  };
}

/** Caller name lookup over HTTP (issue #392). Platform administrators only. */
export function CallerNameCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const errors = useFormErrors();
  const data = useApiData<CallerNameSettings>("/telephony/caller-name");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [testNumber, setTestNumber] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);
  useOnChange(data.data, (s) => setDraft(s ? draftOf(s) : null));

  if (data.error) return <Card title="Caller name lookup"><ErrorState compact error={data.error} onRetry={data.reload} /></Card>;
  if (!draft || !data.data) return <Card title="Caller name lookup"><LoadingState /></Card>;
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: Record<string, unknown> = {
        enabled: draft.enabled,
        url: draft.url.trim() || null,
        header_name: draft.header_name.trim() || null,
        json_field: draft.json_field.trim() || null,
        timeout_ms: Number(draft.timeout_ms),
        cache_minutes: Number(draft.cache_minutes),
      };
      if (draft.clear_header_value) body.header_value = null;
      else if (draft.header_value) body.header_value = draft.header_value;
      data.setData(await api.put<CallerNameSettings>("/telephony/caller-name", body));
      toast.success("Caller name lookup saved", "Deploy changes for inbound routes to use it.");
    } catch (err) {
      errors.set(err);
      toast.error("Not saved", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setTestResult(null);
    try {
      const r = await api.post<{ name: string; milliseconds: number }>("/telephony/caller-name/test", { number: testNumber.trim() });
      setTestResult(r.name ? `${r.name} (${r.milliseconds} ms)` : `No name (${r.milliseconds} ms)`);
    } catch (err) {
      setTestResult(errorMessage(err));
    }
  };

  return (
    <Card title="Caller name lookup" subtitle="Shows a name for callers who send none, from an online lookup service. Turn it on per inbound route with Look up the caller's name." id="caller-name">
      <form className="stack" onSubmit={save}>
        <Callout tone="info" title={"Callers' numbers are sent to the service"}>
          Each lookup sends the caller&apos;s number to the address below. Use a service your district has an agreement with. Names are kept for the cache time, so a number is not looked up on every call.
        </Callout>
        <Checkbox label="Look up caller names" checked={draft.enabled} disabled={!editable} onChange={(e) => set({ enabled: e.target.checked })} />
        <TextField label="Lookup address" disabled={!editable} value={draft.url} error={errors.fields.url} placeholder="https://api.example.com/cnam/{number}"
          help="https only. {number} is replaced with the caller's number." onChange={(e) => set({ url: e.target.value })} />
        <div className="form-grid">
          <TextField label="Header name" disabled={!editable} value={draft.header_name} error={errors.fields.header_name} placeholder="e.g. Authorization" onChange={(e) => set({ header_name: e.target.value })} />
          <div className="stack stack--xs">
            <TextField label="Header value" type="password" autoComplete="off" disabled={!editable || draft.clear_header_value} value={draft.header_value} error={errors.fields.header_value}
              help={data.data.has_header_value ? "A value is set. Type a new one to replace it." : "For example an API key; stored encrypted."} onChange={(e) => set({ header_value: e.target.value })} />
            {data.data.has_header_value ? <Checkbox label="Remove the header value" checked={draft.clear_header_value} disabled={!editable} onChange={(e) => set({ clear_header_value: e.target.checked, header_value: "" })} /> : null}
          </div>
        </div>
        <div className="form-grid">
          <TextField label="Name field in the answer" disabled={!editable} value={draft.json_field} error={errors.fields.json_field} placeholder="e.g. name or data.caller.name"
            help="For an answer in JSON; empty: the answer is the name as plain text." onChange={(e) => set({ json_field: e.target.value })} />
          <TextField label="Wait at most (ms)" type="number" min={200} max={2500} disabled={!editable} value={draft.timeout_ms} error={errors.fields.timeout_ms}
            help="200 to 2500. The phone rings after this even if the service has not answered." onChange={(e) => set({ timeout_ms: e.target.value })} />
          <TextField label="Keep names for (minutes)" type="number" min={0} max={43200} disabled={!editable} value={draft.cache_minutes} error={errors.fields.cache_minutes}
            onChange={(e) => set({ cache_minutes: e.target.value })} />
        </div>
        {editable ? <div className="form-actions"><Button variant="primary" type="submit" loading={busy}>Save</Button></div> : null}
      </form>
      {editable && data.data.url ? (
        <div className="row" style={{ gap: 8, marginTop: 12, alignItems: "flex-end" }}>
          <TextField label="Try a number" value={testNumber} inputMode="tel" onChange={(e) => setTestNumber(e.target.value)} />
          <Button onClick={() => void test()} disabled={testNumber.trim().length < 3}>Look up</Button>
          {testResult ? <span className="subtle">{testResult}</span> : null}
        </div>
      ) : null}
    </Card>
  );
}
