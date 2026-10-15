// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { NumberingPlanCard } from "@/components/extensions/NumberingPlanCard";
import { PendingChanges } from "@/components/extensions/PendingChanges";
import {
  Badge,
  Button,
  Callout,
  Card,
  DataTable,
  Dialog,
  EmptyState,
  PageHeader,
  Pagination,
  SearchInput,
  SelectField,
  Switch,
  TextField,
  useToast,
  type Column,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Extension, NextNumber, Page, User } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

const LIMIT = 25;

export default function ExtensionsPage() {
  const router = useRouter();
  const { can } = useSession();
  const { organizations } = useOrganizationOptions();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [org, setOrg] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const list = useApiData<Page<Extension>>("/extensions", { q: debounced, organization_id: org || undefined, limit: LIMIT, offset });
  const manyOrgs = organizations.length > 1;
  const columns: Column<Extension>[] = [
    {
      key: "number",
      header: "Extension",
      render: (x) => (
        <span>
          <span className="table__primary mono" style={{ display: "block" }}>{x.number}</span>
          <span className="table__secondary">{x.display_name}</span>
        </span>
      ),
    },
    {
      key: "user",
      header: "Assigned to",
      render: (x) => (x.user_display_name ? <span>{x.user_display_name}<span className="table__secondary" style={{ display: "block" }}>{x.user_email}</span></span> : <span className="subtle">Shared phone</span>),
    },
    ...(manyOrgs ? [{ key: "org", header: "Organization", render: (x: Extension) => <span>{x.organization_name}</span> }] : []),
    { key: "endpoint", header: "SIP user", render: (x) => <span className="mono">{x.endpoint_name}</span> },
    {
      key: "status",
      header: "Status",
      render: (x) => (
        <span className="row">
          <Badge tone={x.is_enabled ? "ok" : "neutral"}>{x.is_enabled ? "Enabled" : "Disabled"}</Badge>
          {!x.sip_secret_set ? <Badge tone="warn" icon="alert">No secret</Badge> : null}
        </span>
      ),
    },
    {
      key: "reg",
      header: "Phone",
      render: (x) => x.registration === null ? <span className="subtle">—</span>
        : x.registration.registered ? <Badge tone="ok" icon="checkCircle">{x.registration.channels ? `On a call (${x.registration.channels})` : "Registered"}</Badge>
        : <Badge tone="neutral">Not registered</Badge>,
    },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Extensions"
        description="Numbers that phones register with. Each extension has a SIP user name and secret, and can belong to a user or be a shared phone."
        actions={can("extensions.write") ? <Button variant="primary" icon="plus" onClick={() => setCreateOpen(true)}>New extension</Button> : null}
      />
      <PendingChanges refreshKey={list.data?.total} />
      <Card flush>
        <div className="table-toolbar">
          <SearchInput value={q} onChange={setQ} placeholder="Search by number or name" label="Search extensions" />
          {manyOrgs ? (
            <SelectField label={<span className="sr-only">Organization</span>} value={org} placeholder="All organizations"
              options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setOffset(0); }} />
          ) : null}
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          rowKey={(x) => x.id}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          caption="Extensions"
          onRowClick={(x) => router.push(`/extensions/view/?id=${x.id}`)}
          rowLabel={(x) => `Open extension ${x.number}`}
          empty={<EmptyState icon="phone" title={debounced || org ? "No matching extensions" : "No extensions yet"}>{!debounced && !org && can("extensions.write") ? "Create the first extension, then deploy the configuration so phones can register." : null}</EmptyState>}
          pagination={list.data ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /> : null}
        />
      </Card>
      <NumberingPlanCard editable={can("system.settings.write")} />
      <CreateExtensionDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(x) => router.push(`/extensions/view/?id=${x.id}`)} />
    </div>
  );
}

function CreateExtensionDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (x: Extension) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const users = useApiData<Page<User>>(open ? "/users" : null, { limit: 200 });
  const [org, setOrg] = useState("");
  const [number, setNumber] = useState("");
  const [name, setName] = useState("");
  const [userId, setUserId] = useState("");
  const [cidName, setCidName] = useState("");
  const [cidNumber, setCidNumber] = useState("");
  const [emergencyCid, setEmergencyCid] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [plan, setPlan] = useState<string>("");
  const [suggesting, setSuggesting] = useState(false);
  const [busy, setBusy] = useState(false);

  const suggest = async () => {
    setSuggesting(true);
    try {
      const n = await api.get<NextNumber>("/extensions/next-number", { organization_id: org || undefined });
      setPlan(n.plan);
      if (n.number) setNumber(n.number);
      else if (n.message) toast.error("No free number", n.message);
    } catch (err) {
      toast.error("Could not suggest a number", errorMessage(err));
    } finally {
      setSuggesting(false);
    }
  };

  useOnChange(open, () => {
    if (open) {
      setOrg(session?.user.home_organization_id ?? "");
      setNumber("");
      setName("");
      setUserId("");
      setCidName("");
      setCidNumber("");
      setEnabled(true);
      errors.clear();
      void suggest();
    }
  });

  // Callers without a home organization who can see exactly one get it by default.
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");
  const orgUsers = (users.data?.items ?? []).filter((u) => u.home_organization_id === effectiveOrg && u.is_active);
  const selectedUser = orgUsers.find((u) => u.id === userId);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const created = await api.post<Extension>("/extensions", {
        organization_id: effectiveOrg,
        number: number.trim(),
        display_name: name.trim(),
        user_id: userId || null,
        caller_id_name: cidName.trim() || null,
        caller_id_number: cidNumber.trim() || null,
        emergency_caller_id_number: emergencyCid.trim() || null,
        is_enabled: enabled,
      });
      toast.success(`Extension ${created.number} created`, "Show the SIP credentials to configure the phone, then deploy the configuration.");
      onClose();
      onCreated(created);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="New extension"
      description={plan ? `Numbering plan: ${plan}.` : "A SIP secret is generated automatically."}
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="ext-create" loading={busy} disabled={!effectiveOrg || !number || !name.trim()}>Create extension</Button></>}
    >
      <form id="ext-create" className="stack stack--sm" onSubmit={submit}>
        {organizations.length > 1 ? (
          <SelectField label="Organization" required value={effectiveOrg} error={errors.fields.organization_id} placeholder="Choose an organization"
            options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => { setOrg(e.target.value); setUserId(""); }} />
        ) : null}
        <div className="form-grid">
          <TextField label="Extension number" required autoFocus inputMode="numeric" autoComplete="off" value={number} error={errors.fields.number}
            onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <span className="field__label" aria-hidden="true">&nbsp;</span>
            <Button icon="sparkle" loading={suggesting} onClick={suggest}>Suggest next free</Button>
          </div>
        </div>
        <TextField label="Name" required placeholder="e.g. Front Office or Jane Doe" value={name} error={errors.fields.display_name} onChange={(e) => setName(e.target.value)} />
        <SelectField label="Assigned user (optional)" value={userId} error={errors.fields.user_id} placeholder="Shared phone (no user)"
          help={selectedUser ? selectedUser.email : "Users of the chosen organization."}
          options={orgUsers.map((u) => ({ value: u.id, label: u.display_name }))} onChange={(e) => { setUserId(e.target.value); if (!name && e.target.value) setName(orgUsers.find((u) => u.id === e.target.value)?.display_name ?? ""); }} />
        <div className="form-grid">
          <TextField label="Caller ID name" value={cidName} error={errors.fields.caller_id_name} help="Shown to internal callers. Defaults to the name." onChange={(e) => setCidName(e.target.value)} />
          <TextField label="Caller ID number" value={cidNumber} error={errors.fields.caller_id_number} help="Defaults to the extension number." onChange={(e) => setCidNumber(e.target.value)} />
        </div>
        <TextField label="Emergency caller ID number" inputMode="tel" value={emergencyCid} error={errors.fields.emergency_caller_id_number}
          help="Presented on emergency calls (911) instead of the regular caller ID: the building's registered number. Otherwise the emergency route's number is used."
          onChange={(e) => setEmergencyCid(e.target.value)} />
        <Switch label="Enabled" description="Disabled extensions are kept but left out of the engine configuration." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
