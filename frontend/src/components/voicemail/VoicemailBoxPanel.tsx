// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { TabPanel, Tabs } from "@/components/ui";
import { GreetingsPanel } from "@/components/voicemail/GreetingsPanel";
import { VoicemailInbox, type ForwardTarget } from "@/components/voicemail/VoicemailInbox";

/** Messages and greetings of one box, as two tabs (My Phone and the Voicemail page). */
export function VoicemailBoxPanel({ base, idBase, targets, email, editable = true }: { base: string; idBase: string; targets: ForwardTarget[]; email?: string | null; editable?: boolean }) {
  const [tab, setTab] = useState("messages");
  return (
    <div className="stack stack--sm">
      <Tabs idBase={idBase} active={tab} onChange={setTab} tabs={[{ id: "messages", label: "Messages" }, { id: "greetings", label: "Greetings" }]} />
      <TabPanel idBase={idBase} id="messages" active={tab}><VoicemailInbox base={base} targets={targets} email={email} editable={editable} /></TabPanel>
      <TabPanel idBase={idBase} id="greetings" active={tab}><GreetingsPanel base={base} editable={editable} /></TabPanel>
    </div>
  );
}
