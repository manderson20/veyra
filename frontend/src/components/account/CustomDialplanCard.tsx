// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button, Callout, Card, LoadingState, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useApiData } from "@/hooks/useApiData";

interface CustomDialplan {
  text: string;
  contexts: string[];
  blocked_applications: string[];
  blocked_functions: string[];
}

/** A platform administrator's own Asterisk contexts (docs/CUSTOM_DIALPLAN.md). */
export function CustomDialplanCard({ editable }: { editable: boolean }) {
  const toast = useToast();
  const data = useApiData<CustomDialplan>("/telephony/custom-dialplan");
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saved = data.data?.text;
  const text = draft ?? saved ?? "";

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put("/telephony/custom-dialplan", { text });
      toast.success("Custom dialplan saved", "Deploy the changes to put it into service.");
      data.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Custom dialplan" subtitle="Your own Asterisk contexts, for what Veyra has no feature for. Platform administrators only; every change is in the audit log.">
      {data.loading && !data.data ? <LoadingState /> : (
        <div className="stack stack--sm">
          <Callout tone="warn" title="This is code that runs on the server">The checks below catch the known ways to reach the server&apos;s shell and files, but they are not a sandbox. Only paste dialplan you understand.</Callout>
          <p className="subtle" style={{ margin: 0 }}>Contexts must be named <span className="mono">[custom-…]</span>; only <span className="mono">exten =&gt;</span>, <span className="mono">same =&gt;</span> and <span className="mono">include =&gt; custom-…</span> lines are allowed.</p>
          <label className="field">
            <span className="field__label">Dialplan</span>
            <textarea className="input mono" rows={14} spellCheck={false} value={text} onChange={(e) => setDraft(e.target.value)} disabled={!editable || busy} />
          </label>
          {error ? <Callout tone="danger">{error}</Callout> : null}
          {editable ? <div><Button size="sm" variant="primary" onClick={() => void save()} loading={busy} disabled={text === saved}>Save</Button></div> : null}
          {data.data ? (
            <details>
              <summary>What is not allowed</summary>
              <p className="subtle">Applications: {data.data.blocked_applications.join(", ")}.</p>
              <p className="subtle">Functions: {data.data.blocked_functions.join(", ")}.</p>
            </details>
          ) : null}
        </div>
      )}
    </Card>
  );
}
