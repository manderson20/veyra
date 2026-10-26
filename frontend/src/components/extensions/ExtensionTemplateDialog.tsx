// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Button, Callout, Checkbox, Dialog, SelectField, Switch, TextArea, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { ClassOfService, Department, ExtensionTemplate, ExtensionTemplateSettings, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

type Field = keyof ExtensionTemplateSettings;
const FIELDS: Field[] = ["class_of_service_id", "intercom", "max_registrations", "department_id", "ring_seconds", "call_waiting_off", "anonymous_reject"];
type Values = { class_of_service_id: string; intercom: string; max_registrations: string; department_id: string; ring_seconds: string; call_waiting_off: boolean; anonymous_reject: boolean };
const EMPTY: Values = { class_of_service_id: "", intercom: "default", max_registrations: "", department_id: "", ring_seconds: "30", call_waiting_off: false, anonymous_reject: false };

/** Create or edit an extension template (issue #172): each setting is either left to the extension, set by the template, or set and locked. */
export function ExtensionTemplateDialog({ open, onClose, template, onSaved }: { open: boolean; onClose: () => void; template?: ExtensionTemplate; onSaved: (t: ExtensionTemplate) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open && !template);
  const [org, setOrg] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<Values>(EMPTY);
  const [chosen, setChosen] = useState<Set<Field>>(new Set());
  const [locked, setLocked] = useState<Set<Field>>(new Set());
  const [busy, setBusy] = useState(false);
  const effectiveOrg = template?.organization_id ?? (org || (organizations.length === 1 ? organizations[0]!.id : ""));
  const classes = useApiData<Page<ClassOfService>>(open && effectiveOrg ? "/classes-of-service" : null, { organization_id: effectiveOrg, limit: 200 });
  const departments = useApiData<Department[]>(open && effectiveOrg ? "/departments" : null, { organization_id: effectiveOrg });

  useOnChange(open, () => {
    if (!open) return;
    const s = template?.settings ?? {};
    setOrg(template?.organization_id ?? session?.user.home_organization_id ?? "");
    setName(template?.name ?? "");
    setDescription(template?.description ?? "");
    setValues({
      class_of_service_id: s.class_of_service_id ?? "",
      intercom: s.intercom ?? "default",
      max_registrations: s.max_registrations ? String(s.max_registrations) : "",
      department_id: s.department_id ?? "",
      ring_seconds: String(s.ring_seconds ?? 30),
      call_waiting_off: s.call_waiting_off ?? false,
      anonymous_reject: s.anonymous_reject ?? false,
    });
    setChosen(new Set(Object.keys(s) as Field[]));
    setLocked(new Set(template?.locked ?? []));
    errors.clear();
  });

  const toggle = (f: Field, on: boolean) => {
    setChosen((prev) => { const n = new Set(prev); if (on) n.add(f); else n.delete(f); return n; });
    if (!on) setLocked((prev) => { const n = new Set(prev); n.delete(f); return n; });
  };
  const lock = (f: Field, on: boolean) => setLocked((prev) => { const n = new Set(prev); if (on) n.add(f); else n.delete(f); return n; });
  const value = (f: Field): unknown => {
    switch (f) {
      case "class_of_service_id": return values.class_of_service_id || null;
      case "department_id": return values.department_id || null;
      case "max_registrations": return values.max_registrations ? Number(values.max_registrations) : null;
      case "ring_seconds": return Number(values.ring_seconds);
      case "intercom": return values.intercom;
      default: return values[f];
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body = {
        name: name.trim(),
        description: description.trim() || null,
        settings: Object.fromEntries(FIELDS.filter((f) => chosen.has(f)).map((f) => [f, value(f)])),
        locked: FIELDS.filter((f) => locked.has(f)),
      };
      const saved = template
        ? await api.patch<ExtensionTemplate>(`/extension-templates/${template.id}`, body)
        : await api.post<ExtensionTemplate>("/extension-templates", { organization_id: effectiveOrg, ...body });
      toast.success(template ? "Template saved" : `Template "${saved.name}" created`, template ? "Apply it to change its extensions." : undefined);
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const row = (f: Field, label: string, control: ReactNode) => (
    <div className="stack stack--xs" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <Checkbox label={label} checked={chosen.has(f)} onChange={(e) => toggle(f, e.target.checked)} />
        <Checkbox label="Locked" checked={locked.has(f)} disabled={!chosen.has(f)} onChange={(e) => lock(f, e.target.checked)} />
      </div>
      {chosen.has(f) ? control : null}
      {errors.fields[`settings.${f}`] ? <p className="field__error" role="alert">{errors.fields[`settings.${f}`]}</p> : null}
    </div>
  );

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={template ? `Edit template "${template.name}"` : "New extension template"}
      description="Tick what the template sets. Extensions created with it take these settings; Apply brings its extensions back to them. Locked settings cannot be changed on the extensions while they follow the template."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="ext-template-form" loading={busy} disabled={!effectiveOrg || !name.trim()}>{template ? "Save changes" : "Create template"}</Button></>}>
      <form id="ext-template-form" className="stack stack--sm" onSubmit={submit}>
        {!template && organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <TextField label="Name" required autoFocus value={name} error={errors.fields.name} placeholder="e.g. Classroom phones" onChange={(e) => setName(e.target.value)} />
        <TextArea label="Description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        {row("class_of_service_id", "Class of service", <SelectField label={<span className="sr-only">Class of service</span>} value={values.class_of_service_id} placeholder="None (everything allowed)"
          options={(classes.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))} onChange={(e) => setValues({ ...values, class_of_service_id: e.target.value })} />)}
        {row("intercom", "Intercom", <SelectField label={<span className="sr-only">Intercom</span>} value={values.intercom}
          options={[{ value: "default", label: "The organization's setting" }, { value: "allow", label: "Allowed" }, { value: "deny", label: "Not allowed" }]} onChange={(e) => setValues({ ...values, intercom: e.target.value })} />)}
        {row("max_registrations", "Phones that may register", <TextField label={<span className="sr-only">Phones that may register</span>} type="number" min={1} max={16} value={values.max_registrations} placeholder="Automatic"
          onChange={(e) => setValues({ ...values, max_registrations: e.target.value })} />)}
        {row("department_id", "Department", <SelectField label={<span className="sr-only">Department</span>} value={values.department_id} placeholder="None"
          options={(departments.data ?? []).map((d) => ({ value: d.id, label: d.name }))} onChange={(e) => setValues({ ...values, department_id: e.target.value })} />)}
        {row("ring_seconds", "Ring time (seconds)", <TextField label={<span className="sr-only">Ring time</span>} type="number" min={5} max={120} value={values.ring_seconds}
          onChange={(e) => setValues({ ...values, ring_seconds: e.target.value })} />)}
        {row("call_waiting_off", "Call waiting", <Switch label="Call waiting off" checked={values.call_waiting_off} onChange={(e) => setValues({ ...values, call_waiting_off: e.target.checked })} />)}
        {row("anonymous_reject", "Callers who hide their number", <Switch label="Refused" checked={values.anonymous_reject} onChange={(e) => setValues({ ...values, anonymous_reject: e.target.checked })} />)}
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
