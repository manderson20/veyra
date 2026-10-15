// SPDX-License-Identifier: AGPL-3.0-or-later
// Helpers for the central console and membership pages (docs/CENTRAL_MANAGEMENT.md).
import type { CentralPolicyDocument, CentralStatus, MaintenanceWindow, UpdateMode } from "./types";

export const SECTION_LABELS: Record<string, string> = {
  updates: "Update policy",
  firewall_allow: "Firewall allow list",
  alert_recipients: "Alert recipients",
  notice: "Notice banner",
  commands: "Commands from the console",
};

export const COMMAND_LABELS: Record<string, string> = {
  check_updates: "Check for updates",
  download_update: "Download an update",
  approve_update: "Approve an update",
  refresh_catalogs: "Refresh catalogs",
};

export const STATUS_TONE: Record<CentralStatus, "ok" | "warn" | "danger" | "neutral"> = {
  ok: "ok",
  online: "ok",
  degraded: "warn",
  failed: "danger",
  offline: "danger",
  revoked: "neutral",
};

/** Tone of a per-section policy result on the instance ("applied", "unchanged", "refused", "error: …"). */
export function resultTone(result: string): "ok" | "warn" | "danger" | "neutral" {
  if (result === "applied" || result === "unchanged") return "ok";
  if (result.startsWith("error")) return "danger";
  if (result === "refused") return "warn";
  return "neutral";
}

/** One address per line or separated by commas; blanks dropped. */
export function parseList(text: string): string[] {
  return text
    .split(/[\n,;]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Lines of "<cidr> [comment]". */
export function parseAllow(text: string): { cidr: string; comment: string | null }[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [cidr, ...rest] = l.split(/\s+/);
      const comment = rest.join(" ").replace(/^#\s*/, "").trim();
      return { cidr: cidr ?? "", comment: comment || null };
    });
}

export function formatAllow(entries: { cidr: string; comment?: string | null }[] | undefined): string {
  return (entries ?? []).map((e) => (e.comment ? `${e.cidr} ${e.comment}` : e.cidr)).join("\n");
}

/** Editable form of a policy document: each section can be left unset. */
export interface PolicyForm {
  updates: boolean;
  mode: UpdateMode;
  window: MaintenanceWindow | null;
  categories: string[];
  sourceUrl: string;
  updateRecipients: string;
  firewall: boolean;
  allow: string;
  alerts: boolean;
  recipients: string;
  noticeOn: boolean;
  notice: string;
}

export function policyForm(doc: CentralPolicyDocument | undefined): PolicyForm {
  const u = doc?.updates;
  const p = u?.policy;
  return {
    updates: !!u,
    mode: (p?.mode as UpdateMode) ?? "notify",
    window: (p?.maintenance_window as MaintenanceWindow | null | undefined) ?? null,
    categories: (p?.auto_install_categories as string[] | undefined) ?? [],
    sourceUrl: u?.source_url ?? "",
    updateRecipients: (u?.recipients ?? []).join("\n"),
    firewall: doc?.firewall_allow != null,
    allow: formatAllow(doc?.firewall_allow),
    alerts: doc?.alert_recipients != null,
    recipients: (doc?.alert_recipients ?? []).join("\n"),
    noticeOn: doc?.notice != null,
    notice: doc?.notice ?? "",
  };
}

export function policyDocument(f: PolicyForm): CentralPolicyDocument {
  const doc: CentralPolicyDocument = {};
  if (f.updates) {
    const auto = f.mode === "auto_install_window";
    doc.updates = {
      policy: {
        mode: f.mode,
        auto_download: f.mode === "download_approve" || auto,
        maintenance_window: f.window,
        auto_install_categories: auto ? f.categories : [],
      },
      source_url: f.sourceUrl.trim() || null,
      recipients: f.updateRecipients.trim() ? parseList(f.updateRecipients) : null,
    };
  }
  if (f.firewall) doc.firewall_allow = parseAllow(f.allow);
  if (f.alerts) doc.alert_recipients = parseList(f.recipients);
  if (f.noticeOn) doc.notice = f.notice.trim();
  return doc;
}

/** Short summary of what a policy sets, for tables. */
export function policySummary(doc: CentralPolicyDocument): string[] {
  const out: string[] = [];
  if (doc.updates) out.push(`Updates: ${doc.updates.policy.mode.replace(/_/g, " ")}`);
  if (doc.firewall_allow) out.push(`Allow list: ${doc.firewall_allow.length}`);
  if (doc.alert_recipients) out.push(`Alert recipients: ${doc.alert_recipients.length}`);
  if (doc.notice != null) out.push(doc.notice ? "Notice" : "No notice");
  return out;
}
