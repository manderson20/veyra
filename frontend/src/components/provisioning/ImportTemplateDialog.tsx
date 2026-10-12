// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button, Callout, Dialog, SelectField, TextArea, useToast } from "../ui";
import { api, errorMessage } from "@/lib/api";
import type { TemplateSummary } from "@/lib/types";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

interface ValidateResult {
  valid: boolean;
  errors: string[];
  template?: TemplateSummary;
}

/** Import a template export as a local template: validate first, then import. */
export function ImportTemplateDialog({ open, onClose, onImported, initialText = "" }: {
  open: boolean;
  onClose: () => void;
  onImported: (key: string) => void;
  initialText?: string;
}) {
  const toast = useToast();
  const { session } = useSession();
  const { organizations } = useOrganizationOptions(open);
  const [text, setText] = useState("");
  const [org, setOrg] = useState("");
  const [result, setResult] = useState<ValidateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useOnChange(open, () => {
    if (open) {
      setText(initialText);
      setOrg(session?.is_platform_admin ? "" : (session?.user.home_organization_id ?? ""));
      setResult(null);
      setError(null);
    }
  });

  const parse = (): Record<string, unknown> | null => {
    try {
      const doc = JSON.parse(text) as unknown;
      if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error("not an object");
      return doc as Record<string, unknown>;
    } catch {
      setError("The text is not a valid JSON template export.");
      return null;
    }
  };

  const validate = async () => {
    setError(null);
    setResult(null);
    const doc = parse();
    if (!doc) return;
    setBusy(true);
    try {
      setResult(await api.post<ValidateResult>("/provisioning/templates/validate", { document: doc }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const doImport = async () => {
    const doc = parse();
    if (!doc) return;
    setBusy(true);
    setError(null);
    try {
      const t = await api.post<TemplateSummary>("/provisioning/templates/import", { document: doc, organization_id: org || null });
      toast.success("Template imported", `${t.name} (${t.key})`);
      onClose();
      onImported(t.key);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title="Import template"
      description="Paste a Veyra template export. It is validated before anything is saved."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={validate} loading={busy && !result} disabled={!text.trim()}>Validate</Button>
          <Button variant="primary" onClick={doImport} loading={busy && !!result} disabled={!result?.valid || (!session?.is_platform_admin && !org)}>Import</Button>
        </>
      }>
      <TextArea label="Template export (JSON)" rows={12} spellCheck={false} style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
        value={text} onChange={(e) => { setText(e.target.value); setResult(null); }} />
      <SelectField label="Organization" value={org} placeholder={session?.is_platform_admin ? "All organizations (installation-wide)" : "Choose an organization"}
        options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
      {result?.valid ? <Callout tone="ok" title="Template is valid">{result.template?.name} <span className="mono">{result.template?.key}</span> {result.template?.version}</Callout> : null}
      {result && !result.valid ? (
        <Callout tone="danger" title="Template is not valid">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{result.errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </Callout>
      ) : null}
      {error ? <Callout tone="danger">{error}</Callout> : null}
    </Dialog>
  );
}
