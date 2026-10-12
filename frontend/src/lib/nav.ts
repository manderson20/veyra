// SPDX-License-Identifier: AGPL-3.0-or-later
/** Navigation model and permission filtering (unit tested). */

import type { UiExtension } from "./types";

export interface NavItem {
  label: string;
  href: string;
  icon: string;
  /** Any of these permissions shows the item (advisory; the API enforces access). */
  permissions?: string[];
  platformOnly?: boolean;
  /** Planned features link to /planned/ and display their milestone. */
  planned?: { milestone: number | null };
}

export interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
  collapsible?: boolean;
}

export interface PlannedFeature {
  key: string;
  label: string;
  icon: string;
  milestone: number | null;
  summary: string;
}

export const PLANNED_FEATURES: PlannedFeature[] = [
  { key: "extensions", label: "Extensions", icon: "phone", milestone: 4,
    summary: "Create and manage extensions, SIP credentials and caller ID for users and shared phones." },
  { key: "devices", label: "Devices", icon: "device", milestone: 9,
    summary: "Register desk phones by MAC address, assign provisioning templates and extensions." },
  { key: "trunks", label: "SIP Trunks", icon: "trunk", milestone: 6,
    summary: "Connect to carriers with registration or IP-authenticated SIP trunks and monitor their status." },
  { key: "inbound-routing", label: "Inbound Routing", icon: "arrowIn", milestone: 6,
    summary: "Route DIDs to extensions, IVRs, ring groups, queues and voicemail, with time conditions." },
  { key: "outbound-routing", label: "Outbound Routing", icon: "arrowOut", milestone: 6,
    summary: "Dial plans, trunk selection, failover and caller ID rules for outbound calls." },
  { key: "ivr", label: "IVR", icon: "ivr", milestone: 7,
    summary: "Auto attendant menus with recorded prompts, multi-level menus and direct extension dialing." },
  { key: "ring-groups", label: "Ring Groups", icon: "group", milestone: 8,
    summary: "Ring several phones at once or in sequence, with failover destinations." },
  { key: "queues", label: "Call Queues", icon: "queue", milestone: 8,
    summary: "Queue callers for groups of agents with hold music, announcements and strategies." },
  { key: "voicemail", label: "Voicemail", icon: "voicemail", milestone: 7,
    summary: "Voicemail boxes, greetings, voicemail-to-email and message waiting indicators." },
  { key: "paging", label: "Paging", icon: "megaphone", milestone: null,
    summary: "Paging groups, SIP paging endpoints (such as Algo speakers), multicast paging and intercom. " +
      "SIP paging is not a life-safety notification system." },
  { key: "call-history", label: "Call History", icon: "history", milestone: 10,
    summary: "Searchable call detail records with filtering and CSV export, respecting tenant permissions." },
  { key: "recording", label: "Call Recording", icon: "record", milestone: 10,
    summary: "Policy-based call recording with retention rules and permission-controlled playback." },
];

export function plannedFeature(key: string | null): PlannedFeature | undefined {
  return PLANNED_FEATURES.find((f) => f.key === key);
}

export const NAV: NavSection[] = [
  { id: "overview", label: "Overview", items: [
    { label: "Dashboard", href: "/", icon: "dashboard", permissions: ["system.health.read"] },
  ] },
  { id: "directory", label: "Directory", items: [
    { label: "Organizations", href: "/organizations/", icon: "building", permissions: ["organizations.read"] },
    { label: "Users", href: "/users/", icon: "users", permissions: ["users.read"] },
  ] },
  { id: "telephony", label: "Telephony", collapsible: true, items: PLANNED_FEATURES.map((f) => ({
    label: f.label, href: `/planned/?feature=${f.key}`, icon: f.icon, planned: { milestone: f.milestone },
  })) },
  { id: "provisioning", label: "Provisioning", items: [
    { label: "Templates", href: "/provisioning/", icon: "template", permissions: ["provisioning.read"] },
  ] },
  { id: "modules", label: "Modules", items: [] },
  { id: "system", label: "System", items: [
    { label: "Health", href: "/system/health/", icon: "health", permissions: ["system.health.read"] },
    { label: "Telephony Engine", href: "/system/telephony/", icon: "server", permissions: ["config.read"] },
    { label: "High Availability", href: "/system/ha/", icon: "ha", permissions: ["ha.read"] },
    { label: "Updates", href: "/updates/", icon: "update", permissions: ["updates.read"] },
    { label: "Module Manager", href: "/modules/", icon: "modules", permissions: ["modules.read"] },
    { label: "Audit Log", href: "/audit/", icon: "audit", permissions: ["audit.read"] },
    { label: "Settings", href: "/settings/", icon: "settings" },
  ] },
];

export interface NavContext {
  permissions: string[];
  isPlatformAdmin: boolean;
  extensions?: UiExtension[];
}

export function canSee(item: NavItem, ctx: NavContext): boolean {
  if (ctx.isPlatformAdmin) return true;
  if (item.platformOnly) return false;
  if (!item.permissions || item.permissions.length === 0) return true;
  const held = new Set(ctx.permissions);
  return item.permissions.some((p) => held.has(p) || held.has("*"));
}

export function moduleNavItems(extensions: UiExtension[] = []): NavItem[] {
  return extensions.flatMap((ext) =>
    ext.nav.map((n) => ({
      label: n.label,
      href: `/modules/view/?module=${encodeURIComponent(ext.module_id)}&view=${encodeURIComponent(n.view)}`,
      icon: n.icon,
      permissions: [n.permission],
    })),
  );
}

/** Sections visible to the caller; empty sections are dropped. */
export function buildNav(ctx: NavContext, sections: NavSection[] = NAV): NavSection[] {
  return sections
    .map((s) => {
      const items = s.id === "modules" ? [...s.items, ...moduleNavItems(ctx.extensions)] : s.items;
      return { ...s, items: items.filter((i) => canSee(i, ctx)) };
    })
    .filter((s) => s.items.length > 0);
}

/** True when `href` is the active route for `pathname` (+ search). */
export function isActive(href: string, pathname: string, search = ""): boolean {
  const [hrefPath, hrefQuery] = href.split("?");
  const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
  if (hrefQuery) {
    if (norm(pathname) !== norm(hrefPath ?? "")) return false;
    const want = new URLSearchParams(hrefQuery);
    const have = new URLSearchParams(search);
    for (const [k, v] of want) if (have.get(k) !== v) return false;
    return true;
  }
  if (hrefPath === "/") return norm(pathname) === "/";
  return norm(pathname).startsWith(norm(hrefPath ?? ""));
}
