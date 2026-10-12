"use client";

import type { Organization, Page } from "@/lib/types";
import { useApiData } from "./useApiData";

/** Organizations the caller can see (first 200), for pickers. */
export function useOrganizationOptions(enabled = true) {
  const r = useApiData<Page<Organization>>(enabled ? "/organizations" : null, { limit: 200 });
  return { organizations: r.data?.items ?? [], loading: r.loading, error: r.error };
}
