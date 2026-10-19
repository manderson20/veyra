// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { CallHandlingCard } from "@/components/extensions/CallHandlingCard";
import { FollowMeCard } from "@/components/extensions/FollowMeCard";
import { MyVoicemailCard } from "@/components/account/MyVoicemailCard";
import { VoicemailBoxPanel } from "@/components/voicemail/VoicemailBoxPanel";
import { Badge, Callout, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/ui";
import type { MyExtension, MyVoicemail } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";

interface MyFeatureCodes {
  codes: { key: string; label: string; description: string; code: string; takes_number: boolean }[];
  fixed: Record<string, string>;
}

/** The user's own phone (docs/CALL_FEATURES.md §3; the first slice of the Milestone 20 portal). */
export default function MyPhonePage() {
  const exts = useApiData<MyExtension[]>("/me/extensions");
  const codes = useApiData<MyFeatureCodes>("/me/feature-codes");
  const boxes = useApiData<MyVoicemail[]>("/me/voicemail");
  if (exts.error) return <ErrorState title="Could not load your phone" error={exts.error} onRetry={exts.reload} />;
  if (!exts.data) return <LoadingState />;
  return (
    <div className="stack">
      <PageHeader title="My Phone" description="Your own extensions: switch Do Not Disturb, set where calls go when you are busy or away, ring other numbers with your phone, and manage your voicemail. Changes take effect at once unless noted." />
      {exts.data.length === 0 ? (
        <Card><EmptyState icon="phone" title="No phone is assigned to you">An administrator assigns an extension to your account under Telephony → Extensions.</EmptyState></Card>
      ) : exts.data.map((x) => (
        <section key={x.id} className="stack" aria-label={`Extension ${x.number}`}>
          <Card title={`Extension ${x.number}`} subtitle={x.display_name}>
            <div className="row" style={{ gap: 8 }}>
              {x.registration === null ? <Badge tone="neutral">Phone status unknown</Badge> : x.registration.registered ? <Badge tone="ok">Phone registered</Badge> : <Badge tone="danger">Phone not registered</Badge>}
              {!x.is_enabled ? <Badge tone="warn">Disabled</Badge> : null}
              {x.registration?.contacts?.[0]?.user_agent ? <span className="subtle">{x.registration.contacts[0].user_agent}</span> : null}
            </div>
          </Card>
          <div className="grid grid--2">
            <CallHandlingCard base={`/me/extensions/${x.id}`} editable={x.is_enabled} ringTime={false} />
            <FollowMeCard base={`/me/extensions/${x.id}`} editable={x.is_enabled} />
          </div>
        </section>
      ))}
      {(boxes.data ?? []).map((b) => (
        <Card key={b.id} title={b.shared ? `Voicemail: ${b.name}` : `Voicemail ${b.number}`}
          subtitle={b.shared ? `Shared inbox ${b.number}; you are one of its members.` : "Your messages and greetings, as the phone has them. Changes here change what *97 plays."}>
          <VoicemailBoxPanel base={`/me/voicemail/${b.id}`} idBase={`my-vm-${b.id}`}
            targets={(boxes.data ?? []).filter((o) => o.id !== b.id).map((o) => ({ id: o.id, label: `${o.number} ${o.name}` }))} />
        </Card>
      ))}
      <MyVoicemailCard />
      {codes.data?.codes.length ? (
        <Card title="Codes you can dial" subtitle="Dial these from your phone; some take a number after the code.">
          <ul className="list">
            {codes.data.codes.map((c) => <li key={c.key}><span className="mono">{c.code}{c.takes_number ? "…" : ""}</span> {c.label}{c.description ? <span className="subtle"> · {c.description}</span> : null}</li>)}
          </ul>
          <p className="subtle">Always available: {Object.entries(codes.data.fixed).map(([code, what], i) => <span key={code}>{i ? ", " : ""}<span className="mono">{code}</span> {what}</span>)}.</p>
        </Card>
      ) : null}
      <Callout tone="info" title="Coming later">Greetings, phone keys and speed dials from this page, personal contacts and your call history follow in this milestone.</Callout>
    </div>
  );
}
