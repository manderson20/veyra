// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Badge, Callout, Card, ErrorState, LoadingState, useToast } from "@/components/ui";
import type { CompanionInfo } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/**
 * What an administrator needs to push the Companion extension to managed
 * browsers (Google Admin Console, Chrome and Edge policies): the stable
 * extension ID, the update manifest, the policy that preloads the server, and
 * the install-source pattern that lets users click "Add to Chrome" themselves.
 */
export function CompanionDeploymentCard() {
  const info = useApiData<CompanionInfo>("/companion/info");
  const toast = useToast();
  const copy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} copied`);
    } catch {
      toast.error("Could not copy", "Select the text and copy it by hand.");
    }
  };
  const d = info.data;
  const origin = typeof window !== "undefined" ? window.location.origin : "https://…";
  const policy = JSON.stringify({ serverUrl: origin }, null, 2);

  return (
    <Card title="Companion extension deployment" subtitle="Push the Veyra Companion to users' browsers without anyone installing it by hand.">
      {info.loading ? <LoadingState /> : null}
      {info.error ? <ErrorState error={info.error} onRetry={info.reload} /> : null}
      {d && !d.extension_id ? (
        <Callout tone="warn" title="Package not signed on this server">
          The installer did not produce the signed package. Run the upgrade again; the download of the unsigned zip
          {d.zip_url ? " is still available" : " is unavailable too"}.
        </Callout>
      ) : null}
      {d?.extension_id ? (
        <div className="stack">
          <dl className="dl">
            <dt>Extension</dt>
            <dd className="row" style={{ gap: 8 }}>
              {d.name} <Badge tone="neutral">{d.version}</Badge>
            </dd>
            <dt>Extension ID</dt>
            <dd>
              <code className="mono">{d.extension_id}</code>{" "}
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void copy("Extension ID", d.extension_id ?? "")}>Copy</button>
            </dd>
            <dt>Update URL</dt>
            <dd>
              <code className="mono">{d.update_url}</code>{" "}
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void copy("Update URL", d.update_url ?? "")}>Copy</button>
            </dd>
            <dt>Install-source pattern</dt>
            <dd>
              <code className="mono">{d.install_sources_pattern}</code>{" "}
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void copy("Pattern", d.install_sources_pattern ?? "")}>Copy</button>
            </dd>
            <dt>Policy for extensions</dt>
            <dd>
              <pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{policy}</pre>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => void copy("Policy", policy)}>Copy</button>
            </dd>
          </dl>
          <details>
            <summary style={{ cursor: "pointer" }}><strong>Google Admin Console steps</strong></summary>
            <ol className="stack" style={{ marginTop: 12, paddingLeft: 20, gap: 6 }}>
              <li>Devices → Chrome → Apps &amp; extensions → Users &amp; browsers; pick the organizational unit.</li>
              <li>Click the + button → <em>Add Chrome app or extension by ID</em> → <em>From a custom URL</em>; paste the Extension ID and the Update URL.</li>
              <li>Set the installation policy to <em>Force install</em> (or <em>Force install + pin to toolbar</em>). The extension then appears for every user in that unit, with the server&apos;s host permission granted.</li>
              <li>Under <em>Policy for extensions</em> paste the JSON above, so the server address is preloaded and locked; users only sign in.</li>
              <li>Optional: to let users click <em>Add to Chrome</em> from their account page instead, add the install-source pattern under Chrome → Settings → Users &amp; browsers → <em>Extension install sources</em> (policy ExtensionInstallSources).</li>
            </ol>
            <p className="subtle">
              Each Veyra upgrade re-signs the package with the same key, so the ID stays the same and managed browsers pick up the new version from the Update URL within hours. The browser must trust this server&apos;s certificate.
            </p>
          </details>
        </div>
      ) : null}
    </Card>
  );
}
