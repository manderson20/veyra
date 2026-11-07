// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

/**
 * The configuration check window (docs/CONFIG_VERIFICATION.md §7.1). A save
 * that reaches phone files runs through `useConfigCheck().run(save)`: a
 * window with a progress bar opens while the check runs; a clean result says
 * so and waits for OK; findings are listed with the setting, the Veyra field
 * that fills it and what the setting accepts. Errors in the enforce mode stop
 * the save until someone with the override permission saves past them with a
 * reason. In the off mode no window appears.
 */

import { useCallback, useRef, useState } from "react";
import { Badge, Button, Callout, Checkbox, Dialog, SelectField, TextArea, useToast } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { ConfigAcknowledgement, ConfigCheck, ConfigCheckMode, ConfigCheckModeState, ConfigFinding } from "@/lib/types";
import { useApiData } from "@/hooks/useApiData";
import { countFindings, groupFindings, type FindingGroup } from "@/lib/configCheck";
import { useSession } from "@/hooks/useSession";

const SHOW_AFTER_MS = 250;

export const MODE_LABEL: Record<ConfigCheckMode, string> = {
  enforce: "Enforce: errors stop a save until overridden",
  advisory: "Advisory: findings are shown, nothing is stopped",
  off: "Off: no checks",
};
export const MODE_OPTIONS = (Object.keys(MODE_LABEL) as ConfigCheckMode[]).map((m) => ({ value: m, label: MODE_LABEL[m] }));

/** A template's own check mode (docs/CONFIG_VERIFICATION.md §5): the finest level. */
export function ProfileCheckMode({ profileId }: { profileId: string }) {
  const { can } = useSession();
  const toast = useToast();
  const mode = useApiData<ConfigCheckModeState>(`/provisioning/check-mode`, { profile_id: profileId });
  const [busy, setBusy] = useState(false);
  const m = mode.data;
  if (!m) return null;
  const inherited = m.organization ?? m.installation;
  const set = async (value: string) => {
    setBusy(true);
    try {
      mode.setData(await api.put<ConfigCheckModeState>("/provisioning/check-mode", { scope: "profile", scope_id: profileId, mode: value || null }));
      toast.success("Check mode saved", value === "off" ? "Saves of this template are no longer checked." : undefined);
    } catch (err) {
      toast.error("The mode was not changed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <SelectField label="Configuration checks" value={m.profile ?? ""} disabled={busy || !can("provisioning.check.mode")}
      help="For phones you are testing, use a test template with checks off."
      options={[{ value: "", label: `Same as the ${m.organization ? "organization" : "installation"} (${inherited})` }, ...MODE_OPTIONS]}
      onChange={(e) => void set(e.target.value)} />
  );
}
const REASON_MIN = 5;

const FIELD_NAMES: Record<string, string> = {
  "line.display_name": "the extension's name",
  "line.label": "the line label",
  "line.extension_number": "the extension number",
  "line.sip_username": "the SIP user name",
  "line.caller_id_name": "the caller ID name",
  "line.caller_id_number": "the caller ID number",
  "line.hotline": "the hotline number",
  "device.label": "the phone's label",
  "organization.name": "the organization's name",
  "server.sip_host": "the SIP server",
  "server.ntp_server": "the time server",
  "server.provisioning_url": "the provisioning address",
  "server.directory_url": "the directory address",
  "key.value": "a key's number",
  "key.label": "a key's label",
  "zone.label": "a paging zone's name",
  "zone.multicast_address": "a paging zone's address",
};

function filledBy(f: ConfigFinding): string {
  if (!f.filled_by.length) return "a fixed value (the template text or a Base File Edit)";
  return f.filled_by.map((p) => `${FIELD_NAMES[p] ?? p} (${p})`).join(" and ");
}

function where(f: ConfigFinding, models: string[]): string {
  const fw = f.target?.how === "oldest" || !f.target?.firmware ? `release ${f.release} (no firmware known yet)` : `firmware ${f.firmware}`;
  return `${models.join(", ") || f.model} on ${fw}`;
}

export function FindingItem({ group, selectable, selected, onToggle }: { group: FindingGroup; selectable?: boolean; selected?: boolean; onToggle?: () => void }) {
  const f = group.first;
  const tone = f.severity === "error" ? (group.overridden ? "ok" : "danger") : f.severity === "warning" ? "warn" : "neutral";
  const label = f.severity === "error" ? (group.overridden ? "Overridden" : "Error") : f.severity === "warning" ? "Warning" : "Not checked";
  return (
    <li className="finding">
      <div className="finding__head">
        {selectable ? <input type="checkbox" aria-label={`Override ${f.parameter}`} checked={selected} onChange={onToggle} /> : null}
        <Badge tone={tone}>{label}</Badge>
        <span className="mono finding__param">{f.parameter || f.file}</span>
        {f.profile_name ? <span className="subtle">in {f.profile_name}</span> : null}
      </div>
      <p className="finding__message">{f.message}</p>
      <dl className="finding__facts">
        {f.parameter ? <><dt>Filled by</dt><dd>{filledBy(f)}</dd></> : null}
        {f.parameter ? <><dt>Value</dt><dd className="mono">{f.value === "" ? <span className="subtle">empty</span> : f.value}</dd></> : null}
        {f.accepts ? <><dt>Accepts</dt><dd>{f.accepts}</dd></> : null}
        <dt>Phones</dt><dd>{where(f, group.models)}</dd>
        {f.source ? <><dt>Source</dt><dd>{f.source}</dd></> : null}
        {f.note ? <><dt>Note</dt><dd>{f.note}</dd></> : null}
        {f.override ? <><dt>Overridden</dt><dd>by {f.override.by} on {new Date(f.override.at).toLocaleDateString()}: “{f.override.reason}”{f.override.checker_wrong ? " (reported: the checker is wrong)" : ""}</dd></> : null}
      </dl>
    </li>
  );
}

function Notes({ notes }: { notes: FindingGroup[] }) {
  const [open, setOpen] = useState(false);
  if (!notes.length) return null;
  return (
    <div className="stack--sm">
      {notes.map((g) => (
        <p key={g.key} className="subtle finding__note">○ {g.first.message}</p>
      ))}
      {notes.some((g) => g.first.members.length) ? (
        <>
          <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide these settings" : "Show these settings"}</button>
          {open ? (
            <ul className="finding__members mono">
              {[...new Set(notes.flatMap((g) => g.first.members))].sort().map((m) => <li key={m}>{m}</li>)}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Progress({ done }: { done: boolean }) {
  return (
    <div className={`check-progress${done ? " check-progress--done" : ""}`} role="progressbar" aria-label="Configuration check" aria-valuetext={done ? "Done" : "Checking"}>
      <div className="check-progress__bar" />
    </div>
  );
}

function summaryLine(check: ConfigCheck): string {
  const targets = check.targets ?? [];
  const models = [...new Set(targets.map((t) => t.model))];
  const fws = [...new Set(targets.map((t) => (t.firmware ? t.firmware : "oldest known release")))];
  const shown = models.length > 4 ? `${models.slice(0, 4).join(", ")} and ${models.length - 4} more` : models.join(", ");
  return `${check.checked ?? 0} settings checked${shown ? ` on ${shown}` : ""}${fws.length ? ` · ${fws.join(", ")}` : ""}`;
}

type State =
  | { phase: "idle" }
  | { phase: "running"; visible: boolean }
  | { phase: "result"; check: ConfigCheck }
  | { phase: "problems"; findings: ConfigFinding[]; detail: string };

/**
 * `run(save)` calls `save([])`; when the check stops it, the window lists
 * the findings and `save(acknowledgements)` runs again on Override and save.
 * Resolves with the saved result, or null when the user cancels. Errors
 * other than the check's are thrown as before.
 */
export function useConfigCheck() {
  const { can } = useSession();
  const [state, setState] = useState<State>({ phase: "idle" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [checkerWrong, setCheckerWrong] = useState(false);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ save: (ack: ConfigAcknowledgement[]) => Promise<unknown>; resolve: (v: unknown) => void; reject: (e: unknown) => void; result?: unknown } | null>(null);

  const finish = useCallback((value: unknown) => {
    const p = pending.current;
    pending.current = null;
    setState({ phase: "idle" });
    setBusy(false);
    p?.resolve(value);
  }, []);

  const attempt = useCallback(async (ack: ConfigAcknowledgement[]) => {
    const p = pending.current;
    if (!p) return;
    try {
      const result = (await p.save(ack)) as { config_check?: ConfigCheck | null } | undefined;
      const check = result?.config_check ?? null;
      p.result = result;
      if (!check || check.mode === "off") {
        finish(result);
        return;
      }
      setBusy(false);
      setState({ phase: "result", check });
    } catch (err) {
      if (err instanceof ApiError && err.code === "config_findings") {
        const findings = err.errors as unknown as ConfigFinding[];
        setSelected(new Set(groupFindings(findings).filter((g) => g.first.severity === "error" && !g.overridden).map((g) => g.key)));
        setBusy(false);
        setState({ phase: "problems", findings, detail: err.detail ?? "" });
        return;
      }
      pending.current = null;
      setState({ phase: "idle" });
      setBusy(false);
      p.reject(err);
    }
  }, [finish]);

  const run = useCallback(<T,>(save: (ack: ConfigAcknowledgement[]) => Promise<T>): Promise<T | null> => {
    return new Promise<T | null>((resolve, reject) => {
      pending.current = { save, resolve: resolve as (v: unknown) => void, reject };
      setReason("");
      setCheckerWrong(false);
      setState({ phase: "running", visible: false });
      window.setTimeout(() => setState((s) => (s.phase === "running" ? { phase: "running", visible: true } : s)), SHOW_AFTER_MS);
      void attempt([]);
    });
  }, [attempt]);

  const cancel = () => finish(null);
  const okay = () => finish(pending.current?.result ?? null);

  let dialog = null;
  if (state.phase === "running" && state.visible) {
    dialog = (
      <Dialog open onClose={() => undefined} busy title="Checking the configuration" description="Comparing every phone setting with what the vendor's firmware accepts.">
        <Progress done={false} />
      </Dialog>
    );
  } else if (state.phase === "result") {
    const c = countFindings(state.check.findings);
    const groups = groupFindings(state.check.findings).filter((g) => g.first.severity !== "info");
    const clean = c.errors === 0 && c.warnings === 0;
    dialog = (
      <Dialog open onClose={okay} size="lg" title="Configuration check" footer={<Button variant="primary" onClick={okay} autoFocus>OK</Button>}>
        <div className="stack--sm">
          <Progress done />
          {clean ? (
            <Callout tone="ok" title={c.overridden ? "No new problems found" : "No problems found"}>{summaryLine(state.check)}</Callout>
          ) : (
            <Callout tone={c.errors ? "danger" : "warn"} title={c.errors ? `Saved with ${c.errors} error(s): checks are advisory here` : `Saved with ${c.warnings} warning(s)`}>
              {summaryLine(state.check)}. Phones may refuse or ignore the settings below.
            </Callout>
          )}
          {groups.length ? <ul className="findings">{groups.map((g) => <FindingItem key={g.key} group={g} />)}</ul> : null}
          <Notes notes={c.notes} />
        </div>
      </Dialog>
    );
  } else if (state.phase === "problems") {
    const groups = groupFindings(state.findings);
    const open = groups.filter((g) => g.first.severity === "error" && !g.overridden);
    const rest = groups.filter((g) => g.first.severity !== "info" && !open.includes(g));
    const notes = groups.filter((g) => g.first.severity === "info");
    const mayOverride = can("provisioning.check.override");
    const chosen = open.filter((g) => selected.has(g.key));
    const ack: ConfigAcknowledgement[] = chosen.flatMap((g) => g.fingerprints.map((fingerprint) => ({ fingerprint, reason: reason.trim(), checker_wrong: checkerWrong })));
    const ready = chosen.length === open.length && reason.trim().length >= REASON_MIN;
    dialog = (
      <Dialog open onClose={cancel} busy={busy} size="lg" scroll="inner" title="Configuration check"
        footer={(
          <>
            <Button onClick={cancel} disabled={busy}>Cancel</Button>
            {mayOverride ? (
              <Button variant="danger" loading={busy} disabled={!ready} onClick={() => { setBusy(true); void attempt(ack); }}>Override and save</Button>
            ) : null}
          </>
        )}>
        <div className="stack--sm">
          <Progress done />
          <Callout tone="danger" title={`${open.length} setting(s) the firmware would refuse`}>
            Nothing was saved. Change the configuration, or override these if you know the phones accept them.
          </Callout>
          <ul className="findings">
            {open.map((g) => (
              <FindingItem key={g.key} group={g} selectable={mayOverride} selected={selected.has(g.key)}
                onToggle={() => setSelected((s) => { const n = new Set(s); if (n.has(g.key)) n.delete(g.key); else n.add(g.key); return n; })} />
            ))}
            {rest.map((g) => <FindingItem key={g.key} group={g} />)}
          </ul>
          <Notes notes={notes} />
          {mayOverride ? (
            <div className="stack--sm">
              <TextArea label="Why are these settings right?" required rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
                help={chosen.length < open.length ? "Tick every error to save past it." : `At least ${REASON_MIN} characters. Kept with the override and in the audit log.`} />
              <Checkbox label="The checker is wrong" description="Report it, so the vendor data can be corrected." checked={checkerWrong} onChange={(e) => setCheckerWrong(e.target.checked)} />
            </div>
          ) : (
            <Callout tone="info">Ask an administrator who may override configuration checks to review these.</Callout>
          )}
        </div>
      </Dialog>
    );
  }
  return { run, dialog };
}
