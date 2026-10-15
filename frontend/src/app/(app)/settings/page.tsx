// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { CompanionDeploymentCard } from "@/components/account/CompanionDeploymentCard";
import { EmailDeliveryCard } from "@/components/account/EmailDeliveryCard";
import { MfaPolicyCard } from "@/components/account/MfaPolicyCard";
import { MultiTenancyCard } from "@/components/organizations/MultiTenancyCard";
import { useThemePreference } from "@/components/ThemeToggle";
import { Badge, Card, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import type { ThemePreference } from "@/lib/theme";
import type { SystemInfo } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useSession } from "@/hooks/useSession";

const THEMES: { value: ThemePreference; label: string; help: string }[] = [
  { value: "system", label: "System", help: "Follow your device setting" },
  { value: "light", label: "Light", help: "Always use the light theme" },
  { value: "dark", label: "Dark", help: "Always use the dark theme" },
];

export default function SettingsPage() {
  const { can } = useSession();
  const info = useApiData<SystemInfo>(can("system.health.read") ? "/system/info" : null);
  const [theme, setTheme] = useThemePreference();

  return (
    <div className="stack">
      <PageHeader title="Settings" description="Installation information and your personal preferences. Your password and sessions are on the account page." />
      <div className="grid grid--2" style={{ alignItems: "start" }}>
        <Card title="Installation">
          {!can("system.health.read") ? <p className="muted">Your role does not include installation details.</p>
            : info.error ? <ErrorState compact error={info.error} onRetry={info.reload} />
            : !info.data ? <LoadingState /> : (
              <dl className="dl">
                <dt>Name</dt><dd>{info.data.name ?? "—"}</dd>
                <dt>Veyra version</dt><dd className="mono">{info.data.version}</dd>
                <dt>Module API</dt><dd className="mono">{info.data.module_api_version}</dd>
                <dt>Deployment</dt><dd style={{ textTransform: "capitalize" }}>{info.data.deployment_mode ?? "—"}</dd>
                <dt>Multi-tenancy</dt><dd><Badge tone={info.data.multi_tenancy_enabled ? "ok" : "neutral"}>{info.data.multi_tenancy_enabled ? "Enabled" : "Not enabled"}</Badge></dd>
                <dt>Central management</dt><dd><Badge tone={info.data.central_management_enabled ? "ok" : "neutral"}>{info.data.central_management_enabled ? "Enrolled" : "Not enrolled"}</Badge></dd>
                <dt>Instance ID</dt><dd className="mono">{info.data.instance_id ?? "—"}</dd>
              </dl>
            )}
        </Card>
        <Card title="Appearance" subtitle="Saved in this browser.">
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field__label" style={{ marginBottom: 10 }}>Theme</legend>
            <div className="stack stack--sm">
              {THEMES.map((t) => (
                <label key={t.value} className="check">
                  <input type="radio" name="theme" value={t.value} checked={theme === t.value} onChange={() => setTheme(t.value)} />
                  <span className="check__text"><span>{t.label}</span><span className="subtle">{t.help}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
        </Card>
      </div>
      {can("system.settings.read") ? <EmailDeliveryCard editable={can("system.settings.write")} /> : null}
      {can("system.settings.read") ? <MfaPolicyCard editable={can("system.settings.write")} /> : null}
      {can("system.settings.read") ? <CompanionDeploymentCard /> : null}
      {can("system.settings.read") ? <MultiTenancyCard editable={can("system.settings.write")} /> : null}
      <Card title="Coming later">
        <p className="muted">
          Network, backup and branding settings are delivered in later milestones. They are not shown here until they
          work. Single sign-on is under System → Sign-in.
        </p>
      </Card>
    </div>
  );
}
