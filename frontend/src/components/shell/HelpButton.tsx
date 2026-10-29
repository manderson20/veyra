// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui";
import { canSeeAdminGuides, guidesForPath } from "@/lib/help";
import { useSession } from "@/hooks/useSession";

/** The top bar's Help link: straight to this page's guide when there is
 *  one, otherwise to the list of guides. */
export function HelpButton() {
  const pathname = usePathname();
  const { session } = useSession();
  const guides = session ? guidesForPath(pathname, canSeeAdminGuides(session)) : [];
  const guide = pathname.startsWith("/help") ? undefined : guides[0];
  const href = guide ? `/help/${guide.slug}/` : "/help/";
  const label = guide ? `Help: ${guide.title}` : "Help";
  return (
    <Link href={href} className="btn btn--ghost btn--sm topbar__help" title={label} aria-label={label}>
      <Icon name="help" size={16} />
      <span className="topbar__help-text">{guide ? "How do I…?" : "Help"}</span>
    </Link>
  );
}
