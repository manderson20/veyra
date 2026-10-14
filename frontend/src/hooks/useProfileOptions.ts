// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import type { CatalogModels, FirmwareImage, Page, PagingZone, Site, TemplateDetail, TemplateSummary } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

/** Reference data the device and profile forms need for one organization. */
export function useProfileOptions(organizationId: string, templateKey?: string) {
  const templates = useApiData<{ items: TemplateSummary[] }>("/provisioning/templates");
  const template = useApiData<TemplateDetail>(templateKey ? `/provisioning/templates/${encodeURIComponent(templateKey)}` : null);
  const zones = useApiData<Page<PagingZone>>(organizationId ? "/paging-zones" : null, { organization_id: organizationId, limit: 100 });
  const sites = useApiData<Page<Site>>(organizationId ? "/sites" : null, { organization_id: organizationId, limit: 200 });
  const firmware = useApiData<{ items: FirmwareImage[] }>("/provisioning/firmware");
  const models = useApiData<CatalogModels>("/provisioning/models");
  return {
    templates: templates.data?.items ?? [],
    template: template.data ?? null,
    zones: zones.data?.items ?? [],
    sites: sites.data?.items ?? [],
    firmware: firmware.data?.items ?? [],
    manufacturers: models.data?.manufacturers ?? [],
    loading: templates.loading || zones.loading || sites.loading || firmware.loading,
  };
}
