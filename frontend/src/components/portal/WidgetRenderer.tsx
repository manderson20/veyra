// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { CallHandlingCard } from "@/components/extensions/CallHandlingCard";
import { FollowMeCard } from "@/components/extensions/FollowMeCard";
import { ColleaguesCard } from "@/components/portal/ColleaguesCard";
import { ContactsCard } from "@/components/portal/ContactsCard";
import { FaxCard } from "@/components/portal/FaxCard";
import { PhoneKeysCard } from "@/components/portal/PhoneKeysCard";
import { PresenceCard } from "@/components/portal/PresenceCard";
import { RecentCallsCard } from "@/components/portal/RecentCallsCard";
import { Badge, Callout, Card } from "@/components/ui";
import { VoicemailBoxPanel } from "@/components/voicemail/VoicemailBoxPanel";
import type { MyExtension, MyVoicemail } from "@/lib/types";
import type { Placed } from "@/portal/layout";
import { useApiData } from "@/hooks/useApiData";

interface MyFeatureCodes {
  codes: { key: string; label: string; description: string; code: string; takes_number: boolean }[];
  fixed: Record<string, string>;
}

/** Resolve a widget instance ("first", an id) to one of the user's extensions or boxes. */
export function pickInstance<T extends { id: string }>(items: T[], instance: string): T | undefined {
  if (instance === "first" || instance === "default") return items[0];
  return items.find((i) => i.id === instance) ?? items[0];
}

/** The widget for a placed entry of the layout (docs/USER_PORTAL.md §10). */
export function WidgetRenderer({ placed, extensions, boxes, announcement }: { placed: Placed; extensions: MyExtension[]; boxes: MyVoicemail[]; announcement?: string | null }) {
  const x = pickInstance(extensions, placed.instance);
  switch (placed.key) {
    case "phone":
      if (!x) return <Card title="My phone"><p className="subtle">No phone is assigned to you.</p></Card>;
      return (
        <Card title={`Extension ${x.number}`} subtitle={x.display_name}>
          <div className="stack stack--sm">
            <div className="row" style={{ gap: 8 }}>
              {x.registration === null ? <Badge tone="neutral">Phone status unknown</Badge> : x.registration.registered ? <Badge tone="ok">Phone registered</Badge> : <Badge tone="danger">Phone not registered</Badge>}
              {!x.is_enabled ? <Badge tone="warn">Disabled</Badge> : null}
            </div>
            <CallHandlingCard base={`/me/extensions/${x.id}`} editable={x.is_enabled} ringTime={false} />
            <FollowMeCard base={`/me/extensions/${x.id}`} editable={x.is_enabled} />
          </div>
        </Card>
      );
    case "presence":
      if (!x) return null;
      return <PresenceCard base={`/me/extensions/${x.id}`} editable={x.is_enabled} />;
    case "voicemail": {
      const b = pickInstance(boxes, placed.instance);
      if (!b) return <Card title="Voicemail"><p className="subtle">You have no voicemail box.</p></Card>;
      return (
        <Card title={b.shared ? `Voicemail: ${b.name}` : `Voicemail ${b.number}`}>
          <VoicemailBoxPanel base={`/me/voicemail/${b.id}`} idBase={`vm-${b.id}`} email={b.email} targets={boxes.filter((o) => o.id !== b.id).map((o) => ({ id: o.id, label: `${o.number} ${o.name}` }))} />
        </Card>
      );
    }
    case "calls":
      return <RecentCallsCard extensions={extensions} />;
    case "contacts":
      return <ContactsCard extensions={extensions} />;
    case "colleagues":
      return <ColleaguesCard extensions={extensions} />;
    case "keys":
      return <PhoneKeysCard />;
    case "codes":
      return <CodesCard />;
    case "fax":
      return <FaxCard />;
    case "announce":
      return (
        <Callout tone="info" title={String(placed.settings?.title ?? "From your administrators")}>
          {announcement ?? String(placed.settings?.text ?? "Nothing to announce right now.")}
        </Callout>
      );
    default:
      return <Card title={placed.key}><p className="subtle">This widget is not available in this version.</p></Card>;
  }
}

function CodesCard() {
  const codes = useApiData<MyFeatureCodes>("/me/feature-codes");
  if (!codes.data) return <Card title="Codes you can dial"><p className="subtle">Loading…</p></Card>;
  return (
    <Card title="Codes you can dial" subtitle="Dial these from your phone; some take a number after the code.">
      <ul className="list">
        {codes.data.codes.map((c) => <li key={c.key}><span className="mono">{c.code}{c.takes_number ? "…" : ""}</span> {c.label}{c.description ? <span className="subtle"> · {c.description}</span> : null}</li>)}
      </ul>
      <p className="subtle">Always available: {Object.entries(codes.data.fixed).map(([code, what], i) => <span key={code}>{i ? ", " : ""}<span className="mono">{code}</span> {what}</span>)}.</p>
    </Card>
  );
}
