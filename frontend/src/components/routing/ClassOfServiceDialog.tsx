// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { Button, Callout, Checkbox, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { ClassOfService, ClassOfServiceInput, FeatureCodes, OutboundRoutes } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

/** Create or edit a class of service (docs/CALL_FEATURES.md §3.8). */
export function ClassOfServiceDialog({ open, onClose, cls, onSaved }: { open: boolean; onClose: () => void; cls?: ClassOfService; onSaved: (c: ClassOfService) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !cls);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [routes, setRoutes] = useState<string[]>([]);
  const [allCodes, setAllCodes] = useState(true);
  const [codes, setCodes] = useState<string[]>([]);
  const [extForwards, setExtForwards] = useState(true);
  const [extFollowMe, setExtFollowMe] = useState(true);
  const [intercom, setIntercom] = useState(true);
  const [monitor, setMonitor] = useState(false);
  const [protectedCls, setProtectedCls] = useState(false);
  const [fax, setFax] = useState(true);
  const [maxCalls, setMaxCalls] = useState("");
  const [busy, setBusy] = useState(false);
  const effectiveOrg = cls?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const routeList = useApiData<OutboundRoutes>(open ? "/routing/outbound" : null);
  const codeList = useApiData<FeatureCodes>(open ? "/telephony/feature-codes" : null);

  useOnChange(open, () => {
    if (open) {
      setOrg(cls?.organization_id ?? session?.user.home_organization_id ?? "");
      setName(cls?.name ?? "");
      setDescription(cls?.description ?? "");
      setRoutes(cls ? cls.allowed_outbound_routes.map((r) => r.id) : []);
      setAllCodes(cls ? cls.allowed_feature_code_keys === null : true);
      setCodes(cls?.allowed_feature_code_keys ?? []);
      setExtForwards(cls?.allow_external_forwards ?? true);
      setExtFollowMe(cls?.allow_external_follow_me ?? true);
      setIntercom(cls?.allow_intercom ?? true);
      setMonitor(cls?.allow_monitor ?? false);
      setProtectedCls(cls?.monitor_protected ?? false);
      setFax(cls?.allow_fax ?? true);
      setMaxCalls(cls?.max_outbound_calls ? String(cls.max_outbound_calls) : "");
      errors.clear();
    }
  });

  const available = (routeList.data?.items ?? []).filter((r) => !r.is_emergency && (!r.organization_id || r.organization_id === effectiveOrg));
  const toggle = (list: string[], id: string, set: (v: string[]) => void) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: ClassOfServiceInput = {
        name: name.trim(),
        description: description.trim() || null,
        allowed_outbound_route_ids: routes,
        allow_external_forwards: extForwards,
        allow_external_follow_me: extFollowMe,
        allow_intercom: intercom,
        allow_monitor: monitor,
        monitor_protected: protectedCls,
        allow_fax: fax,
        ...(allCodes ? (cls ? { all_feature_codes: true } : { allowed_feature_code_keys: null }) : { allowed_feature_code_keys: codes }),
        ...(maxCalls.trim() ? { max_outbound_calls: Number(maxCalls) } : (cls ? { no_call_limit: true } : {})),
      };
      const saved = cls
        ? await api.patch<ClassOfService>(`/classes-of-service/${cls.id}`, body)
        : await api.post<ClassOfService>("/classes-of-service", { organization_id: effectiveOrg, ...body });
      toast.success(cls ? "Class saved" : `Class "${saved.name}" created`, "Deploy changes to apply it to the phone system.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={cls ? `Edit class "${cls.name}"` : "New class of service"}
      description="Phones in the class may use only the routes and feature codes ticked here. Emergency routes always work."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="cos-form" loading={busy} disabled={!effectiveOrg || !name.trim()}>{cls ? "Save changes" : "Create class"}</Button></>}>
      <form id="cos-form" className="stack stack--sm" onSubmit={submit}>
        {!cls && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setRoutes([]); }} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Classrooms" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} error={errors.fields.description} onChange={(e) => setDescription(e.target.value)} />
        <fieldset className="stack stack--sm">
          <legend className="field__label">Outbound routes the class may use</legend>
          {available.length ? available.map((r) => <Checkbox key={r.id} label={r.name} checked={routes.includes(r.id)} onChange={() => toggle(routes, r.id, setRoutes)} />) : <p className="subtle">No non-emergency outbound routes yet; the class can only call inside and 911.</p>}
          {errors.fields.allowed_outbound_route_ids ? <p className="field__error" role="alert">{errors.fields.allowed_outbound_route_ids}</p> : null}
        </fieldset>
        <Switch label="Every feature code" checked={allCodes} onChange={(e) => setAllCodes(e.target.checked)} description="Off: tick the codes the class may dial." />
        {!allCodes ? (
          <fieldset className="stack stack--sm">
            <legend className="field__label">Feature codes</legend>
            {(codeList.data?.codes ?? []).filter((c) => c.enabled).map((c) => <Checkbox key={c.key} label={`${c.label} (${c.code})`} checked={codes.includes(c.key)} onChange={() => toggle(codes, c.key, setCodes)} />)}
          </fieldset>
        ) : null}
        <div className="grid grid--2">
          <Checkbox label="Forwards may go to outside numbers" checked={extForwards} onChange={(e) => setExtForwards(e.target.checked)} />
          <Checkbox label="Follow-me may ring outside numbers" checked={extFollowMe} onChange={(e) => setExtFollowMe(e.target.checked)} />
          <Checkbox label="May use intercom" checked={intercom} onChange={(e) => setIntercom(e.target.checked)} />
          <Checkbox label="May send faxes from My Phone" checked={fax} onChange={(e) => setFax(e.target.checked)} />
          <Checkbox label="May listen to, whisper on and join calls (supervisor codes)" checked={monitor} onChange={(e) => setMonitor(e.target.checked)}
            description="The phone codes *222, *223 and *224 plus an extension. Check your state's recording-consent rules." />
          <Checkbox label="Never monitored" checked={protectedCls} onChange={(e) => setProtectedCls(e.target.checked)}
            description="For counselors, nurses and others whose calls must stay private: no supervisor code or web button reaches these phones." />
          <TextField label="Outside calls at once (empty: no limit)" type="number" min={1} max={500} value={maxCalls} error={errors.fields.max_outbound_calls} onChange={(e) => setMaxCalls(e.target.value)} help="Counted across all phones of the class." />
        </div>
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
