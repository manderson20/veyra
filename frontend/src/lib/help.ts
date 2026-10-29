// SPDX-License-Identifier: AGPL-3.0-or-later
/* The help guides (docs/guides, built by tools/guides.py into
 * src/generated/guides.json): the same text as the GitHub wiki. */

import data from "@/generated/guides.json";

export interface Guide {
  slug: string;
  title: string;
  summary: string;
  audience: "admin" | "user";
  section: string;
  reviewed: string;
  reviewed_date: string | null;
  pages: string[];
  headings: { id: string; title: string }[];
  wiki: string;
  html: string;
}

export const GUIDES = data.guides as Guide[];
export const SECTIONS = data.sections;
export const WIKI_URL = data.wiki;

/** Administrators' guides are shown to people who can manage something;
 *  everyone sees the guides for users. */
export function canSeeAdminGuides(session: { is_platform_admin: boolean; permissions: string[] }): boolean {
  return session.is_platform_admin || session.permissions.some((p) => p === "*" || p.endsWith(".write") || p === "extensions.read");
}

export function visibleGuides(admin: boolean): Guide[] {
  return GUIDES.filter((g) => admin || g.audience === "user");
}

export function guideBySlug(slug: string): Guide | undefined {
  return GUIDES.find((g) => g.slug === slug);
}

/** The guides for a page: those naming it, or the closest page above it. */
export function guidesForPath(pathname: string, admin: boolean): Guide[] {
  const path = pathname.endsWith("/") ? pathname : `${pathname}/`;
  let best = 0;
  let found: Guide[] = [];
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

export function searchGuides(guides: Guide[], query: string): Guide[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return guides;
  const text = (g: Guide) => `${g.title} ${g.summary} ${g.headings.map((h) => h.title).join(" ")} ${g.html.replace(/<[^>]+>/g, " ")}`.toLowerCase();
  return guides
    .map((g) => ({ g, t: text(g), title: `${g.title} ${g.summary}`.toLowerCase() }))
    .filter(({ t }) => words.every((w) => t.includes(w)))
    .sort((a, b) => Number(words.every((w) => b.title.includes(w))) - Number(words.every((w) => a.title.includes(w))))
    .map(({ g }) => g);
}
