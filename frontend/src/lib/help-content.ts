// SPDX-License-Identifier: AGPL-3.0-or-later
/* The guides' text, for the Help pages only (the rest of the interface
 * loads the index in help.ts). */

import data from "@/generated/guides.json";
import type { GuideMeta } from "./help";

export interface Guide extends GuideMeta {
  headings: { id: string; title: string }[];
  html: string;
}

export const GUIDE_TEXT = data.guides as Guide[];

export function guideText(slug: string): Guide | undefined {
  return GUIDE_TEXT.find((g) => g.slug === slug);
}

/** Guides matching every word, those matching in the title or summary first. */
export function searchGuides(guides: GuideMeta[], query: string): GuideMeta[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return guides;
  const full = new Map(GUIDE_TEXT.map((g) => [g.slug, g]));
  const text = (g: GuideMeta) => {
    const f = full.get(g.slug);
    return `${g.title} ${g.summary} ${f ? f.headings.map((h) => h.title).join(" ") + " " + f.html.replace(/<[^>]+>/g, " ") : ""}`.toLowerCase();
  };
  return guides
    .map((g) => ({ g, t: text(g), title: `${g.title} ${g.summary}`.toLowerCase() }))
    .filter(({ t }) => words.every((w) => t.includes(w)))
    .sort((a, b) => Number(words.every((w) => b.title.includes(w))) - Number(words.every((w) => a.title.includes(w))))
    .map(({ g }) => g);
}
