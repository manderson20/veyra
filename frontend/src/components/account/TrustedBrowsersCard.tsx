// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Card, IconButton, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { describeUserAgent } from "@/lib/useragent";
import { useApiData } from "@/hooks/useApiData";

interface TrustedBrowser {
  id: string;
  label: string | null;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  last_ip: string | null;
  current: boolean;
}

/** Browsers that skip the second factor (#137), with "forget". */
export function TrustedBrowsersCard() {
  const toast = useToast();
  const list = useApiData<TrustedBrowser[]>("/auth/trusted-browsers");
  const [busy, setBusy] = useState<string | null>(null);
  if (!list.data?.length) return null;
  const forget = async (id: string | null) => {
    setBusy(id ?? "all");
    try {
      const r = await api.del<{ message: string }>(id ? `/auth/trusted-browsers/${id}` : "/auth/trusted-browsers");
      toast.success("Forgotten", r?.message);
      list.reload();
    } catch (err) {
      toast.error("Not changed", errorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card title="Trusted browsers" subtitle="These browsers sign you in with the password only, until the date shown. Forget one you no longer use, or all of them if a computer was lost."
      actions={<Button size="sm" loading={busy === "all"} onClick={() => forget(null)}>Forget all</Button>}>
      <ul className="list-plain">
        {list.data.map((b) => (
          <li key={b.id} className="list-row" style={{ paddingLeft: 0, paddingRight: 0 }}>
            <span style={{ minWidth: 0 }}>
              <span className="table__primary" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {describeUserAgent(b.label).label} {b.current ? <Badge tone="info">This browser</Badge> : null}
              </span>
              <span className="table__secondary">
                Trusted until {formatDateTime(b.expires_at)}{b.last_used_at ? ` · used ${formatRelative(b.last_used_at)}` : ""}{b.last_ip ? ` from ${b.last_ip}` : ""}
              </span>
            </span>
            <IconButton icon="trash" size="sm" label="Forget this browser" onClick={() => forget(b.id)} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
