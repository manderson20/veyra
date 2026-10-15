// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type FormEvent } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Button, Callout, Dialog, SelectField, Switch, TextField, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import type { IdentityProviderInput, IdentityProviderOut, JitRole } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOnChange } from "@/hooks/useOnChange";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

type Kind = IdentityProviderInput["kind"];

const KINDS: { value: Kind; label: string }[] = [
  { value: "google", label: "Google Workspace" },
  { value: "microsoft", label: "Microsoft Entra ID" },
  { value: "oidc", label: "Other OpenID Connect provider" },
];

export const ROLES: { value: JitRole; label: string }[] = [
  { value: "standard_user", label: "Standard User" },
  { value: "read_only", label: "Read-Only User" },
  { value: "technician", label: "Technician" },
  { value: "site_admin", label: "Site Administrator" },
  { value: "org_admin", label: "Organization Administrator" },
];

/** Split "a.org, b.org" or one per line into a clean list. */
export function parseDomains(text: string): string[] {
  return [...new Set(text.split(/[\s,;]+/).map((d) => d.trim().toLowerCase().replace(/^@/, "")).filter(Boolean))];
}

function tenantOf(issuer: string): string {
  const m = /login\.microsoftonline\.com\/([^/]+)\/v2\.0/.exec(issuer);
  return m?.[1] ?? "";
}

/** Add or edit an identity provider (docs/INTEGRATIONS.md §1.1). */
export function ProviderDialog({ open, onClose, provider, onSaved }: { open: boolean; onClose: () => void; provider?: IdentityProviderOut; onSaved: (p: IdentityProviderOut) => void }) {
  const toast = useToast();
  const { session } = useSession();
  const errors = useFormErrors();
  const { organizations } = useOrganizationOptions(open);
  const redirect = useApiData<{ redirect_uri: string }>(open ? "/identity-providers/redirect-uri" : null);
  const [kind, setKind] = useState<Kind>("google");
  const [name, setName] = useState("Google");
  const [tenant, setTenant] = useState("");
  const [issuer, setIssuer] = useState("");
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [domains, setDomains] = useState("");
  const [org, setOrg] = useState("");
  const [create, setCreate] = useState(false);
  const [role, setRole] = useState<JitRole>("standard_user");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const effectiveOrg = org || (organizations.length === 1 ? organizations[0]!.id : "");

  useOnChange(open, () => {
    if (!open) return;
    setKind(provider?.kind ?? "google");
    setName(provider?.name ?? "Google");
    setTenant(provider?.kind === "microsoft" ? tenantOf(provider.issuer) : "");
    setIssuer(provider?.kind === "oidc" ? provider.issuer : "");
    setClientId(provider?.client_id ?? "");
    setSecret("");
    setDomains((provider?.allowed_domains ?? []).join(", "));
    setOrg(provider?.organization_id ?? session?.user.home_organization_id ?? "");
    setCreate(provider?.create_accounts ?? false);
    setRole(provider?.default_role_key ?? "standard_user");
    setEnabled(provider?.enabled ?? true);
    errors.clear();
  });

  const changeKind = (k: Kind) => {
    setKind(k);
    if (!provider) setName(k === "google" ? "Google" : k === "microsoft" ? "Microsoft" : "");
  };

  const effectiveIssuer = kind === "google" ? null : kind === "microsoft" ? (tenant.trim() ? `https://login.microsoftonline.com/${tenant.trim()}/v2.0` : "") : issuer.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const body: IdentityProviderInput = {
        kind,
        name: name.trim(),
        issuer: effectiveIssuer,
        client_id: clientId.trim(),
        client_secret: secret || null,
        allowed_domains: parseDomains(domains),
        organization_id: effectiveOrg,
        create_accounts: create,
        default_role_key: role,
        enabled,
      };
      const saved = provider
        ? await api.put<IdentityProviderOut>(`/identity-providers/${provider.id}`, body)
        : await api.post<IdentityProviderOut>("/identity-providers", body);
      toast.success(provider ? "Provider saved" : `"${saved.name}" added`, provider ? "" : "Copy its redirect address into the provider's console, then test it.");
      onClose();
      onSaved(saved);
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };

  const ready = name.trim() && clientId.trim() && (provider || secret) && parseDomains(domains).length > 0 && effectiveOrg && effectiveIssuer !== "";

  return (
    <Dialog open={open} onClose={onClose} busy={busy} size="lg" title={provider ? `Edit "${provider.name}"` : "Add a sign-in provider"}
      description="People sign in with the account their school or company already gives them. Veyra checks the provider's signature on every sign-in and keeps no access to the account."
      footer={<><Button onClick={onClose} disabled={busy}>Cancel</Button><Button variant="primary" type="submit" form="provider-form" loading={busy} disabled={!ready}>{provider ? "Save changes" : "Add provider"}</Button></>}>
      <form id="provider-form" className="stack stack--sm" onSubmit={submit}>
        {redirect.data ? (
          <Callout tone="info" title="Redirect address for the provider's console">
            <span className="row" style={{ gap: 6 }}><span className="mono" style={{ wordBreak: "break-all" }}>{redirect.data.redirect_uri}</span><CopyButton text={redirect.data.redirect_uri} /></span>
          </Callout>
        ) : null}
        <div className="form-grid">
          <SelectField label="Provider" value={kind} options={KINDS} onChange={(e) => changeKind(e.target.value as Kind)} />
          <TextField label="Button name" required value={name} error={errors.fields.name} help={`Shown as "Sign in with ${name || "…"}".`} onChange={(e) => setName(e.target.value)} />
        </div>
        {kind === "microsoft" ? (
          <TextField label="Directory (tenant) ID" required value={tenant} error={errors.fields.issuer} placeholder="00000000-0000-0000-0000-000000000000" help="From the app registration's Overview page in the Entra admin center." onChange={(e) => setTenant(e.target.value)} />
        ) : kind === "oidc" ? (
          <TextField label="Issuer" required type="url" value={issuer} error={errors.fields.issuer} placeholder="https://id.example.org" help="Veyra reads /.well-known/openid-configuration below this address." onChange={(e) => setIssuer(e.target.value)} />
        ) : null}
        <div className="form-grid">
          <TextField label="Client ID" required value={clientId} error={errors.fields.client_id} spellCheck={false} onChange={(e) => setClientId(e.target.value)} />
          <TextField label={provider ? "New client secret (blank keeps the current one)" : "Client secret"} required={!provider} type="password" autoComplete="off" value={secret} error={errors.fields.client_secret} help="Stored encrypted; never shown again." onChange={(e) => setSecret(e.target.value)} />
        </div>
        <TextField label="Allowed e-mail domains" required value={domains} error={errors.fields.allowed_domains} placeholder="example.org" help={kind === "google" ? "Accounts outside these Google Workspace domains are refused, including personal Gmail accounts." : "Accounts with other addresses are refused."} onChange={(e) => setDomains(e.target.value)} />
        {organizations.length > 1 ? (
          <SelectField label="Organization for new accounts" value={effectiveOrg} placeholder="Choose an organization" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
        ) : null}
        <Switch label="Create accounts on first sign-in" description="Off: only people who already have a Veyra account with the same address can sign in (they are linked on first use)." checked={create} onChange={(e) => setCreate(e.target.checked)} />
        {create ? <SelectField label="Role for new accounts" value={role} options={ROLES} onChange={(e) => setRole(e.target.value as JitRole)} /> : null}
        <Switch label="Enabled" description="A disabled provider has no button on the sign-in page." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      </form>
    </Dialog>
  );
}
