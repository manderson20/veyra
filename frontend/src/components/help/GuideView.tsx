// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import type { MouseEvent } from "react";
import { Badge, Callout, Icon, PageHeader } from "@/components/ui";
import { canSeeAdminGuides } from "@/lib/help";
import { guideText } from "@/lib/help-content";
import { useSession } from "@/hooks/useSession";

/** One guide: its text (built from docs/guides), when it was last reviewed,
 *  and its sections. Links inside stay in the single-page app. */
export function GuideView({ slug }: { slug: string }) {
  const router = useRouter();
  const { session } = useSession();
  const guide = guideText(slug);
  if (!guide) return <Callout tone="warn" title="No such guide">It may have been renamed. See the list on the Help page.</Callout>;
  const forAdmins = guide.audience === "admin";
  const hidden = forAdmins && session && !canSeeAdminGuides(session);

  const follow = (e: MouseEvent<HTMLElement>) => {
    const a = (e.target as HTMLElement).closest("a");
    const href = a?.getAttribute("href");
    if (!a || !href || !href.startsWith("/") || a.target || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    router.push(href);
  };

  return (
    <div className="stack">
      <PageHeader
        title={guide.title}
        description={guide.summary}
        back={{ href: "/help/", label: "Help" }}
        actions={<a className="btn btn--ghost btn--sm" href={guide.wiki} target="_blank" rel="noreferrer">On the wiki <Icon name="external" size={12} /></a>}
      />
      <p className="subtle row" style={{ gap: 8, flexWrap: "wrap", margin: 0 }}>
        <Badge tone="neutral">{forAdmins ? "For administrators" : "For everyone"}</Badge>
        <span>
          Reviewed for Veyra {guide.reviewed}
          {guide.reviewed_date ? ` (${guide.reviewed_date})` : ""}
          {session?.version && session.version !== guide.reviewed ? `; still current in ${session.version}` : ""}.
        </span>
      </p>
      {hidden ? <Callout tone="neutral">This guide is for administrators; the pages it describes may not be open to you.</Callout> : null}
      <div className="help-layout">
        {guide.headings.length > 2 ? (
          <nav className="help-toc" aria-label="On this page">
            <strong>On this page</strong>
            <ol>
              {guide.headings.map((h) => (
                <li key={h.id}><a href={`#${h.id}`}>{h.title}</a></li>
              ))}
            </ol>
          </nav>
        ) : null}
        {/* The HTML is built from the guides in the repository (tools/guides.py escapes their text). */}
        <article className="help-article" onClick={follow} dangerouslySetInnerHTML={{ __html: guide.html }} />
      </div>
    </div>
  );
}
