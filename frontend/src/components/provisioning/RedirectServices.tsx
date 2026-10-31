// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { CopyButton } from "@/components/common/CopyButton";
import { Card } from "@/components/ui";
import { buttonClass } from "@/components/ui/Button";
import { API_BASE } from "@/lib/api";
import { sameBrand } from "@/lib/brands";

const REDIRECT_VENDORS: { name: string; service: string; how: string }[] = [
  { name: "Yealink", service: "Yealink RPS (Redirection and Provisioning Service)", how: "Add the MACs in the RPS portal with the provisioning URL as the server; the phones then find Veyra at first boot." },
  { name: "Poly", service: "Poly ZTP (Zero Touch Provisioning) in Poly Lens", how: "Register the MACs with the provisioning URL; or use DHCP option 160 on the voice VLAN." },
  { name: "Algo", service: "DHCP option 66 (Algo has no cloud redirect)", how: "Give the voice VLAN option 66 with the provisioning URL, or set the static server once in the device's web page." },
  { name: "Grandstream", service: "Grandstream GDMS", how: "Import the MACs in GDMS with the provisioning URL as the config server." },
];

/** A brand's redirect service (docs/PROVISIONING_BREADTH.md §6): how its new
 * phones find Veyra, and the MAC export to register them in bulk. */
export function RedirectServices({ brand }: { brand: string }) {
  const v = REDIRECT_VENDORS.find((x) => sameBrand(x.name, brand));
  const url = typeof window === "undefined" ? "/provisioning/" : `${window.location.origin}/provisioning/`;
  return (
    <Card title="Connect new phones" subtitle="New phones find Veyra through the vendor's redirect service or DHCP.">
      <div className="stack stack--sm">
        <p>Provisioning URL: <span className="mono">{url}</span> <CopyButton text={url} /></p>
        <p className="subtle">Phones authenticate with their organization&apos;s enrollment credential (Directory → Organizations → the organization → Phone provisioning) the first time, then with their own.</p>
        {v ? (
          <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
            <span style={{ minWidth: 0 }}>
              <span className="table__primary" style={{ display: "block" }}>{v.service}</span>
              <span className="table__secondary">{v.how}</span>
            </span>
            <a className={buttonClass("secondary", "sm")} href={`${API_BASE}/devices/export.csv?manufacturer=${encodeURIComponent(v.name)}`} download>Export {v.name} MACs</a>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
