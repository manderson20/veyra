// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Tone } from "../ui";

export const TELEPHONY_STATE: Record<string, string> = {
  running: "Running",
  stopped: "Stopped",
  not_installed: "Not installed",
  unreachable: "Unreachable",
  not_configured: "Not configured",
  unknown: "Unknown",
};

export const MODULE_STATE: Record<string, { label: string; tone: Tone }> = {
  available: { label: "Available", tone: "outline" },
  installed: { label: "Installed", tone: "neutral" },
  enabled: { label: "Enabled", tone: "ok" },
  disabled: { label: "Disabled", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
  removed: { label: "Removed (data kept)", tone: "warn" },
};

export const TRUST: Record<string, { label: string; tone: Tone; icon: string }> = {
  official: { label: "Official", tone: "info", icon: "shield" },
  community: { label: "Community", tone: "accent", icon: "users" },
  third_party: { label: "Third-party", tone: "warn", icon: "puzzle" },
  unsigned: { label: "Unsigned", tone: "danger", icon: "alert" },
};

export const REVISION_STATE: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "outline" },
  validated: { label: "Ready to deploy", tone: "info" },
  deploying: { label: "Deploying…", tone: "accent" },
  deployed: { label: "Deployed", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  superseded: { label: "Superseded", tone: "neutral" },
  rolled_back: { label: "Rolled back", tone: "warn" },
};

export const OUTCOME: Record<string, Tone> = { success: "ok", failure: "danger", denied: "warn" };

export const TEMPLATE_SOURCE: Record<string, { label: string; tone: Tone }> = {
  official: { label: "Official", tone: "info" },
  community: { label: "Community", tone: "accent" },
  local: { label: "Local", tone: "neutral" },
};
