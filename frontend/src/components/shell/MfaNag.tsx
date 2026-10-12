// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Callout } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { useSession } from "@/hooks/useSession";

/** Reminds a user whose role requires two-factor authentication to set it up during the grace window. */
export function MfaNag() {
  const { session } = useSession();
  const pathname = usePathname();
  if (!session || session.mfa.enabled || !session.mfa.required || pathname.startsWith("/account")) return null;
  return (
    <div style={{ padding: "0 var(--space-6)", paddingTop: "var(--space-4)", maxWidth: "var(--content-max)", margin: "0 auto", width: "100%" }}>
      <Callout tone="warn" title="Two-factor authentication is required for your role">
        {session.mfa.grace_until ? <>You can keep signing in without it until {formatDateTime(session.mfa.grace_until)}. </> : null}
        <Link href="/account/#mfa">Set it up on your account page</Link>. It takes about a minute with an authenticator app on your phone.
      </Callout>
    </div>
  );
}
