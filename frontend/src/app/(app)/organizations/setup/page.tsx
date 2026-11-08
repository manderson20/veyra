// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent, type ReactNode } from "react";
import {
  Badge,
  Button,
  Callout,
  Card,
  ErrorState,
  LoadingState,
  PageHeader,
  TextField,
  buttonClass,
  useToast,
} from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Onboarding, OnboardingCheck, OnboardingStep, Organization, User } from "@/lib/types";
import { LimitsCard } from "@/components/organizations/LimitsCard";
import { NumbersCard } from "@/components/organizations/NumbersCard";
import { ProvisioningCredentialCard } from "@/components/organizations/ProvisioningCredentialCard";
import { useApiData } from "@/hooks/useApiData";
import { useFormErrors } from "@/hooks/useFormErrors";
import { useSession } from "@/hooks/useSession";

/** Onboarding (docs/MULTI_TENANCY_MSP.md §10): each step saves on its own and
 * shows done or to do, so the page can be left and resumed. */
function Setup() {
  const id = useSearchParams().get("id");
  const { can } = useSession();
  const org = useApiData<Organization>(id ? `/organizations/${encodeURIComponent(id)}` : null);
  const status = useApiData<Onboarding>(id ? `/organizations/${encodeURIComponent(id)}/onboarding` : null);
  const [open, setOpen] = useState<string | null>(null);

  if (!id) return <ErrorState title="No organization selected" error={{ message: "Open an organization from the list." }} />;
  if (org.error) return <ErrorState title="Could not load organization" error={org.error} onRetry={org.reload} />;
  if (status.error) return <ErrorState title="Could not load the setup" error={status.error} onRetry={status.reload} />;
  if (!org.data || !status.data) return <LoadingState />;
  const o = org.data;
  const editable = can("organizations.write");
  const steps = status.data.steps;
  const first = steps.find((s) => !s.done && !s.optional)?.key ?? null;
  const current = open ?? first;
  const changed = () => { status.reload(); org.reload(); };

  const body = (s: OnboardingStep): ReactNode => {
    switch (s.key) {
      case "organization":
        return (
          <div className="stack stack--sm">
            <p className="subtle">Main number <span className="mono">{o.main_number ?? "none"}</span>, emergency number <span className="mono">{o.emergency_caller_id_number ?? "none"}</span>. Change them, the name or the time zone on the <Link href={`/organizations/view/?id=${o.id}`}>organization&apos;s page</Link>.</p>
            {can("routing.read") ? <NumbersCard organizationId={o.id} editable={editable} /> : null}
          </div>
        );
      case "trunk":
        return (
          <div className="stack stack--sm">
            <p className="subtle">Outside calls use the shared outbound routes (marked &quot;All organizations&quot;), or a trunk of its own: create the trunk, set its organization to {o.name}, and give it an outbound route. A dedicated trunk may also route its &quot;any&quot; catch-all to the organization.</p>
            <div className="row">
              {can("trunks.read") ? <Link className={buttonClass("secondary", "sm")} href="/trunks/">Trunks</Link> : null}
              {can("routing.read") ? <Link className={buttonClass("secondary", "sm")} href="/routing/outbound/">Outbound routes</Link> : null}
            </div>
          </div>
        );
      case "administrator":
        return can("users.write") ? <FirstAdmin org={o} onDone={changed} /> : <p className="subtle">Ask a user administrator to add one.</p>;
      case "phones":
        return can("devices.read") ? <ProvisioningCredentialCard organizationId={o.id} editable={can("devices.write") && editable} bootstrapIncludesCredential={o.bootstrap_includes_credential ?? false} /> : null;
      case "emergency":
        return (
          <div className="stack stack--sm">
            <p className="subtle">Add a site with its civic address and an ELIN, one of the organization&apos;s numbers registered at that address, then validate it on the emergency page.</p>
            <div className="row">
              {can("sites.read") ? <Link className={buttonClass("secondary", "sm")} href="/sites/">Sites</Link> : null}
              <Link className={buttonClass("secondary", "sm")} href="/system/emergency/">Emergency readiness</Link>
            </div>
          </div>
        );
      case "limits":
        return <LimitsCard organizationId={o.id} editable={editable} />;
      default:
        return null;
    }
  };

  return (
    <div className="stack">
      <PageHeader
        back={{ href: `/organizations/view/?id=${o.id}`, label: o.name }}
        title={`Set up ${o.name}`}
        description={status.data.left.length ? `Still to do: ${status.data.left.join(", ")}.` : "Every required step is done. Run the check to finish."}
        actions={<Button icon="refresh" onClick={changed}>Refresh</Button>}
      />
      {!status.data.multi_tenancy ? (
        <Callout tone="info">Multi-tenancy is off. A second organization needs it: turn it on under <Link href="/settings/">System → Settings</Link>.</Callout>
      ) : null}
      <ol className="stack stack--sm" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {steps.map((s, i) => (
          <li key={s.key}>
            <Card
              title={<span className="row"><span className="subtle">{i + 1}.</span> {s.title}</span>}
              subtitle={s.detail}
              actions={<>
                <Badge tone={s.done ? "ok" : s.optional ? "neutral" : "warn"}>{s.done ? "Done" : s.optional ? "Optional" : "To do"}</Badge>
                <Button size="sm" variant="ghost" aria-expanded={current === s.key} onClick={() => setOpen(current === s.key ? "" : s.key)}>{current === s.key ? "Close" : "Open"}</Button>
              </>}
            >
              {current === s.key ? body(s) : null}
            </Card>
          </li>
        ))}
        <li>
          <CheckStep orgId={o.id} index={steps.length + 1} allowed={can("system.settings.read")} />
        </li>
      </ol>
    </div>
  );
}

/** Step 3: the organization's first administrator, with a temporary password. */
function FirstAdmin({ org, onDone }: { org: Organization; onDone: () => void }) {
  const toast = useToast();
  const errors = useFormErrors();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    errors.clear();
    try {
      const user = await api.post<User>("/users", { email: email.trim(), display_name: name.trim(), password, home_organization_id: org.id, require_password_change: true });
      await api.post(`/users/${user.id}/roles`, { role_key: "org_admin", scope_type: "organization", organization_id: org.id });
      toast.success("Administrator added", `${user.email} chooses a new password at the first sign-in.`);
      setEmail(""); setName(""); setPassword("");
      onDone();
    } catch (err) {
      errors.set(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="stack stack--sm" onSubmit={submit}>
      <p className="subtle">An Organization Administrator of {org.name} only. They manage its extensions, phones and users, and apply its changes.</p>
      <TextField label="Email" type="email" required value={email} error={errors.fields.email} onChange={(e) => setEmail(e.target.value)} />
      <TextField label="Name" required value={name} error={errors.fields.display_name} onChange={(e) => setName(e.target.value)} />
      <TextField label="Temporary password" type="password" required autoComplete="new-password" value={password} error={errors.fields.password}
        help="At least 12 characters. Share it securely; they choose their own at the first sign-in." onChange={(e) => setPassword(e.target.value)} />
      {errors.message ? <Callout tone="danger">{errors.message}</Callout> : null}
      <div className="form-actions"><Button variant="primary" type="submit" loading={busy}>Add administrator</Button></div>
    </form>
  );
}

/** Step 7: the isolation check and the caller ID and 911 rules, with this organization in. */
function CheckStep({ orgId, index, allowed }: { orgId: string; index: number; allowed: boolean }) {
  const [result, setResult] = useState<OnboardingCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<OnboardingCheck>(`/organizations/${orgId}/onboarding/check`));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      title={<span className="row"><span className="subtle">{index}.</span> Check</span>}
      subtitle="Generates the configuration with this organization and a copy of it, and checks that no organization can reach another's phones, numbers, voicemail or queues."
      actions={<>
        {result ? <Badge tone={result.ok ? "ok" : "warn"}>{result.ok ? "Ready" : "Not yet"}</Badge> : null}
        {allowed ? <Button size="sm" variant="primary" loading={busy} onClick={run}>Run check</Button> : null}
      </>}
    >
      {!allowed ? <p className="subtle">A platform administrator runs the check.</p> : null}
      {error ? <Callout tone="danger">{error}</Callout> : null}
      {result ? (
        <div className="stack stack--sm">
          <ul className="stack stack--xs" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {result.checks.map((c) => (
              <li key={c.name} className="row" style={{ alignItems: "baseline" }}>
                <Badge tone={!c.ok ? "danger" : c.warning ? "warn" : "ok"}>{!c.ok ? "Fails" : c.warning ? "Review" : "OK"}</Badge>
                <span>{c.detail}</span>
              </li>
            ))}
          </ul>
          {result.left.length ? (
            <Callout tone="warn" title="Left to do"><ul>{result.left.map((l) => <li key={l}>{l}</li>)}</ul></Callout>
          ) : (
            <Callout tone="ok">The organization is set up. Apply the pending changes to put it live.</Callout>
          )}
        </div>
      ) : null}
    </Card>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><Setup /></Suspense>;
}
