// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LoadingState } from "@/components/ui";

/** Device profiles became each brand's templates; old links land on the brands. */
export default function DeviceProfilesRedirect() {
  const router = useRouter();
  useEffect(() => router.replace("/provisioning/brands/"), [router]);
  return <LoadingState />;
}
