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
  { id: "overview", label: "Overview", icon: "dashboard", description: "System status, resources and telephony activity at a glance.", items: [
    { label: "Dashboard", href: "/", icon: "dashboard", permissions: ["system.health.read"] },
  ] },
  { id: "directory", label: "Directory", icon: "users", description: "Organizations, their sites and the people who sign in.", items: [
    { label: "Organizations", href: "/organizations/", icon: "building", permissions: ["organizations.read"] },
    { label: "Sites", href: "/sites/", icon: "building", permissions: ["organizations.read"] },
    { label: "Users", href: "/users/", icon: "users", permissions: ["users.read"] },
  ] },
  { id: "telephony", label: "Telephony", icon: "phone", collapsible: true, description: "Extensions, calls, trunks, routing, voicemail, menus, groups and paging.", items: [
    { label: "Extensions", href: "/extensions/", icon: "phone", permissions: ["extensions.read"] },
    { label: "Active Calls", href: "/calls/", icon: "activity", permissions: ["calls.read"] },
    { label: "SIP Trunks", href: "/trunks/", icon: "trunk", permissions: ["trunks.read"] },
    { label: "Inbound Routes", href: "/routing/inbound/", icon: "arrowIn", permissions: ["routing.read"] },
    { label: "Outbound Routes", href: "/routing/outbound/", icon: "arrowOut", permissions: ["routing.read"] },
    { label: "Time Conditions", href: "/routing/time-conditions/", icon: "clock", permissions: ["routing.read"] },
    { label: "Voicemail", href: "/voicemail/", icon: "voicemail", permissions: ["voicemail.read"] },
    { label: "IVR Menus", href: "/ivr/", icon: "ivr", permissions: ["ivr.read"] },
    { label: "Audio", href: "/prompts/", icon: "audio", permissions: ["ivr.read"] },
    { label: "Ring Groups", href: "/ring-groups/", icon: "group", permissions: ["groups.read"] },
    { label: "Call Queues", href: "/queues/", icon: "queue", permissions: ["groups.read"] },
    { label: "Pickup Groups", href: "/pickup-groups/", icon: "phone", permissions: ["groups.read"] },
    { label: "Paging Zones", href: "/paging-zones/", icon: "megaphone", permissions: ["paging.read"] },
    ...PLANNED_FEATURES.map((f) => ({
      label: f.label, href: `/planned/?feature=${f.key}`, icon: f.icon, planned: { milestone: f.milestone },
    })),
  ] },
  { id: "provisioning", label: "Provisioning", icon: "device", description: "Phones, their profiles, configuration templates and firmware.", items: [
    { label: "Devices", href: "/devices/", icon: "device", permissions: ["devices.read"] },
    { label: "Device Profiles", href: "/device-profiles/", icon: "settings", permissions: ["devices.read"] },
    { label: "Templates", href: "/provisioning/", icon: "template", permissions: ["provisioning.read"] },
    { label: "Firmware", href: "/firmware/", icon: "update", permissions: ["provisioning.read"] },
  ] },
  { id: "modules", label: "Modules", icon: "modules", description: "Pages added by installed modules.", items: [] },
  { id: "system", label: "System", icon: "settings", description: "Health, the telephony engine, high availability, updates, modules, audit and settings.", items: [
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
