// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Card, Switch, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { MyExtension } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

interface Prefs { portal: { missed_call_email?: boolean } }

/** Email me about missed calls (#136): one message per call to the user's
 * extension nobody answered; voicemail has its own email. */
export function MissedCallEmailCard() {
  const toast = useToast();
  const exts = useApiData<MyExtension[]>("/me/extensions");
  const prefs = useApiData<Prefs>("/me/preferences");
  const [busy, setBusy] = useState(false);
  if (!exts.data?.length || !prefs.data) return null;
  const on = Boolean(prefs.data.portal?.missed_call_email);
  const toggle = async (next: boolean) => {
    setBusy(true);
    try {
      prefs.setData(await api.put<Prefs>("/me/preferences", { portal: { missed_call_email: next } }));
      toast.success(next ? "Missed-call emails on" : "Missed-call emails off");
    } catch (err) {
      toast.error("Not changed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Missed calls">
      <Switch label="Email me about missed calls" description="One email for each call to your phone that nobody answered, with who called and when. Calls that went to voicemail send the voicemail email instead."
        checked={on} disabled={busy} onChange={(e) => toggle(e.target.checked)} />
    </Card>
  );
}
