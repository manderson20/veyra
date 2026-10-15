// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Callout } from "@/components/ui";
import type { CentralNotice as Notice } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** The notice set by the central console this installation is enrolled with (docs/CENTRAL_MANAGEMENT.md). */
export function CentralNotice() {
  const notice = useApiData<Notice>("/central/notice");
  const text = notice.data?.text;
  if (!text) return null;
  return (
    <div style={{ padding: "0 var(--space-6)", paddingTop: "var(--space-4)", maxWidth: "var(--content-max)", margin: "0 auto", width: "100%" }}>
      <Callout tone="info" title={notice.data?.console_name ? `From ${notice.data.console_name}` : "From the central console"}>
        {text}
      </Callout>
    </div>
  );
}
