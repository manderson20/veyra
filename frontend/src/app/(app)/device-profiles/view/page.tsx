// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { LoadingState } from "@/components/ui";

function Redirect() {
  const router = useRouter();
  const id = useSearchParams().get("id") ?? "";
  useEffect(() => router.replace(`/provisioning/brands/template/?id=${encodeURIComponent(id)}`), [router, id]);
  return <LoadingState />;
}

/** A device profile's old address. */
export default function Page() {
  return <Suspense fallback={<LoadingState />}><Redirect /></Suspense>;
}
