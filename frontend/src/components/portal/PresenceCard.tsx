// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Badge, Button, Callout, Card, SelectField, TextField, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Presence, PresenceRule, PresenceState } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { useOnChange } from "@/hooks/useOnChange";

export const PRESENCE_TONE: Record<PresenceState, "ok" | "warn" | "danger" | "neutral" | "info"> = {
  available: "ok", away: "warn", busy: "danger", meeting: "danger", lunch: "warn", out: "neutral",
};

interface PortalPrefs { presence_rules: Record<string, PresenceRule> }
interface Prefs { companion: unknown; portal: PortalPrefs; updated_at: string | null }

/** The user's presence for one extension, with the automatic actions per state (docs/USER_PORTAL.md §7). */
export function PresenceCard({ base, editable = true }: { base: string; editable?: boolean }) {
  const toast = useToast();
  const presence = useApiData<Presence>(`${base}/presence`);
  const prefs = useApiData<Prefs>("/me/preferences");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [rules, setRules] = useState<Record<string, PresenceRule>>({});
  const [error, setError] = useState<string | null>(null);
  useOnChange(presence.data, (p) => { if (p) setMessage(p.message ?? ""); });
  useOnChange(prefs.data, (p) => { if (p) setRules(p.portal.presence_rules ?? {}); });

  const setState = async (state: PresenceState) => {
    setBusy(true);
    setError(null);
    try {
      const out = await api.put<Presence>(`${base}/presence`, { state, message: message.trim() || null });
      presence.setData(out);
      const did = Object.keys(out.applied).filter((k) => k === "dnd" || k === "cf_always");
      toast.success(`You are ${out.label.toLowerCase()}`, did.length ? `Applied: ${did.map((k) => k === "dnd" ? (out.applied.dnd ? "Do Not Disturb on" : "Do Not Disturb off") : (out.applied.cf_always ? `forward to ${out.applied.cf_always}` : "forward cleared")).join(", ")}.` : undefined);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const saveRules = async () => {
    if (!prefs.data) return;
    setBusy(true);
    setError(null);
    try {
      const clean: Record<string, PresenceRule> = {};
      for (const [k, r] of Object.entries(rules)) {
        const rule: PresenceRule = {};
        if (r.dnd !== null && r.dnd !== undefined) rule.dnd = r.dnd;
        if (r.cf_always !== null && r.cf_always !== undefined) rule.cf_always = r.cf_always.trim();
        if (Object.keys(rule).length) clean[k] = rule;
      }
      prefs.setData(await api.put<Prefs>("/me/preferences", { companion: prefs.data.companion, portal: { presence_rules: clean } }));
      toast.success("Presence actions saved");
      setRulesOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const p = presence.data;
  return (
    <Card title="Presence" subtitle="What colleagues see in the directory and the portal. Each state can switch Do Not Disturb or a forward for you.">
      {presence.error ? <Callout tone="danger">{errorMessage(presence.error)}</Callout> : null}
      {p ? (
        <div className="stack stack--sm">
          <div className="row" style={{ flexWrap: "wrap" }}>
            {p.states.map((s) => (
              <Button key={s.key} size="sm" variant={p.state === s.key ? "primary" : "secondary"} disabled={!editable || busy} onClick={() => setState(s.key)}>{s.label}</Button>
            ))}
          </div>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <TextField label="Message (optional)" value={message} maxLength={60} placeholder="Back at 3" disabled={!editable || busy} onChange={(e) => setMessage(e.target.value)} />
            <Button size="sm" disabled={!editable || busy || message === (p.message ?? "")} onClick={() => setState(p.state)}>Save message</Button>
          </div>
          <p className="subtle" style={{ margin: 0 }}>Now: <Badge tone={PRESENCE_TONE[p.state]}>{p.label}</Badge>{p.message ? ` · ${p.message}` : ""}</p>
          {editable ? <div><Button size="sm" onClick={() => setRulesOpen((o) => !o)}>{rulesOpen ? "Hide automatic actions" : "Automatic actions…"}</Button></div> : null}
          {rulesOpen ? (
            <div className="stack stack--sm" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              {p.states.map((s) => {
                const r = rules[s.key] ?? {};
                const dndMode = r.dnd === true ? "on" : r.dnd === false ? "off" : "keep";
                const cfMode = r.cf_always === undefined || r.cf_always === null ? "keep" : r.cf_always === "" ? "clear" : "set";
                return (
                  <div key={s.key} className="row" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
                    <span style={{ minWidth: 130 }}><Badge tone={PRESENCE_TONE[s.key]}>{s.label}</Badge></span>
                    <SelectField label="Do Not Disturb" value={dndMode} options={[{ value: "keep", label: "Leave as it is" }, { value: "on", label: "Turn on" }, { value: "off", label: "Turn off" }]}
                      onChange={(e) => setRules((all) => ({ ...all, [s.key]: { ...all[s.key], dnd: e.target.value === "keep" ? null : e.target.value === "on" } }))} />
                    <SelectField label="Forward all calls" value={cfMode} options={[{ value: "keep", label: "Leave as it is" }, { value: "clear", label: "Clear the forward" }, { value: "set", label: "Forward to…" }]}
                      onChange={(e) => setRules((all) => ({ ...all, [s.key]: { ...all[s.key], cf_always: e.target.value === "keep" ? null : e.target.value === "clear" ? "" : (all[s.key]?.cf_always || " ") } }))} />
                    {cfMode === "set" ? <TextField label="Number" inputMode="tel" value={(r.cf_always ?? "").trim()} onChange={(e) => setRules((all) => ({ ...all, [s.key]: { ...all[s.key], cf_always: e.target.value || " " } }))} /> : null}
                  </div>
                );
              })}
              <p className="subtle" style={{ margin: 0 }}>Actions run each time you pick the state; leaving a setting as it is changes nothing.</p>
              <div className="form-actions"><Button variant="primary" loading={busy} onClick={saveRules}>Save actions</Button></div>
            </div>
          ) : null}
          {error ? <Callout tone="danger">{error}</Callout> : null}
        </div>
      ) : <p className="subtle">Loading…</p>}
    </Card>
  );
}
