// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { EMPTY_DEFINITION, ReportBuilder } from "@/components/reports/Builder";
import { ReportsOverview } from "@/components/reports/Overview";
import { SavedReports } from "@/components/reports/SavedReports";
import { PageHeader, TabPanel, Tabs } from "@/components/ui";
import type { ReportDefinition, SavedReport } from "@/lib/types";

/** Telephony → Reports: the overview, the report builder and saved reports
    (docs/REPORTING.md §5, docs/REPORT_BUILDER.md). */
export default function ReportsPage() {
  const [tab, setTab] = useState("overview");
  const [definition, setDefinition] = useState<ReportDefinition>(EMPTY_DEFINITION);
  const [saved, setSaved] = useState<SavedReport | null>(null);
  const [version, setVersion] = useState(0);
  const open = (r: SavedReport) => {
    setSaved(r);
    setDefinition({ ...EMPTY_DEFINITION, ...r.definition, filters: { ...EMPTY_DEFINITION.filters, ...r.definition.filters }, organization_id: r.organization_id });
    setTab("build");
  };
  return (
    <div className="stack">
      <PageHeader title="Reports" description="An overview of the phone system, and reports you build, save and have emailed." />
      <Tabs idBase="rep" active={tab} onChange={setTab}
        tabs={[{ id: "overview", label: "Overview" }, { id: "build", label: saved ? `Build: ${saved.name}` : "Build" }, { id: "saved", label: "Saved" }]} />
      <TabPanel idBase="rep" id="overview" active={tab}><ReportsOverview /></TabPanel>
      <TabPanel idBase="rep" id="build" active={tab}>
        <ReportBuilder definition={definition} setDefinition={setDefinition} saved={saved}
          onSaved={(r) => { setSaved(r); setVersion((v) => v + 1); }} />
        {saved ? <p className="subtle"><button type="button" className="link" onClick={() => { setSaved(null); setDefinition(EMPTY_DEFINITION); }}>Start a new report</button></p> : null}
      </TabPanel>
      <TabPanel idBase="rep" id="saved" active={tab}><SavedReports onOpen={open} version={version} /></TabPanel>
    </div>
  );
}
