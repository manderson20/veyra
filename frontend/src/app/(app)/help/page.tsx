// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useState } from "react";
import { Card, EmptyState, Icon, PageHeader, SearchInput } from "@/components/ui";
import { canSeeAdminGuides, searchGuides, SECTIONS, visibleGuides, WIKI_URL } from "@/lib/help";
import { useSession } from "@/hooks/useSession";

export default function HelpPage() {
  const { session } = useSession();
  const [query, setQuery] = useState("");
  const admin = session ? canSeeAdminGuides(session) : false;
  const guides = searchGuides(visibleGuides(admin), query);

  return (
    <div className="stack">
      <PageHeader
        title="Help"
        description="Step-by-step guides for setting up and using Veyra. The same guides are on the project wiki."
        actions={<a className="btn btn--ghost" href={WIKI_URL} target="_blank" rel="noreferrer">Open the wiki <Icon name="external" size={12} /></a>}
      />
      <div style={{ maxWidth: 480 }}>
        <SearchInput value={query} onChange={setQuery} placeholder="Search the guides" label="Search the guides" />
      </div>
      {guides.length === 0 ? <EmptyState title="No guide matches">Try other words, or look on the wiki.</EmptyState> : null}
      {SECTIONS.map((section) => {
        const items = guides.filter((g) => g.section === section);
        if (!items.length) return null;
        return (
          <Card key={section} title={section}>
            <ul className="help-list">
              {items.map((g) => (
                <li key={g.slug}>
                  <Link href={`/help/${g.slug}/`}><strong>{g.title}</strong></Link>
                  <span className="subtle">{g.summary}</span>
                </li>
              ))}
            </ul>
          </Card>
        );
      })}
    </div>
  );
}
