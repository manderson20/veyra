// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { parseDomains, ROLES } from "@/components/integrations/ProviderDialog";
import { Button, Callout, Card, Icon, LoadingState, PageHeader, SelectField, Stepper, Switch, TextField, useToast, type StepDef } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { IdentityProviderInput, IdentityProviderOut, JitRole, ProviderTestOut, TestSignInOut, TestSignInResult } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useOrganizationOptions } from "@/hooks/useOrganizations";
import { useSession } from "@/hooks/useSession";

type Kind = IdentityProviderInput["kind"];
type StepKey = "provider" | "console" | "credentials" | "accounts" | "test";

const STEPS: { key: StepKey; title: string }[] = [
  { key: "provider", title: "Choose a provider" },
  { key: "console", title: "Register Veyra" },
  { key: "credentials", title: "Enter the credentials" },
  { key: "accounts", title: "Who can sign in" },
  { key: "test", title: "Test and turn on" },
];

const KINDS: { value: Kind; title: string; text: string }[] = [
  { value: "google", title: "Google Workspace", text: "People sign in with their Google Workspace account." },
  { value: "microsoft", title: "Microsoft Entra ID", text: "People sign in with their Microsoft 365 work or school account." },
  { value: "oidc", title: "Another provider", text: "Any OpenID Connect provider, such as Okta, Keycloak or Authentik." },
];

const CREDENTIAL_FIELDS = ["name", "issuer", "client_id", "client_secret", "allowed_domains"];

const LABEL: Record<Kind, string> = { google: "Google", microsoft: "Microsoft", oidc: "the provider" };

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer">{children} <Icon name="external" size={12} /></a>;
}

function Redirect({ uri }: { uri: string | undefined }) {
  if (!uri) return <span className="subtle">loading…</span>;
  return <span className="row" style={{ gap: 6, display: "inline-flex" }}><span className="mono" style={{ wordBreak: "break-all" }}>{uri}</span><CopyButton text={uri} /></span>;
}

function ConsoleSteps({ kind, uri }: { kind: Kind; uri: string | undefined }) {
  if (kind === "google") {
    return (
      <>
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li>Open the <Ext href="https://console.cloud.google.com/">Google Cloud console</Ext> signed in with a Workspace administrator account, and choose or create a project for Veyra (for example <em>Veyra sign-in</em>).</li>
          <li>Open <Ext href="https://console.cloud.google.com/auth/branding">Google Auth Platform → Branding</Ext> (older consoles: <strong>APIs &amp; Services → OAuth consent screen</strong>). If asked to get started, enter <em>Veyra</em> as the app name and a support e-mail address. Under <strong>Audience</strong>, choose <strong>Internal</strong> so only accounts in your Workspace can use it.</li>
          <li>Open <Ext href="https://console.cloud.google.com/auth/clients">Clients</Ext> and choose <strong>Create client</strong>. Application type: <strong>Web application</strong>; name: <em>Veyra</em>.</li>
          <li>Under <strong>Authorized redirect URIs</strong>, choose <strong>Add URI</strong> and paste exactly:<br /><Redirect uri={uri} /></li>
          <li>Choose <strong>Create</strong>. Copy the <strong>Client ID</strong> and the <strong>Client secret</strong> now: Google shows the secret only once (you can also download the JSON file).</li>
        </ol>
        <Callout tone="info" title="No extra scopes are needed">Veyra asks only for the person&apos;s name and e-mail address (openid, email, profile), which need no verification by Google.</Callout>
        <Callout tone="neutral" title="Later, for the Companion on managed Chromebooks">To let the Companion sign in without a click, mark this client as <strong>Trusted</strong> in the Google Admin console (Security → Access and data control → API controls → Manage third-party app access) and choose it in the sign-in step of System → <a href="/system/companion/">Companion rollout</a>.</Callout>
      </>
    );
  }
  if (kind === "microsoft") {
    return (
      <>
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li>Open the <Ext href="https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade">Microsoft Entra admin center → App registrations</Ext> as an Application Administrator (or Global Administrator) and choose <strong>New registration</strong>.</li>
          <li>Name: <em>Veyra</em>. Supported account types: <strong>Accounts in this organizational directory only (Single tenant)</strong>.</li>
          <li>Redirect URI: choose the platform <strong>Web</strong> and paste exactly:<br /><Redirect uri={uri} /><br />Then choose <strong>Register</strong>.</li>
          <li>On the app&apos;s <strong>Overview</strong> page, note the <strong>Application (client) ID</strong> and the <strong>Directory (tenant) ID</strong>.</li>
          <li>Open <strong>Certificates &amp; secrets → Client secrets → New client secret</strong>, pick an expiry and choose <strong>Add</strong>. Copy the <strong>Value</strong> column right away — not the <em>Secret ID</em>. Microsoft shows the value only once.</li>
          <li>Nothing is needed under <strong>API permissions</strong>: the default <em>Microsoft Graph User.Read</em> is enough. If your tenant does not let users consent to apps, choose <strong>Grant admin consent</strong> there.</li>
        </ol>
        <Callout tone="warn" title="Client secrets expire">Sign-in stops working when the secret expires (24 months at most). Put a reminder in your calendar to create a new one and paste it into Veyra (Edit on the Sign-in page).</Callout>
        <Callout tone="neutral" title="Optional: only some people">To limit who can sign in, open <strong>Enterprise applications → Veyra → Properties</strong>, set <strong>Assignment required</strong> to Yes, and add users or groups under <strong>Users and groups</strong>.</Callout>
      </>
    );
  }
  return (
    <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
      <li>In your provider&apos;s administration, create an OpenID Connect application of the <strong>confidential</strong> (web, with a client secret) kind, using the <strong>authorization code</strong> flow.</li>
      <li>Add this redirect (callback) address exactly:<br /><Redirect uri={uri} /></li>
      <li>Allow the scopes <span className="mono">openid email profile</span>. The ID token must carry <span className="mono">email</span> and <span className="mono">email_verified</span>.</li>
      <li>Note the <strong>issuer</strong> address (Veyra reads <span className="mono">/.well-known/openid-configuration</span> below it), the <strong>client ID</strong> and the <strong>client secret</strong>.</li>
    </ol>
  );
}

const HINTS: Record<string, string> = {
  token_exchange: "The provider refused Veyra's client ID or secret. Check both — for Microsoft, the secret is the Value column, not the Secret ID. Use Edit on the Sign-in page to enter a new secret.",
  bad_token: "The answer was meant for another application or directory. Check the client ID (and for Microsoft, the tenant ID).",
  bad_signature: "The provider's signature did not check out. Use “Check the connection” again; if it keeps failing, check the issuer address.",
  no_email: "The provider did not send an e-mail address. Make sure the account has one and that the email scope is allowed.",
  unverified_email: "The provider has not verified this account's e-mail address.",
  browser_mismatch: "Start the test from this page, in this browser.",
  expired_request: "The test took longer than 10 minutes or was already used. Start it again.",
  access_denied: "The sign-in was cancelled, or this account may not use the app (Google: an account outside your Workspace with an Internal app; Microsoft: assignment required and the account not assigned).",
  provider_error: "If the error mentions the redirect address (redirect_uri_mismatch, AADSTS50011), copy the redirect address again exactly. AADSTS7000215 means the secret is wrong.",
  no_account: "Add this person under Users, or turn on account creation (Edit on the Sign-in page), then test again.",
  recovery_admin: "Test with another account: the recovery administrator never uses single sign-on.",
  inactive: "Enable the account under Users, or test with another account.",
};

function TestResult({ result, domains }: { result: Record<string, unknown>; domains: string[] }) {
  const ok = result.ok === true;
  const outcome = String(result.outcome ?? "");
  const reason = typeof result.reason === "string" ? result.reason : "";
  const passed = ok && outcome !== "refused";
  const tone = passed ? "ok" : ok ? "warn" : "danger";
  const title = passed ? "Single sign-on works" : ok ? `The provider works, but ${String(result.email ?? "this account")} would not get in` : "The test sign-in failed";
  const hint = reason === "domain_not_allowed" ? `Test with an account in ${domains.join(", ")}, or add this account's domain to the allowed domains.` : HINTS[reason];
  return (
    <Callout tone={tone} title={title}>
      <p style={{ margin: 0 }}>{String(result.message ?? "")}</p>
      {typeof result.detail === "string" && result.detail ? <p className="mono" style={{ margin: "6px 0 0", wordBreak: "break-word" }}>{result.detail}</p> : null}
      {hint ? <p style={{ margin: "6px 0 0" }}>{hint}</p> : null}
      {passed ? <p className="subtle" style={{ margin: "6px 0 0" }}>Nothing was changed: no one was signed in, linked or created.</p> : null}
    </Callout>
  );
}

function bodyOf(p: IdentityProviderOut, enabled: boolean): IdentityProviderInput {
  return {
    kind: p.kind, name: p.name, issuer: p.kind === "google" ? null : p.issuer, client_id: p.client_id, client_secret: null,
    allowed_domains: p.allowed_domains, organization_id: p.organization_id, create_accounts: p.create_accounts, default_role_key: p.default_role_key, enabled,
  };
}

function TestStep({ provider, testId, onChanged }: { provider: IdentityProviderOut; testId: string | null; onChanged: (p: IdentityProviderOut) => void }) {
  const toast = useToast();
  const router = useRouter();
  const [check, setCheck] = useState<ProviderTestOut | null>(null);
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [busy, setBusy] = useState(false);
  const result = useApiData<TestSignInResult>(testId ? `/identity-providers/${provider.id}/test-sign-in/${testId}` : null);
  const passed = result.data?.status === "done" && result.data.result?.ok === true && result.data.result.outcome !== "refused";

  const checkConnection = (id: string) =>
    api.post<ProviderTestOut>(`/identity-providers/${id}/test`)
      .catch((err: unknown): ProviderTestOut => ({ ok: false, message: errorMessage(err), authorization_endpoint: null, keys: 0 }));
  const runCheck = async () => {
    setChecking(true);
    setCheck(await checkConnection(provider.id));
    setChecking(false);
  };
  useEffect(() => {
    let live = true;
    void checkConnection(provider.id).then((r) => { if (live) setCheck(r); });
    return () => { live = false; };
  }, [provider.id]);

  const tryIt = async () => {
    setStarting(true);
    try {
      const r = await api.post<TestSignInOut>(`/identity-providers/${provider.id}/test-sign-in`);
      window.location.assign(r.url);
    } catch (err) {
      toast.error("Could not start the test", errorMessage(err));
      setStarting(false);
    }
  };
  const turnOn = async () => {
    setBusy(true);
    try {
      const saved = await api.put<IdentityProviderOut>(`/identity-providers/${provider.id}`, bodyOf(provider, true));
      onChanged(saved);
      toast.success(`"${saved.name}" is on`, `The sign-in page now shows "Sign in with ${saved.name}".`);
      router.push("/system/sign-in/");
    } catch (err) {
      toast.error("Could not turn it on", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div>
        <h2 className="card__title">Test {provider.name}</h2>
        <p className="muted">A test sign-in goes through {LABEL[provider.kind]} exactly like a real one and shows which Veyra account it would use. It signs no one in and changes nothing, so you can test with any account{provider.enabled ? "" : ", before anyone sees the button"}.</p>
      </div>
      <div className="stack stack--sm">
        <strong>1. Check the connection</strong>
        {checking || !check ? <span className="subtle">Contacting {LABEL[provider.kind]}…</span> : check.ok
          ? <Callout tone="ok" title="Veyra can reach the provider">{check.message} {check.keys} signing key(s).</Callout>
          : <Callout tone="danger" title="Veyra cannot reach the provider">{check.message} {provider.kind === "microsoft" ? "Check the directory (tenant) ID." : provider.kind === "oidc" ? "Check the issuer address." : "Check this server's internet access."}</Callout>}
        {check && !check.ok ? <div><Button size="sm" icon="refresh" loading={checking} onClick={() => void runCheck()}>Check again</Button></div> : null}
      </div>
      <div className="stack stack--sm">
        <strong>2. Try signing in</strong>
        <p className="muted" style={{ margin: 0 }}>You go to {LABEL[provider.kind]}, sign in, and come back to this page with the result. Use an account in {provider.allowed_domains.join(", ")}.</p>
        {result.loading ? <span className="subtle">Loading the result…</span> : null}
        {result.data?.status === "done" && result.data.result ? <TestResult result={result.data.result} domains={provider.allowed_domains} /> : null}
        {result.data?.status === "expired" ? <Callout tone="warn" title="This test did not finish">It was cancelled or took longer than 10 minutes. Try again.</Callout> : null}
        {result.error ? <Callout tone="danger">{errorMessage(result.error)}</Callout> : null}
        <div><Button variant={passed ? "secondary" : "primary"} icon="key" loading={starting} disabled={check?.ok === false} onClick={() => void tryIt()}>{testId ? "Test again" : `Sign in with ${provider.name} to test`}</Button></div>
      </div>
      <div className="stack stack--sm">
        <strong>3. Turn it on</strong>
        {provider.enabled ? (
          <Callout tone="ok">The sign-in page shows &quot;Sign in with {provider.name}&quot;.</Callout>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{provider.name} is saved but turned off: the sign-in page does not show its button yet.</p>
        )}
        <div className="row" style={{ gap: 8 }}>
          {!provider.enabled ? <Button variant={passed ? "primary" : "secondary"} icon="check" loading={busy} onClick={() => void turnOn()}>{passed ? "Turn on the sign-in button" : "Turn on without a passing test"}</Button> : null}
          <Button onClick={() => router.push("/system/sign-in/")}>{provider.enabled ? "Done" : "Finish later"}</Button>
        </div>
      </div>
    </>
  );
}

function Wizard() {
  const params = useSearchParams();
  const router = useRouter();
  const { session, can } = useSession();
  const errors = useFormErrors();
  const providerParam = params.get("provider");
  const testId = params.get("test");
  const existing = useApiData<IdentityProviderOut>(providerParam ? `/identity-providers/${providerParam}` : null);
  const redirect = useApiData<{ redirect_uri: string }>("/identity-providers/redirect-uri");
  const { organizations } = useOrganizationOptions(true);
  const [step, setStep] = useState<StepKey>(providerParam ? "test" : "provider");
  const [saved, setSaved] = useState<IdentityProviderOut | null>(null);
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
  const [busy, setBusy] = useState(false);

  const provider = saved ?? existing.data ?? null;
  const effectiveOrg = org || session?.user.home_organization_id || (organizations.length === 1 ? organizations[0]!.id : "");
  const effectiveIssuer = kind === "google" ? null : kind === "microsoft" ? (tenant.trim() ? `https://login.microsoftonline.com/${tenant.trim()}/v2.0` : "") : issuer.trim();
  const index = STEPS.findIndex((s) => s.key === step);
  const done = new Set<string>(STEPS.slice(0, index).map((s) => s.key));
  const steps: StepDef[] = STEPS.map((s) => ({ key: s.key, title: s.title, available: true }));

  if (!can("sso.write")) return <Callout tone="warn">Setting up single sign-on needs the permission to change sign-in providers.</Callout>;
  if (providerParam && existing.loading) return <LoadingState />;
  if (providerParam && existing.error) return <Callout tone="danger" title="Provider not found">{errorMessage(existing.error)}</Callout>;

  const chooseKind = (k: Kind) => {
    setKind(k);
    setName(k === "google" ? "Google" : k === "microsoft" ? "Microsoft" : "");
  };
  const credentialsReady = name.trim() && clientId.trim() && (saved || secret) && parseDomains(domains).length > 0 && effectiveIssuer !== "";

  const save = async () => {
    setBusy(true);
    errors.clear();
    const body: IdentityProviderInput = {
      kind, name: name.trim(), issuer: effectiveIssuer, client_id: clientId.trim(), client_secret: secret || null,
      allowed_domains: parseDomains(domains), organization_id: effectiveOrg, create_accounts: create, default_role_key: role, enabled: false,
    };
    try {
      const p = saved
        ? await api.put<IdentityProviderOut>(`/identity-providers/${saved.id}`, body)
        : await api.post<IdentityProviderOut>("/identity-providers", body);
      setSaved(p);
      setSecret("");
      router.replace(`/system/sign-in/setup/?provider=${p.id}`);
      setStep("test");
    } catch (err) {
      errors.set(err);
      // Field problems are all on the credentials step.
      const fields = err instanceof ApiError ? Object.keys(err.fieldErrors()) : [];
      if (fields.some((f) => CREDENTIAL_FIELDS.includes(f))) setStep("credentials");
    } finally {
      setBusy(false);
    }
  };

  const next = (e: FormEvent) => {
    e.preventDefault();
    if (step === "accounts") void save();
    else setStep(STEPS[index + 1]!.key);
  };
  const back = index > 0 && step !== "test" ? () => setStep(STEPS[index - 1]!.key) : null;

  return (
    <div className="wizard">
      <Stepper steps={steps} current={step} completed={done} />
      <Card>
        {step === "test" && provider ? (
          <div className="stack"><TestStep provider={provider} testId={testId} onChanged={setSaved} /></div>
        ) : (
          <form className="stack" onSubmit={next}>
            {step === "provider" ? (
              <>
                <div>
                  <h2 className="card__title">Which accounts do people already have?</h2>
                  <p className="muted">People sign in with the account their school or company already gives them. Veyra checks the provider&apos;s signature on every sign-in and keeps no access to the account.</p>
                </div>
                <div className="choice-tiles" role="radiogroup" aria-label="Provider">
                  {KINDS.map((k) => (
                    <button key={k.value} type="button" role="radio" aria-checked={kind === k.value} className="choice-tile" onClick={() => chooseKind(k.value)}>
                      <strong>{k.title}</strong>
                      <span className="subtle">{k.text}</span>
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            {step === "console" ? (
              <>
                <div>
                  <h2 className="card__title">Register Veyra with {KINDS.find((k) => k.value === kind)!.title}</h2>
                  <p className="muted">Do this in another tab and keep this page open; the next step asks for what you copy there.</p>
                </div>
                <ConsoleSteps kind={kind} uri={redirect.data?.redirect_uri} />
              </>
            ) : null}
            {step === "credentials" ? (
              <>
                <div>
                  <h2 className="card__title">Enter what you copied</h2>
                  <p className="muted">The secret is stored encrypted and never shown again.</p>
                </div>
                {kind === "microsoft" ? (
                  <TextField label="Directory (tenant) ID" required value={tenant} error={errors.fields.issuer} placeholder="00000000-0000-0000-0000-000000000000" spellCheck={false} help="From the app registration's Overview page." onChange={(e) => setTenant(e.target.value)} />
                ) : kind === "oidc" ? (
                  <TextField label="Issuer" required type="url" value={issuer} error={errors.fields.issuer} placeholder="https://id.example.org" help="Veyra reads /.well-known/openid-configuration below this address." onChange={(e) => setIssuer(e.target.value)} />
                ) : null}
                <div className="form-grid">
                  <TextField label={kind === "microsoft" ? "Application (client) ID" : "Client ID"} required value={clientId} error={errors.fields.client_id} spellCheck={false} onChange={(e) => setClientId(e.target.value)} />
                  <TextField label={saved ? "New client secret (blank keeps the saved one)" : kind === "microsoft" ? "Client secret value" : "Client secret"} required={!saved} type="password" autoComplete="off" value={secret} error={errors.fields.client_secret}
                    help={kind === "microsoft" ? "The Value column, not the Secret ID." : undefined} onChange={(e) => setSecret(e.target.value)} />
                </div>
                <TextField label="Allowed e-mail domains" required value={domains} error={errors.fields.allowed_domains} placeholder="example.org" help={kind === "google" ? "Accounts outside these Google Workspace domains are refused, including personal Gmail accounts. Separate several with commas." : "Accounts with other addresses are refused. Separate several with commas."} onChange={(e) => setDomains(e.target.value)} />
                <TextField label="Button name" required value={name} error={errors.fields.name} help={`Shown as "Sign in with ${name || "…"}".`} onChange={(e) => setName(e.target.value)} />
                {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
              </>
            ) : null}
            {step === "accounts" ? (
              <>
                <div>
                  <h2 className="card__title">Who can sign in</h2>
                  <p className="muted">People who already have a Veyra account with the same e-mail address are linked to it the first time they sign in.</p>
                </div>
                {organizations.length > 1 ? (
                  <SelectField label="Organization for new accounts" value={effectiveOrg} placeholder="Choose an organization" options={organizations.map((o) => ({ value: o.id, label: o.name }))} onChange={(e) => setOrg(e.target.value)} />
                ) : null}
                <Switch label="Create accounts on first sign-in" description="Off: only people who already have a Veyra account can sign in. On: anyone in the allowed domains gets an account the first time." checked={create} onChange={(e) => setCreate(e.target.checked)} />
                {create ? <SelectField label="Role for new accounts" value={role} options={ROLES} onChange={(e) => setRole(e.target.value as JitRole)} /> : null}
                <Callout tone="info">Saving keeps the provider turned off: its button appears on the sign-in page only after you test it and turn it on in the next step.</Callout>
                {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
              </>
            ) : null}
            <div className="row" style={{ gap: 8, justifyContent: "space-between" }}>
              {back ? <Button onClick={back} disabled={busy}>Back</Button> : <Button onClick={() => router.push("/system/sign-in/")}>Cancel</Button>}
              <Button variant="primary" type="submit" loading={busy} disabled={(step === "credentials" && !credentialsReady) || (step === "accounts" && (!credentialsReady || !effectiveOrg))}>
                {step === "accounts" ? "Save and test" : "Continue"}
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}

export default function SsoSetupPage() {
  return (
    <div className="stack">
      <PageHeader title="Set up single sign-on" description="A step-by-step guide to letting people sign in with their Google Workspace, Microsoft or other account." back={{ href: "/system/sign-in/", label: "Sign-in" }} />
      <Suspense fallback={<LoadingState />}><Wizard /></Suspense>
    </div>
  );
}
