// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { CopyButton } from "@/components/common/CopyButton";
import { Badge, Callout, Card, ErrorState, LinkButton, LoadingState } from "@/components/ui";
import type { CompanionInfo } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/**
 * The Companion package on this server, and the way into the rollout guide
 * (System → Companion rollout) that walks through pushing it to managed
 * browsers.
 */
export function CompanionDeploymentCard() {
  const info = useApiData<CompanionInfo>("/companion/info");
  const d = info.data;

  return (
    <Card title="Companion extension deployment" subtitle="Push the Veyra Companion to people's browsers so nobody installs it by hand." actions={<LinkButton href="/system/companion/" variant="primary" size="sm">Open the rollout guide</LinkButton>}>
      {info.loading ? <LoadingState /> : null}
      {info.error ? <ErrorState error={info.error} onRetry={info.reload} /> : null}
      {d && !d.extension_id ? (
        <Callout tone="warn" title="Package not signed on this server">
          The installer did not produce the signed package. Run the upgrade again; the download of the unsigned zip
          {d.zip_url ? " is still available" : " is unavailable too"}.
        </Callout>
      ) : null}
      {d?.extension_id ? (
        <dl className="dl">
          <dt>Extension</dt>
          <dd className="row" style={{ gap: 8 }}>{d.name} <Badge tone="neutral">{d.version}</Badge></dd>
          <dt>Extension ID</dt>
          <dd className="row" style={{ gap: 6 }}><code className="mono">{d.extension_id}</code><CopyButton text={d.extension_id} /></dd>
          <dt>Update URL</dt>
          <dd className="row" style={{ gap: 6, flexWrap: "wrap" }}><code className="mono" style={{ wordBreak: "break-all" }}>{d.update_url}</code><CopyButton text={d.update_url ?? ""} /></dd>
        </dl>
      ) : null}
    </Card>
  );
}
