// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState, type ReactNode } from "react";
import { CopyButton } from "@/components/common/CopyButton";
import { Badge, Button, Callout, Card, DataTable, ErrorState, Icon, LinkButton, LoadingState, PageHeader, SelectField, Stepper, type StepDef } from "@/components/ui";
import type { CompanionRollout, SsoProviderPublic } from "@/lib/types";
import { formatRelative } from "@/lib/format";
import { useApiData } from "@/hooks/useApiData";

/* The Companion rollout guide (docs/COMPANION.md §5.1): where the browsers
 * are managed, trusting the server's certificate, how people sign in, the
 * push itself, and a check that the extension is signing in. */

type Platform = "google" | "windows" | "self";
type StepKey = "platform" | "certificate" | "signin" | "push" | "check";

const STEPS: { key: StepKey; title: string }[] = [
  { key: "platform", title: "Where browsers are managed" },
  { key: "certificate", title: "Trust this server" },
  { key: "signin", title: "How people sign in" },
  { key: "push", title: "Push the extension" },
  { key: "check", title: "Check it worked" },
];

const PLATFORMS: { value: Platform; title: string; text: string }[] = [
  { value: "google", title: "Google Admin console", text: "Chromebooks, and Chrome on any computer enrolled in Chrome Browser Cloud Management." },
  { value: "windows", title: "Windows: Group Policy or Intune", text: "Chrome and Edge on computers joined to Active Directory or managed by Intune." },
  { value: "self", title: "People install it themselves", text: "Browsers nobody manages: each person adds the extension by hand." },
];

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer">{children} <Icon name="external" size={12} /></a>;
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className="row" style={{ gap: 6, flexWrap: "wrap" }}><code className="mono" style={{ wordBreak: "break-all" }}>{value}</code><CopyButton text={value} /></dd>
    </>
  );
}

/** A .reg file that force-installs the extension in Chrome and Edge and
 *  preloads the server address (machine policy, both browsers). */
function registryFile(id: string, updateUrl: string, policy: Record<string, string>): string {
  const q = (s: string) => `"${s.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  const lines = ["Windows Registry Editor Version 5.00", ""];
  for (const browser of ["Google\\Chrome", "Microsoft\\Edge"]) {
    const base = `HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\${browser}`;
    lines.push(`[${base}\\ExtensionInstallForcelist]`, `"1"=${q(`${id};${updateUrl}`)}`, "");
    lines.push(`[${base}\\3rdparty\\extensions\\${id}\\policy]`);
    for (const [k, v] of Object.entries(policy)) lines.push(`${q(k)}=${q(v)}`);
    lines.push("");
  }
  return lines.join("\r\n");
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function CertificateStep({ rollout, platform }: { rollout: CompanionRollout; platform: Platform }) {
  const c = rollout.certificate;
  if (c.kind === "public") {
    return (
      <Callout tone="ok" title="Nothing to do: browsers already trust this server">
        {rollout.host} has a certificate from a public authority{c.issuer ? <> ({c.issuer})</> : null}{c.not_after ? <>, renewed automatically before {new Date(c.not_after).toLocaleDateString()}</> : null}. Every browser trusts it without any change.
      </Callout>
    );
  }
  return (
    <>
      <Callout tone="warn" title="Browsers do not trust this server yet">
        {rollout.host} uses a certificate signed by this server&apos;s own Veyra certificate authority. Unlike a person, the extension cannot click past a certificate warning, so it cannot connect until the browser trusts that authority. Push the Veyra CA certificate to the browsers first — or get a free public certificate instead (Settings → HTTPS certificate), which every browser trusts as it is and needs nothing pushed.
      </Callout>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <LinkButton href={rollout.ca_url} icon="download">Download the Veyra CA certificate</LinkButton>
        <LinkButton href="/settings/" variant="ghost">Use a public certificate instead</LinkButton>
      </div>
      {platform === "google" ? (
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li>In the <Ext href="https://admin.google.com/ac/networks/certificates">Google Admin console</Ext>, open <strong>Devices → Networks → Certificates</strong> and pick the organizational unit (the top one covers everyone).</li>
          <li>Choose <strong>Add certificate</strong>, name it <em>Veyra CA</em> and upload <span className="mono">veyra-ca.crt</span>.</li>
          <li>Under <strong>Certificate authority</strong>, tick <strong>Chromebook</strong> and <strong>Chrome browser</strong> (the second covers Chrome on managed Windows and Mac computers), then <strong>Add</strong>.</li>
        </ol>
      ) : platform === "windows" ? (
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li><strong>Group Policy:</strong> in a policy linked to the computers, open <strong>Computer Configuration → Policies → Windows Settings → Security Settings → Public Key Policies → Trusted Root Certification Authorities</strong>, right-click, <strong>Import</strong>, and pick <span className="mono">veyra-ca.crt</span>.</li>
          <li><strong>Intune:</strong> <Ext href="https://intune.microsoft.com/#view/Microsoft_Intune_DeviceSettings/DevicesMenu/~/configuration">Devices → Configuration</Ext> → <strong>Create → New policy</strong>, platform <strong>Windows 10 and later</strong>, profile type <strong>Templates → Trusted certificate</strong>; upload <span className="mono">veyra-ca.crt</span>, destination store <strong>Computer certificate store - Root</strong>, and assign it to the device groups.</li>
          <li>Chrome and Edge on Windows use the Windows certificate store, so nothing else is needed for the browsers.</li>
        </ol>
      ) : (
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li><strong>Windows:</strong> double-click <span className="mono">veyra-ca.crt</span> → <strong>Install Certificate</strong> → <strong>Local Machine</strong> → <strong>Place all certificates in the following store</strong> → <strong>Trusted Root Certification Authorities</strong>.</li>
          <li><strong>Mac:</strong> double-click it to add it to Keychain Access, open it in the <strong>System</strong> keychain, and under <strong>Trust</strong> set <strong>When using this certificate</strong> to <strong>Always Trust</strong>.</li>
          <li><strong>Chromebook (not managed):</strong> chrome://certificate-manager → <strong>Local certificates → Custom → Import</strong>, and tick <em>Trust this certificate for identifying websites</em>.</li>
        </ol>
      )}
      <p className="subtle">To check: open {rollout.origin} in a new window of a browser that got the certificate. There should be no warning, and the padlock should show the connection as secure.</p>
    </>
  );
}

function PushStep({ rollout, platform, policy }: { rollout: CompanionRollout; platform: Platform; policy: Record<string, string> }) {
  const d = rollout.info;
  const json = JSON.stringify(policy, null, 2);
  if (platform === "self") {
    return (
      <>
        <p>Chrome and Edge install extensions from outside their stores only when a policy allows it, so on unmanaged browsers each person loads the extension by hand:</p>
        <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
          <li>They sign in to Veyra and open <strong>Account → Connected apps</strong>, which has the download and these steps.</li>
          <li>They unzip <span className="mono">veyra-companion.zip</span> into a folder they will keep (the browser reads it from there).</li>
          <li>In <span className="mono">chrome://extensions</span> (Edge: <span className="mono">edge://extensions</span>) they turn on <strong>Developer mode</strong>, choose <strong>Load unpacked</strong> and pick the folder.</li>
          <li>They click the Veyra icon, enter <span className="mono">{rollout.origin}</span> and sign in.</li>
        </ol>
        <Callout tone="neutral" title="Updates are by hand too">A loaded-unpacked extension does not update itself. After a Veyra upgrade, people download the zip again and replace the folder&apos;s contents. Where browsers can be managed, a pushed extension updates itself.</Callout>
        {d.zip_url ? <div><LinkButton href={d.zip_url} icon="download">Download the zip</LinkButton></div> : null}
        {d.install_sources_pattern ? (
          <Callout tone="neutral" title="Managed browsers, but people choose">
            To let people install it with one click instead of forcing it on everyone, allow this server as an install source — policy <span className="mono">ExtensionInstallSources</span> (Google Admin console: Chrome → Settings → Users &amp; browsers → <strong>App and extension install sources</strong>) with <code className="mono">{d.install_sources_pattern}</code> <CopyButton text={d.install_sources_pattern} />. The <strong>Add to Chrome</strong> button on their account page then works.
          </Callout>
        ) : null}
      </>
    );
  }
  if (!d.extension_id || !d.update_url) {
    return (
      <Callout tone="warn" title="The signed package is missing on this server">
        The installer did not produce the signed extension package that browsers need for a pushed install. Run the upgrade again (<span className="mono">sudo veyra updates install</span>, or the installer&apos;s upgrade script); its log says why signing failed.
      </Callout>
    );
  }
  return (
    <>
      <dl className="dl">
        <Value label="Extension ID" value={d.extension_id} />
        <Value label="Update URL" value={d.update_url} />
        <Value label="Install line (ID;URL)" value={`${d.extension_id};${d.update_url}`} />
      </dl>
      {platform === "google" ? (
        <>
          <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
            <li>In the <Ext href="https://admin.google.com/ac/chrome/apps/user">Google Admin console</Ext>, open <strong>Devices → Chrome → Apps &amp; extensions → Users &amp; browsers</strong> and pick the organizational unit of the people who should get it.</li>
            <li>Choose the yellow <strong>+</strong> button → <strong>Add Chrome app or extension by ID</strong>, pick <strong>From a custom URL</strong>, and paste the <strong>Extension ID</strong> and the <strong>Update URL</strong> above.</li>
            <li>Set <strong>Installation policy</strong> to <strong>Force install + pin to browser toolbar</strong>.</li>
            <li>In <strong>Policy for extensions</strong> on the right, paste:<pre className="mono" style={{ margin: "8px 0", whiteSpace: "pre-wrap" }}>{json}</pre><CopyButton text={json} /></li>
            <li>Choose <strong>Save</strong>. Chromebooks and managed Chrome pick it up within a few hours, or right away after signing out and in, or from <span className="mono">chrome://policy</span> → <strong>Reload policies</strong>.</li>
          </ol>
          <Callout tone="neutral" title="Chrome on Windows or Mac">Google Admin console policies reach Chrome on Windows and Mac only when the browser is enrolled in Chrome Browser Cloud Management, or when people sign in to Chrome with their managed account. For computers that are only joined to the domain, use the Windows option instead.</Callout>
        </>
      ) : (
        <>
          <Callout tone="info" title="Only on managed computers">Chrome and Edge on Windows install extensions from outside their stores only on computers joined to Active Directory, joined to Microsoft Entra and managed by Intune, or enrolled in Chrome Browser Cloud Management. On any other computer the browser ignores this policy, and people install the extension themselves.</Callout>
          <h3 className="card__title" style={{ fontSize: "1rem" }}>Group Policy</h3>
          <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
            <li>Install the Chrome and Edge administrative templates (ADMX) on the domain controllers if they are not there yet: <Ext href="https://support.google.com/chrome/a/answer/187202">Chrome</Ext>, <Ext href="https://www.microsoft.com/edge/business/download">Edge</Ext>.</li>
            <li>In a policy linked to the computers: <strong>Computer Configuration → Policies → Administrative Templates → Google → Google Chrome → Extensions → Configure the list of force-installed apps and extensions</strong>: <strong>Enabled</strong>, <strong>Show</strong>, and add the <strong>install line</strong> above.</li>
            <li>For Edge: <strong>… → Microsoft Edge → Extensions → Control which extensions are installed silently</strong>, the same install line.</li>
            <li>To preload the server address, add the registry values from the file below to the same policy (<strong>Preferences → Windows Settings → Registry</strong>), or import the file on one computer to try it first.</li>
          </ol>
          <h3 className="card__title" style={{ fontSize: "1rem" }}>Intune</h3>
          <ol className="stack" style={{ paddingLeft: 20, gap: 10 }}>
            <li><Ext href="https://intune.microsoft.com/#view/Microsoft_Intune_DeviceSettings/DevicesMenu/~/configuration">Devices → Configuration</Ext> → <strong>Create → New policy</strong>, platform <strong>Windows 10 and later</strong>, profile type <strong>Settings catalog</strong>.</li>
            <li>Add <strong>Microsoft Edge → Extensions → Control which extensions are installed silently</strong> and <strong>Google Chrome → Extensions → Configure the list of force-installed apps and extensions</strong>, each with the <strong>install line</strong> above. (If Google Chrome is not in the catalog, import Chrome&apos;s ADMX first under <strong>Devices → Configuration → Import ADMX</strong>.)</li>
            <li>To preload the server address, deploy the registry file below with a script or remediation; without it, people type the address once.</li>
          </ol>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Button icon="download" onClick={() => download("veyra-companion-policy.reg", registryFile(d.extension_id!, d.update_url!, policy), "text/plain")}>Download the registry file</Button>
            <span className="subtle">Machine policy for Chrome and Edge: force-install plus the server address. If you already force-install other extensions, change the &quot;1&quot; to the next free number.</span>
          </div>
        </>
      )}
      <p className="subtle">Every Veyra upgrade re-signs the extension with the same key, so the ID stays the same and browsers fetch new versions from the update URL by themselves.</p>
    </>
  );
}

function CheckStep({ rollout, reload, loading }: { rollout: CompanionRollout; reload: () => void; loading: boolean }) {
  const a = rollout.adoption;
  return (
    <>
      <div className="row" style={{ gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <span><strong style={{ fontSize: "1.5rem" }}>{a.users}</strong> <span className="muted">people signed in to the Companion</span></span>
        <span><strong style={{ fontSize: "1.5rem" }}>{a.active_7d}</strong> <span className="muted">used it in the last 7 days</span></span>
        <Button icon="refresh" onClick={reload} loading={loading}>Check again</Button>
      </div>
      {a.users === 0 ? (
        <Callout tone="info" title="No sign-ins yet">
          Policies take a while to reach browsers. On one test computer:
          <ol className="stack" style={{ paddingLeft: 20, gap: 6, marginTop: 8 }}>
            <li>Open <span className="mono">chrome://policy</span> (Edge: <span className="mono">edge://policy</span>), choose <strong>Reload policies</strong>, and look for <strong>ExtensionInstallForcelist</strong> with the install line. If it is missing, the policy has not reached this browser yet.</li>
            <li>Open <span className="mono">chrome://extensions</span>: <strong>Veyra Companion</strong> should be listed as installed by your administrator. If the policy is there but the extension is not, the browser could not download it: check the certificate step, and that the computer can reach {rollout.origin}.</li>
            <li>Click the Veyra icon and sign in. The sign-in shows up here.</li>
          </ol>
        </Callout>
      ) : (
        <DataTable
          caption="Recent Companion sign-ins"
          rows={rollout.adoption.recent}
          rowKey={(r) => `${r.email}-${r.created_at}`}
          columns={[
            { key: "who", header: "Person", render: (r) => <span>{r.display_name} <span className="subtle">{r.email}</span></span> },
            { key: "device", header: "Device", render: (r) => r.device },
            { key: "signed", header: "Signed in", render: (r) => formatRelative(r.created_at) },
            { key: "used", header: "Last used", render: (r) => (r.last_used_at ? formatRelative(r.last_used_at) : "not yet") },
          ]}
        />
      )}
    </>
  );
}

export default function CompanionRolloutPage() {
  const data = useApiData<CompanionRollout>("/companion/rollout");
  const providers = useApiData<SsoProviderPublic[]>("/auth/sso/providers");
  const [step, setStep] = useState<StepKey>("platform");
  const [platform, setPlatform] = useState<Platform>("google");
  const [sso, setSso] = useState<string | null>(null);
  const r = data.data;
  const index = STEPS.findIndex((s) => s.key === step);
  const steps: StepDef[] = STEPS.map((s) => ({ key: s.key, title: s.title, available: true }));
  const done = new Set(STEPS.slice(0, index).map((s) => s.key));
  // Without an explicit choice, a provider (when there is one) is used.
  const ssoId = sso ?? providers.data?.[0]?.id ?? "";
  const policy: Record<string, string> = r ? { serverUrl: r.origin, ...(ssoId ? { ssoProvider: ssoId } : {}) } : {};

  return (
    <div className="stack">
      <PageHeader title="Companion rollout" description="A step-by-step guide to putting the Veyra Companion extension in people's browsers: click-to-dial, caller pop-ups and voicemail." back={{ href: "/settings/", label: "Settings" }} />
      {data.loading && !r ? <LoadingState /> : null}
      {data.error ? <ErrorState error={data.error} onRetry={data.reload} /> : null}
      {r ? (
        <div className="wizard">
          <Stepper steps={steps} current={step} completed={done} />
          <Card>
            <div className="stack">
              {step === "platform" ? (
                <>
                  <div>
                    <h2 className="card__title">Where are your browsers managed?</h2>
                    <p className="muted">Pushed by policy, the extension installs itself, stays up to date with every Veyra upgrade, and can come with the server address filled in, so people only sign in.</p>
                  </div>
                  <div className="choice-tiles" role="radiogroup" aria-label="Where browsers are managed">
                    {PLATFORMS.map((p) => (
                      <button key={p.value} type="button" role="radio" aria-checked={platform === p.value} className="choice-tile" onClick={() => setPlatform(p.value)}>
                        <strong>{p.title}</strong>
                        <span className="subtle">{p.text}</span>
                      </button>
                    ))}
                  </div>
                  <p className="subtle">
                    Extension: {r.info.name ?? "Veyra Companion"} {r.info.version ? <Badge tone="neutral">{r.info.version}</Badge> : null} · Chrome and Edge (and other Chromium browsers). Several kinds of computer? Go through the guide once for each.
                  </p>
                </>
              ) : null}
              {step === "certificate" ? (
                <>
                  <div>
                    <h2 className="card__title">Make the browsers trust this server</h2>
                    <p className="muted">The extension talks to {r.host} over HTTPS, and the browser must accept the server&apos;s certificate without asking.</p>
                  </div>
                  <CertificateStep rollout={r} platform={platform} />
                </>
              ) : null}
              {step === "signin" ? (
                <>
                  <div>
                    <h2 className="card__title">How people sign in to the extension</h2>
                    <p className="muted">People sign in once; the extension stays signed in while they use it.</p>
                  </div>
                  {providers.data && providers.data.length > 0 ? (
                    <>
                      <SelectField label="Sign in with" value={ssoId} options={[...providers.data.map((p) => ({ value: p.id, label: `${p.name} (single sign-on)` })), { value: "", label: "E-mail and password" }]} onChange={(e) => setSso(e.target.value)} />
                      {ssoId && platform === "google" ? (
                        <Callout tone="info" title="Silent sign-in on Chromebooks">On a managed Chromebook the extension then signs in with the person&apos;s Google account by itself. For that, mark Veyra&apos;s OAuth client as trusted: Google Admin console → <strong>Security → Access and data control → API controls → Manage third-party app access</strong> → <strong>Configure new app</strong>, search for the client ID (the one entered when setting up sign-in), and set it to <strong>Trusted</strong>.</Callout>
                      ) : ssoId ? (
                        <Callout tone="neutral">The extension shows a <strong>Sign in with {providers.data.find((p) => p.id === ssoId)?.name}</strong> button, so people do not type a Veyra password.</Callout>
                      ) : null}
                    </>
                  ) : (
                    <Callout tone="neutral" title="E-mail and password">
                      People sign in with their Veyra e-mail address and password (and second factor, when they have one). To let them use their Google or Microsoft account instead, <a href="/system/sign-in/setup/">set up single sign-on</a> first and come back.
                    </Callout>
                  )}
                </>
              ) : null}
              {step === "push" ? (
                <>
                  <div>
                    <h2 className="card__title">{platform === "self" ? "Have people install it" : "Push the extension"}</h2>
                    <p className="muted">{platform === "google" ? "Do this in the Google Admin console in another tab." : platform === "windows" ? "Use whichever of Group Policy or Intune manages the computers." : "Send people these steps, or point them to their account page."}</p>
                  </div>
                  <PushStep rollout={r} platform={platform} policy={policy} />
                </>
              ) : null}
              {step === "check" ? (
                <>
                  <div>
                    <h2 className="card__title">Check that it worked</h2>
                    <p className="muted">Each person who signs in to the Companion shows up here.</p>
                  </div>
                  <CheckStep rollout={r} reload={data.reload} loading={data.loading} />
                </>
              ) : null}
              <div className="row" style={{ gap: 8, justifyContent: "space-between" }}>
                {index > 0 ? <Button onClick={() => setStep(STEPS[index - 1]!.key)}>Back</Button> : <LinkButton href="/settings/">Cancel</LinkButton>}
                {index < STEPS.length - 1 ? <Button variant="primary" onClick={() => setStep(STEPS[index + 1]!.key)}>Continue</Button> : <LinkButton href="/settings/" variant="primary">Done</LinkButton>}
              </div>
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
