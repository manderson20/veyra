"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Badge, Card, EmptyState, Icon, LoadingState, PageHeader } from "@/components/ui";
import { PLANNED_FEATURES, plannedFeature } from "@/lib/nav";

function Planned() {
  const feature = plannedFeature(useSearchParams().get("feature"));
  if (!feature) {
    return (
      <div className="stack">
        <PageHeader title="Coming later" description="Telephony features planned for upcoming milestones." />
        <Card flush>
          <ul className="list-plain">
            {PLANNED_FEATURES.map((f) => (
              <li key={f.key} className="list-row">
                <Link href={`/planned/?feature=${f.key}`} className="row"><Icon name={f.icon} /> {f.label}</Link>
                <Badge tone="outline">{f.milestone ? `Milestone ${f.milestone}` : "Planned"}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    );
  }
  return (
    <div className="stack">
      <PageHeader title={feature.label} description="This feature is not available yet." />
      <Card>
        <EmptyState icon={feature.icon} title={`${feature.label} is coming ${feature.milestone ? `in Milestone ${feature.milestone}` : "in a later milestone"}`}
          action={<Link href="/planned/" className="btn btn--secondary">See all planned features</Link>}>
          <p>{feature.summary}</p>
          <p className="subtle" style={{ marginTop: 10 }}>
            Veyra only shows controls for features that work. This page will be replaced by the real feature when it ships.
          </p>
        </EmptyState>
      </Card>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingState />}><Planned /></Suspense>;
}
