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
  /** Column heading in the flyout; items of one group sit together. */
  group?: string;
}

export interface NavSection {
  id: string;
  label: string;
  items: NavItem[];
  collapsible?: boolean;
  /** Rail icon and flyout description (docs/INTERFACE_REWORK.md §1). */
  icon?: string;
  description?: string;
}

export interface PlannedFeature {
  key: string;
  label: string;
  icon: string;
  milestone: number | null;
  summary: string;
}

export const PLANNED_FEATURES: PlannedFeature[] = [
];

export function plannedFeature(key: string | null): PlannedFeature | undefined {
  return PLANNED_FEATURES.find((f) => f.key === key);
}

export const NAV: NavSection[] = [
  { id: "overview", label: "Overview", icon: "dashboard", description: "System status, resources and telephony activity at a glance.", items: [
    { label: "Dashboard", href: "/", icon: "dashboard", permissions: ["system.health.read"] },
  ] },
  { id: "me", label: "My Phone", icon: "phone", description: "Your own phone: Do Not Disturb, forwarding, follow-me, voicemail and the codes you can dial.", items: [
    { label: "My Phone", href: "/my-phone/", icon: "phone" },
  ] },
  { id: "directory", label: "Directory", icon: "users", description: "Organizations, their sites and the people who sign in.", items: [
    { label: "Organizations", href: "/organizations/", icon: "building", permissions: ["organizations.read"], group: "Organizations" },
    { label: "Sites", href: "/sites/", icon: "building", permissions: ["organizations.read"], group: "Organizations" },
    { label: "Users", href: "/users/", icon: "users", permissions: ["users.read"], group: "People" },
  ] },
  { id: "telephony", label: "Telephony", icon: "handsetLoop", collapsible: true, description: "Extensions, calls, trunks, routing, voicemail, menus, groups and paging.", items: [
    { label: "Extensions", href: "/extensions/", icon: "phone", permissions: ["extensions.read"], group: "Phones and calls" },
    { label: "Active Calls", href: "/calls/", icon: "activity", permissions: ["calls.read"], group: "Phones and calls" },
    { label: "SIP Trunks", href: "/trunks/", icon: "trunk", permissions: ["trunks.read"], group: "Routing" },
    { label: "Inbound Routes", href: "/routing/inbound/", icon: "arrowIn", permissions: ["routing.read"], group: "Routing" },
    { label: "Outbound Routes", href: "/routing/outbound/", icon: "arrowOut", permissions: ["routing.read"], group: "Routing" },
    { label: "Time Conditions", href: "/routing/time-conditions/", icon: "clock", permissions: ["routing.read"], group: "Routing" },
    { label: "Classes of Service", href: "/routing/classes-of-service/", icon: "shield", permissions: ["routing.read"], group: "Routing" },
    { label: "Registrations", href: "/registrations/", icon: "device", permissions: ["extensions.read"], group: "Phones and calls" },
    { label: "Voicemail", href: "/voicemail/", icon: "voicemail", permissions: ["voicemail.read"], group: "Call handling" },
    { label: "IVR Menus", href: "/ivr/", icon: "ivr", permissions: ["ivr.read"], group: "Call handling" },
    { label: "Audio", href: "/prompts/", icon: "audio", permissions: ["ivr.read"], group: "Audio" },
    { label: "Hold Music", href: "/hold-music/", icon: "audio", permissions: ["ivr.read"], group: "Audio" },
    { label: "Ring Groups", href: "/ring-groups/", icon: "group", permissions: ["groups.read"], group: "Call handling" },
    { label: "Call Queues", href: "/queues/", icon: "queue", permissions: ["groups.read"], group: "Call handling" },
    { label: "Pickup Groups", href: "/pickup-groups/", icon: "phone", permissions: ["groups.read"], group: "Call handling" },
    { label: "Feature Codes", href: "/feature-codes/", icon: "key", permissions: ["extensions.read"], group: "Call handling" },
    { label: "Paging Zones", href: "/paging-zones/", icon: "megaphone", permissions: ["paging.read"], group: "Paging and bells" },
    { label: "Pages", href: "/paging/", icon: "megaphone", permissions: ["paging.read"], group: "Paging and bells" },
    { label: "Calendars", href: "/calendars/", icon: "clock", permissions: ["bells.read"], group: "Paging and bells" },
    { label: "Bell Schedules", href: "/bells/", icon: "clock", permissions: ["bells.read"], group: "Paging and bells" },
    { label: "Call History", href: "/call-history/", icon: "history", permissions: ["calls.history.read"], group: "History and reports" },
    { label: "Call Recording", href: "/recording/", icon: "record", permissions: ["recordings.read", "recordings.read_own", "recording_policies.read"], group: "History and reports" },
    { label: "Reports", href: "/reports/", icon: "activity", permissions: ["reports.read"], group: "History and reports" },
    ...PLANNED_FEATURES.map((f) => ({
      label: f.label, href: `/planned/?feature=${f.key}`, icon: f.icon, planned: { milestone: f.milestone }, group: "Coming later",
    })),
  ] },
  { id: "provisioning", label: "Provisioning", icon: "device", description: "Phones, their profiles, configuration templates and firmware.", items: [
    { label: "Devices", href: "/devices/", icon: "device", permissions: ["devices.read"], group: "Phones" },
    { label: "Device Profiles", href: "/device-profiles/", icon: "settings", permissions: ["devices.read"], group: "Phones" },
    { label: "Templates", href: "/provisioning/", icon: "template", permissions: ["provisioning.read"], group: "Configuration" },
    { label: "Firmware", href: "/firmware/", icon: "update", permissions: ["provisioning.read"], group: "Configuration" },
  ] },
  { id: "modules", label: "Modules", icon: "modules", description: "Pages added by installed modules.", items: [] },
  { id: "system", label: "System", icon: "settings", description: "Health, alerts, diagnostics, the telephony engine, high availability, the firewall, sign-in, integrations, updates, modules, audit and settings.", items: [
    { label: "Health", href: "/system/health/", icon: "health", permissions: ["system.health.read"], group: "Status" },
    { label: "Telephony Engine", href: "/system/telephony/", icon: "server", permissions: ["config.read"], group: "Platform" },
    { label: "High Availability", href: "/system/ha/", icon: "ha", permissions: ["ha.read"], group: "Platform" },
    { label: "Emergency Calling", href: "/system/emergency/", icon: "alert", permissions: ["emergency.read"], group: "Status" },
    { label: "Diagnostics", href: "/system/diagnostics/", icon: "search", permissions: ["diagnostics.read"], group: "Status" },
    { label: "Updates", href: "/updates/", icon: "update", permissions: ["updates.read"], group: "Software" },
    { label: "Backups", href: "/system/backups/", icon: "database", permissions: ["backups.read"], group: "Software" },
    { label: "Module Manager", href: "/modules/", icon: "modules", permissions: ["modules.read"], group: "Software" },
    { label: "Audit Log", href: "/audit/", icon: "audit", permissions: ["audit.read"], group: "Status" },
    { label: "Alerts", href: "/system/alerts/", icon: "alert", permissions: ["alerts.read"], group: "Status" },
    { label: "Firewall", href: "/system/firewall/", icon: "shield", permissions: ["firewall.read"], group: "Security" },
    { label: "Sign-in", href: "/system/sign-in/", icon: "key", permissions: ["sso.read"], group: "Security" },
    { label: "Integrations", href: "/system/integrations/", icon: "external", permissions: ["integrations.read", "webhooks.read"], group: "Platform" },
    { label: "Central console", href: "/system/central/", icon: "server", permissions: ["central.read"], group: "Platform" },
    { label: "Central management", href: "/system/membership/", icon: "ha", permissions: ["system.settings.read"], group: "Platform" },
    { label: "Settings", href: "/settings/", icon: "settings", group: "Settings" },
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

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

/** Items split into flyout columns, in the order each group first appears. */
export function groupItems(items: NavItem[]): NavGroup[] {
  const groups: NavGroup[] = [];
  for (const item of items) {
    const label = item.group ?? null;
    let g = groups.find((x) => x.label === label);
    if (!g) groups.push((g = { label, items: [] }));
    g.items.push(item);
  }
  return groups;
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

/** The section and item of the current route, for the rail highlight and the breadcrumb. */
export function activeLocation(sections: NavSection[], pathname: string, search = ""): { section: NavSection; item: NavItem } | null {
  let best: { section: NavSection; item: NavItem; length: number } | null = null;
  for (const section of sections) {
    for (const item of section.items) {
      if (!isActive(item.href, pathname, search)) continue;
      const length = item.href.length;
      if (!best || length > best.length) best = { section, item, length };
    }
  }
  return best ? { section: best.section, item: best.item } : null;
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
