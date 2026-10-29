// SPDX-License-Identifier: AGPL-3.0-or-later
/* The help guides (docs/guides, built by tools/guides.py): the same text
 * as the GitHub wiki. Every page loads only the index (titles and pages);
 * the text is in help-content.ts, loaded by the Help pages. */

import data from "@/generated/guides-index.json";

export interface GuideMeta {
  slug: string;
  title: string;
  summary: string;
  audience: "admin" | "user";
  section: string;
  reviewed: string;
  reviewed_date: string | null;
  pages: string[];
  wiki: string;
}

export const GUIDES = data.guides as GuideMeta[];
export const SECTIONS = data.sections;
export const WIKI_URL = data.wiki;

/** Administrators' guides are shown to people who can manage something;
 *  everyone sees the guides for users. */
export function canSeeAdminGuides(session: { is_platform_admin: boolean; permissions: string[] }): boolean {
  return session.is_platform_admin || session.permissions.some((p) => p === "*" || p.endsWith(".write") || p === "extensions.read");
}

export function visibleGuides(admin: boolean): GuideMeta[] {
  return GUIDES.filter((g) => admin || g.audience === "user");
}

export function guideBySlug(slug: string): GuideMeta | undefined {
  return GUIDES.find((g) => g.slug === slug);
}

/** The guides for a page: those naming it, or the closest page above it. */
export function guidesForPath(pathname: string, admin: boolean): GuideMeta[] {
  const path = pathname.endsWith("/") ? pathname : `${pathname}/`;
  let best = 0;
  let found: GuideMeta[] = [];
  for (const g of visibleGuides(admin)) {
    for (const p of g.pages) {
      if (p !== "/" && path.startsWith(p)) {
        if (p.length > best) {
          best = p.length;
          found = [g];
        } else if (p.length === best && !found.includes(g)) {
          found.push(g);
        }
      }
    }
  }
  return found;
}
