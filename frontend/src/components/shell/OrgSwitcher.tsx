// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { usePathname } from "next/navigation";
import { useApiData } from "@/hooks/useApiData";
import type { MyOrganizations } from "@/lib/types";
import { pathAfterSwitch, setWorkingOrg, workingOrg } from "@/lib/workingOrg";
import { Icon } from "@/components/ui";

/** The organization this tab works in (docs/MULTI_TENANCY_MSP.md §10a). Shown
 * only to users who can see more than one organization. */
export function OrgSwitcher() {
  const pathname = usePathname() ?? "/";
  const mine = useApiData<MyOrganizations>("/me/organizations");
  const d = mine.data;
  if (!d?.switcher) return null;
  const current = workingOrg();
  const known = d.organizations.some((o) => o.slug === current);
  const value = current && known ? current : "";
  const choose = (slug: string) => {
    setWorkingOrg(slug);
    // A full load: every list, the menu and the permissions follow the new organization.
    window.location.assign(pathAfterSwitch(pathname, slug));
  };
  return (
    <label className={["org-switch", value ? "org-switch--org" : "org-switch--system"].join(" ")} title="The organization you are working in">
      <Icon name={value ? "building" : "server"} size={16} />
      <span className="sr-only">Working in</span>
      <select className="org-switch__select" value={value} onChange={(e) => choose(e.target.value)}>
        {d.system || !value ? <option value="">{d.system ? "System (all organizations)" : "Choose an organization"}</option> : null}
        {d.organizations.map((o) => <option key={o.id} value={o.slug}>{o.name}</option>)}
      </select>
    </label>
  );
}
