// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AuthLayout } from "@/components/AuthLayout";
import { BrandLogo } from "@/components/Brand";
import {
  Button,
  Callout,
  Card,
  ErrorState,
  LoadingState,
  SelectField,
  Stepper,
  TextField,
  type StepDef,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { slugify } from "@/lib/format";
import { browserTimeZone, timeZones } from "@/lib/timezones";
import type { SetupStatus } from "@/lib/types";
import { useSession } from "@/hooks/useSession";

type StepKey = "token" | "administrator" | "organization" | "installation" | "numbering" | "review";
const FLOW: StepKey[] = ["token", "administrator", "organization", "installation", "numbering", "review"];

interface FormState {
  setup_token: string;
  admin_email: string;
  admin_name: string;
  admin_password: string;
  admin_password2: string;
  org_name: string;
  org_slug: string;
  slug_touched: boolean;
  installation_name: string;
  timezone: string;
  ext_length: string;
  ext_first: string;
  ext_last: string;
}

const RESERVED_DEFAULT = ["0", "9", "911", "933"];
const LENGTH_OPTIONS = [3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n} digits` }));
const RANGE_DEFAULTS: Record<string, [string, string]> = {
  "3": ["100", "799"], "4": ["1000", "7999"], "5": ["10000", "79999"], "6": ["100000", "799999"],
};

const FIELD_STEP: Record<string, StepKey> = {
  setup_token: "token",
  "administrator.email": "administrator",
  "administrator.display_name": "administrator",
  "administrator.password": "administrator",
  "organization.name": "organization",
  "organization.slug": "organization",
  "organization.timezone": "installation",
  installation_name: "installation",
  numbering: "numbering",
  "numbering.extension_length": "numbering",
  "numbering.first_extension": "numbering",
  "numbering.last_extension": "numbering",
};

export default function SetupPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [step, setStep] = useState<StepKey>("token");
  const [done, setDone] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const zones = useMemo(() => timeZones(), []);
  const [f, setF] = useState<FormState>({
    setup_token: "", admin_email: "", admin_name: "", admin_password: "", admin_password2: "",
    org_name: "", org_slug: "", slug_touched: false, installation_name: "", timezone: "UTC",
    ext_length: "4", ext_first: "1000", ext_last: "7999",
  });

  useEffect(() => {
    api
      .get<SetupStatus>("/setup/status", undefined, { noRedirect: true })
      .then((s) => {
        if (!s.setup_required) {
          router.replace("/login/");
          return;
        }
        setF((prev) => ({ ...prev, timezone: browserTimeZone() }));
        setStatus(s);
      })
      .catch(setLoadError);
  }, [router]);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const steps: StepDef[] = useMemo(() => {
    const later = (status?.steps ?? []).filter((s) => !s.available);
    return [
      { key: "token", title: "Verify access", available: true },
      { key: "administrator", title: "Administrator account", available: true },
      { key: "organization", title: "Organization", available: true },
      { key: "installation", title: "Installation", available: true },
      { key: "numbering", title: "Numbering plan", available: true },
      { key: "review", title: "Review", available: true },
      ...later.map((s) => ({ key: s.key, title: s.title, available: false, note: s.milestone ? `Coming later (Milestone ${s.milestone})` : "Coming later" })),
    ];
  }, [status]);

  const validate = (k: StepKey): Record<string, string> => {
    const e: Record<string, string> = {};
    if (k === "token" && !f.setup_token.trim()) e.setup_token = "Enter the setup token.";
    if (k === "administrator") {
      if (!/^[^@\s]+@[^@\s]+$/.test(f.admin_email.trim())) e["administrator.email"] = "Enter a valid email address.";
      if (!f.admin_name.trim()) e["administrator.display_name"] = "Enter a name.";
      if (f.admin_password.length < 12) e["administrator.password"] = "Use at least 12 characters.";
      else if (f.admin_password !== f.admin_password2) e.admin_password2 = "Passwords do not match.";
    }
    if (k === "organization") {
      if (!f.org_name.trim()) e["organization.name"] = "Enter the organization name.";
      if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(f.org_slug)) e["organization.slug"] = "Use lower-case letters, digits and dashes.";
    }
    if (k === "installation" && !f.installation_name.trim()) e.installation_name = "Enter a name for this installation.";
    if (k === "numbering") {
      const len = Number(f.ext_length);
      if (!/^\d+$/.test(f.ext_first) || f.ext_first.length !== len) e["numbering.first_extension"] = `Enter a ${len}-digit number.`;
      if (!/^\d+$/.test(f.ext_last) || f.ext_last.length !== len) e["numbering.last_extension"] = `Enter a ${len}-digit number.`;
      if (!e["numbering.first_extension"] && !e["numbering.last_extension"] && Number(f.ext_last) < Number(f.ext_first)) e["numbering.last_extension"] = "Must not be lower than the first extension.";
      const lead = f.ext_first[0];
      if (!e["numbering.first_extension"] && !e["numbering.last_extension"] && lead === f.ext_last[0] && (lead === "0" || lead === "9")) {
        e["numbering.first_extension"] = "The whole range starts with a reserved digit (0 or 9).";
      }
    }
    return e;
  };

  const goNext = (e: FormEvent) => {
    e.preventDefault();
    const errs = validate(step);
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;
    setDone((d) => new Set(d).add(step));
    const i = FLOW.indexOf(step);
    const nxt = FLOW[i + 1];
    if (nxt) setStep(nxt);
  };

  const back = () => {
    const i = FLOW.indexOf(step);
    const prev = FLOW[i - 1];
    if (prev) setStep(prev);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/setup/initialize", {
        setup_token: f.setup_token.trim(),
        installation_name: f.installation_name.trim(),
        administrator: { email: f.admin_email.trim(), display_name: f.admin_name.trim(), password: f.admin_password },
        organization: { name: f.org_name.trim(), slug: f.org_slug, timezone: f.timezone },
        numbering: { extension_length: Number(f.ext_length), first_extension: f.ext_first, last_extension: f.ext_last, reserved_prefixes: RESERVED_DEFAULT },
      }, { noRedirect: true });
      await refresh();
      router.replace("/");
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError) {
        const fe = err.fieldErrors();
        if (err.code === "invalid_setup_token") fe.setup_token = err.detail ?? "Invalid setup token.";
        setFieldErrors(fe);
        const first = Object.keys(fe).map((k) => FIELD_STEP[k]).find(Boolean);
        if (first) setStep(first);
        setError(err.detail || err.title);
      } else {
        setError("Setup failed. Check that the Veyra service is running and try again.");
      }
    }
  };

  if (loadError) return <AuthLayout><ErrorState title="Cannot reach Veyra" error={loadError} onRetry={() => location.reload()} /></AuthLayout>;
  if (!status) return <AuthLayout><LoadingState /></AuthLayout>;

  return (
    <AuthLayout wide>
      <div className="stack">
        <div className="row"><BrandLogo height={30} /></div>
        <div>
          <h1 className="auth__title">Set up Veyra</h1>
          <p className="muted">Create the first administrator and organization. You can change everything later.</p>
        </div>
        <div className="wizard">
          <Stepper steps={steps} current={step} completed={done} />
          <Card>
            <form className="stack" onSubmit={step === "review" ? (e) => { e.preventDefault(); void submit(); } : goNext}>
              {step === "token" ? (
                <>
                  <div>
                    <h2 className="card__title">Verify access</h2>
                    <p className="muted">Only someone with access to the server console can complete setup.</p>
                  </div>
                  <Callout tone="info" title="Where do I find the setup token?">
                    The installer printed a one-time token when it finished. To create a new one, run this on the server:
                    <pre className="code" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>sudo veyra setup-token</pre>
                    Tokens are valid for 24 hours and can be used once.
                    {!status.token_issued ? <><br />No token has been issued yet.</> : null}
                  </Callout>
                  <TextField label="Setup token" required autoFocus autoComplete="off" spellCheck={false} value={f.setup_token}
                    error={fieldErrors.setup_token} onChange={(e) => set("setup_token", e.target.value)} />
                </>
              ) : null}
              {step === "administrator" ? (
                <>
                  <div>
                    <h2 className="card__title">Administrator account</h2>
                    <p className="muted">This becomes the platform administrator and the local recovery account.</p>
                  </div>
                  <TextField label="Full name" required autoFocus value={f.admin_name} error={fieldErrors["administrator.display_name"]} onChange={(e) => set("admin_name", e.target.value)} />
                  <TextField label="Email address" type="email" required autoComplete="username" value={f.admin_email} error={fieldErrors["administrator.email"]} onChange={(e) => set("admin_email", e.target.value)} />
                  <div className="form-grid">
                    <TextField label="Password" type="password" required autoComplete="new-password" help="At least 12 characters." value={f.admin_password} error={fieldErrors["administrator.password"]} onChange={(e) => set("admin_password", e.target.value)} />
                    <TextField label="Confirm password" type="password" required autoComplete="new-password" value={f.admin_password2} error={fieldErrors.admin_password2} onChange={(e) => set("admin_password2", e.target.value)} />
                  </div>
                </>
              ) : null}
              {step === "organization" ? (
                <>
                  <div>
                    <h2 className="card__title">Organization</h2>
                    <p className="muted">The school district, municipality or business this installation serves.</p>
                  </div>
                  <TextField label="Organization name" required autoFocus value={f.org_name} error={fieldErrors["organization.name"]}
                    onChange={(e) => setF((s) => ({ ...s, org_name: e.target.value, org_slug: s.slug_touched ? s.org_slug : slugify(e.target.value) }))} />
                  <TextField label="Short name" required help="Used in addresses and identifiers. Lower-case letters, digits and dashes." value={f.org_slug}
                    error={fieldErrors["organization.slug"]} onChange={(e) => setF((s) => ({ ...s, org_slug: e.target.value.toLowerCase(), slug_touched: true }))} />
                </>
              ) : null}
              {step === "installation" ? (
                <>
                  <div>
                    <h2 className="card__title">Installation</h2>
                    <p className="muted">How this Veyra server is identified, and its default time zone.</p>
                  </div>
                  <TextField label="Installation name" required autoFocus placeholder="e.g. District Phone System" value={f.installation_name}
                    error={fieldErrors.installation_name} onChange={(e) => set("installation_name", e.target.value)} />
                  <SelectField label="Time zone" value={f.timezone} error={fieldErrors["organization.timezone"]}
                    options={zones.map((z) => ({ value: z, label: z.replace(/_/g, " ") }))} onChange={(e) => set("timezone", e.target.value)} />
                  <Callout tone={status.telephony_state === "running" ? "ok" : status.telephony_state === "not_configured" ? "neutral" : "warn"} title="Telephony engine check">
                    {status.telephony_state === "running"
                      ? "Asterisk is running and reachable. SIP settings and the first configuration deployment are done after setup, under System → Telephony Engine."
                      : status.telephony_state === "not_configured"
                        ? "No telephony engine is configured on this server. Setup can continue; telephony features stay unavailable until an engine is installed."
                        : `The telephony engine is ${status.telephony_state.replace(/_/g, " ")}. Setup can continue; check the engine from System → Telephony Engine afterwards.`}
                  </Callout>
                </>
              ) : null}
              {step === "numbering" ? (
                <>
                  <div>
                    <h2 className="card__title">Numbering plan</h2>
                    <p className="muted">How extensions are numbered. You can change this later under Extensions; existing extensions keep their numbers.</p>
                  </div>
                  <SelectField label="Extension length" value={f.ext_length} options={LENGTH_OPTIONS}
                    onChange={(e) => { const [first, last] = RANGE_DEFAULTS[e.target.value] ?? ["", ""]; setF((s) => ({ ...s, ext_length: e.target.value, ext_first: first, ext_last: last })); }} />
                  <div className="form-grid">
                    <TextField label="First extension" required inputMode="numeric" value={f.ext_first} error={fieldErrors["numbering.first_extension"]}
                      onChange={(e) => set("ext_first", e.target.value.replace(/\D/g, ""))} />
                    <TextField label="Last extension" required inputMode="numeric" value={f.ext_last} error={fieldErrors["numbering.last_extension"]}
                      onChange={(e) => set("ext_last", e.target.value.replace(/\D/g, ""))} />
                  </div>
                  {fieldErrors.numbering ? <Callout tone="danger">{fieldErrors.numbering}</Callout> : null}
                  <Callout tone="neutral" title="Reserved numbers">
                    Extensions never start with 0 (operator), 9 (outside line), 911 or 933 (emergency), whatever range you choose. Feature codes such as *43 use the star key and never collide.
                  </Callout>
                </>
              ) : null}
              {step === "review" ? (
                <>
                  <div>
                    <h2 className="card__title">Review</h2>
                    <p className="muted">Confirm these details to finish setup.</p>
                  </div>
                  <dl className="dl">
                    <dt>Administrator</dt><dd>{f.admin_name} ({f.admin_email})</dd>
                    <dt>Organization</dt><dd>{f.org_name} <span className="subtle">({f.org_slug})</span></dd>
                    <dt>Installation</dt><dd>{f.installation_name}</dd>
                    <dt>Time zone</dt><dd>{f.timezone}</dd>
                    <dt>Extensions</dt><dd>{f.ext_length}-digit numbers from <span className="mono">{f.ext_first}</span> to <span className="mono">{f.ext_last}</span></dd>
                  </dl>
                  <Callout tone="neutral">
                    Network, SIP, email, backup, update and high availability settings are configured in later releases;
                    they are listed on the left as “coming later”. High availability is optional.
                  </Callout>
                </>
              ) : null}
              {error && step === "review" ? <Callout tone="danger">{error}</Callout> : null}
              <div className="form-actions">
                {step !== "token" ? <Button onClick={back} disabled={busy}>Back</Button> : null}
                <Button variant="primary" type="submit" loading={busy}>{step === "review" ? "Finish setup" : "Continue"}</Button>
              </div>
            </form>
          </Card>
        </div>
      </div>
    </AuthLayout>
  );
}
