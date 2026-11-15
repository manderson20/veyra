// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { ExtensionListPicker, type ListedExtension } from "@/components/common/ExtensionListPicker";
import { Button, Card, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Extension, FeatureCodes, Page } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";

/** Pickup In-call (Grandstream, issue #392): the extensions that may take
 * over this phone's answered calls with the feature code. */
export function PickupIncallCard({ extension, editable, onSaved }: {
  extension: Extension;
  editable: boolean;
  onSaved: () => void;
}) {
  const toast = useToast();
  const codes = useApiData<FeatureCodes>("/telephony/feature-codes");
  const feature = codes.data?.codes.find((c) => c.key === "pickup_incall");
  const code = feature?.enabled ? feature.code : null;
  const ids = extension.pickup_incall_ids ?? [];
  const known = useApiData<Page<Extension>>(ids.length ? "/extensions" : null, { organization_id: extension.organization_id, limit: 200 });
  const stored: ListedExtension[] = ids.map((id) => {
    const e = known.data?.items.find((x) => x.id === id);
    return { id, number: e?.number ?? "…", name: e?.display_name ?? "" };
  });
  const storedKey = ids.join(",") + "|" + (known.data ? "1" : "0");
  const [listed, setListed] = useState<ListedExtension[]>(stored);
  const [busy, setBusy] = useState(false);
  useOnChange(storedKey, () => setListed(stored));
  const dirty = listed.map((x) => x.id).join(",") !== ids.join(",");

  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/extensions/${extension.id}`, { pickup_incall_ids: listed.map((x) => x.id) });
      toast.success("Pickup In-call saved", "Deploy changes for phones to use it.");
      onSaved();
    } catch (err) {
      toast.error("Could not save Pickup In-call", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Pickup In-call" subtitle={code
      ? `Phones listed here can take over this phone's answered call by dialling ${code}${extension.number}; this phone then drops out of the call.`
      : codes.data ? "The Pickup In-call feature code is turned off under Feature Codes." : undefined}>
      <ExtensionListPicker label="May take over this phone's calls" organizationId={extension.organization_id} value={listed}
        onChange={(next) => setListed(next.filter((x) => x.id !== extension.id))} disabled={!editable || busy}
        emptyText="Nobody: no phone can take over this phone's calls." />
      {editable ? (
        <div className="form-actions">
          <Button onClick={() => setListed(stored)} disabled={!dirty || busy}>Discard</Button>
          <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!dirty}>Save</Button>
        </div>
      ) : null}
    </Card>
  );
}
