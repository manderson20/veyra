// SPDX-License-Identifier: AGPL-3.0-or-later
import { GuideView } from "@/components/help/GuideView";
import { GUIDES } from "@/lib/help";

export function generateStaticParams() {
  return GUIDES.map((g) => ({ slug: g.slug }));
}

export default async function GuidePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <GuideView slug={slug} />;
}
