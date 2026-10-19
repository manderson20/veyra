// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { Badge, Checkbox, FormSection, SelectField, Switch, TextArea, TextField } from "@/components/ui";
import { AUTH_MODES, CALLER_ID_HEADERS, CODECS, DTMF_MODES, TRANSPORTS, parseList, trunkStatus } from "@/lib/routing";
import type { CallerIdHeader, DtmfMode, Trunk, TrunkAuthMode, TrunkInput, TrunkTransport } from "@/lib/types";

/** Form state for a trunk; numbers are kept as text while editing. */
export interface TrunkDraft {
  name: string;
  description: string;
  is_enabled: boolean;
  auth_mode: TrunkAuthMode;
  host: string;
  port: string;
  transport: TrunkTransport;
  username: string;
  auth_username: string;
  /** New password to store; empty = leave unchanged. */
  password: string;
  /** Remove the stored password (IP mode only, edit only). */
  clear_password: boolean;
  from_user: string;
  from_domain: string;
  outbound_proxy: string;
  /** Comma or newline separated. */
  match_addresses: string;
  /** null = installation default. */
  codecs: string[] | null;
  max_channels: string;
  default_caller_id: string;
  caller_id_header: CallerIdHeader;
  dtmf_mode: DtmfMode;
  fax_t38: boolean;
  qualify_frequency: string;
  register_expiry: string;
}

export const EMPTY_TRUNK: TrunkDraft = {
  name: "",
  description: "",
  is_enabled: true,
  auth_mode: "registration",
  host: "",
  port: "5060",
  transport: "udp",
  username: "",
  auth_username: "",
  password: "",
  clear_password: false,
  from_user: "",
  from_domain: "",
  outbound_proxy: "",
  match_addresses: "",
  codecs: null,
  max_channels: "",
  default_caller_id: "",
  caller_id_header: "pai",
  dtmf_mode: "rfc4733",
  fax_t38: false,
  qualify_frequency: "60",
  register_expiry: "3600",
};

export function trunkDraft(t: Trunk): TrunkDraft {
  return {
    name: t.name,
    description: t.description ?? "",
    is_enabled: t.is_enabled,
    auth_mode: t.auth_mode,
    host: t.host,
    port: String(t.port),
    transport: t.transport,
    username: t.username ?? "",
    auth_username: t.auth_username ?? "",
    password: "",
    clear_password: false,
    from_user: t.from_user ?? "",
    from_domain: t.from_domain ?? "",
    outbound_proxy: t.outbound_proxy ?? "",
    match_addresses: t.match_addresses.join("\n"),
    codecs: t.codecs ? [...t.codecs] : null,
    max_channels: t.max_channels === null ? "" : String(t.max_channels),
    default_caller_id: t.default_caller_id ?? "",
    caller_id_header: t.caller_id_header,
    dtmf_mode: t.dtmf_mode,
    fax_t38: t.fax_t38,
    qualify_frequency: String(t.qualify_frequency),
    register_expiry: String(t.register_expiry),
  };
}

function int(text: string, fallback: number): number {
  const n = Number.parseInt(text, 10);
  return Number.isFinite(n) ? n : fallback;
}

const text = (v: string) => v.trim() || null;

/** Request body for POST or PATCH; the password is only sent when set (or cleared). */
export function trunkBody(d: TrunkDraft): TrunkInput {
  const body: TrunkInput = {
    name: d.name.trim(),
    description: text(d.description),
    is_enabled: d.is_enabled,
    auth_mode: d.auth_mode,
    host: d.host.trim(),
    port: int(d.port, 5060),
    transport: d.transport,
    username: text(d.username),
    auth_username: text(d.auth_username),
    from_user: text(d.from_user),
    from_domain: text(d.from_domain),
    outbound_proxy: text(d.outbound_proxy),
    match_addresses: parseList(d.match_addresses),
    codecs: d.codecs ? [...d.codecs].sort((a, b) => CODECS.indexOf(a as (typeof CODECS)[number]) - CODECS.indexOf(b as (typeof CODECS)[number])) : null,
    max_channels: d.max_channels.trim() ? int(d.max_channels, 0) : null,
    default_caller_id: text(d.default_caller_id),
    caller_id_header: d.caller_id_header,
    dtmf_mode: d.dtmf_mode,
    fax_t38: d.fax_t38,
    qualify_frequency: int(d.qualify_frequency, 60),
    register_expiry: int(d.register_expiry, 3600),
  };
  if (d.password) body.password = d.password;
  else if (d.clear_password) body.password = null;
  return body;
}

export function trunkDirty(draft: TrunkDraft, trunk: Trunk): boolean {
  return JSON.stringify(trunkBody(draft)) !== JSON.stringify(trunkBody(trunkDraft(trunk)));
}

export function TrunkStatusBadge({ trunk }: { trunk: Pick<Trunk, "is_enabled" | "status"> }) {
  const s = trunkStatus(trunk);
  return (
    <span className={`badge badge--${s.tone}`}>
      <span className={s.tone === "neutral" ? "dot dot--ring" : "dot"} aria-hidden="true" />
      {s.label}
    </span>
  );
}

interface FieldsProps {
  draft: TrunkDraft;
  onChange: (patch: Partial<TrunkDraft>) => void;
  errors: Record<string, string>;
  disabled?: boolean;
  /** Whether a password is currently stored (edit mode). */
  hasPassword?: boolean;
}

const HOST_HELP = "Host name or IP address of the carrier's SIP server.";
const MATCH_HELP = "One address or CIDR network per line (or comma separated). Calls from these addresses are accepted as this trunk. Empty: the host above.";

/** The essential fields for the create dialog. */
export function TrunkEssentialFields({ draft, onChange, errors, disabled }: FieldsProps) {
  const registration = draft.auth_mode === "registration";
  return (
    <>
      <TextField label="Name" required autoFocus disabled={disabled} value={draft.name} error={errors.name} placeholder="e.g. Carrier A"
        onChange={(e) => onChange({ name: e.target.value })} />
      <SelectField label="Authentication" required disabled={disabled} value={draft.auth_mode} error={errors.auth_mode}
        help={registration ? "Veyra registers with the carrier using a user name and password." : "The carrier trusts calls from Veyra's address; incoming calls are matched by source address."}
        options={AUTH_MODES} onChange={(e) => onChange({ auth_mode: e.target.value as TrunkAuthMode })} />
      <div className="form-grid">
        <TextField label="Host" required disabled={disabled} value={draft.host} error={errors.host} help={HOST_HELP} autoComplete="off" spellCheck={false}
          onChange={(e) => onChange({ host: e.target.value })} />
        <div className="form-grid">
          <TextField label="Port" required inputMode="numeric" disabled={disabled} value={draft.port} error={errors.port}
            onChange={(e) => onChange({ port: e.target.value.replace(/\D/g, "") })} />
          <SelectField label="Transport" disabled={disabled} value={draft.transport} error={errors.transport} options={TRANSPORTS}
            onChange={(e) => onChange({ transport: e.target.value as TrunkTransport })} />
        </div>
      </div>
      {registration ? (
        <div className="form-grid">
          <TextField label="User name" required disabled={disabled} value={draft.username} error={errors.username} autoComplete="off" spellCheck={false}
            onChange={(e) => onChange({ username: e.target.value })} />
          <TextField label="Password" required type="password" disabled={disabled} value={draft.password} error={errors.password} autoComplete="new-password"
            onChange={(e) => onChange({ password: e.target.value })} />
        </div>
      ) : (
        <TextArea label="Match addresses" rows={3} disabled={disabled} value={draft.match_addresses} error={errors.match_addresses} help={MATCH_HELP}
          placeholder={draft.host.trim() || "203.0.113.10\n198.51.100.0/24"} spellCheck={false} onChange={(e) => onChange({ match_addresses: e.target.value })} />
      )}
      <TextField label="Default caller ID" disabled={disabled} value={draft.default_caller_id} error={errors.default_caller_id} inputMode="tel"
        help="Number sent on outbound calls when the route and extension set none." onChange={(e) => onChange({ default_caller_id: e.target.value })} />
    </>
  );
}

/** Every trunk field, grouped into sections, for the detail page. */
export function TrunkAllFields({ draft, onChange, errors, disabled, hasPassword }: FieldsProps) {
  const registration = draft.auth_mode === "registration";
  const toggleCodec = (codec: string, on: boolean) => {
    const current = draft.codecs ?? [];
    onChange({ codecs: on ? [...current.filter((c) => c !== codec), codec] : current.filter((c) => c !== codec) });
  };
  return (
    <>
      <FormSection title="Connection" description="Where the carrier's SIP server is and how to reach it.">
        <TextField label="Name" required disabled={disabled} value={draft.name} error={errors.name} onChange={(e) => onChange({ name: e.target.value })} />
        <div className="form-grid">
          <TextField label="Host" required disabled={disabled} value={draft.host} error={errors.host} help={HOST_HELP} autoComplete="off" spellCheck={false}
            onChange={(e) => onChange({ host: e.target.value })} />
          <div className="form-grid">
            <TextField label="Port" required inputMode="numeric" disabled={disabled} value={draft.port} error={errors.port}
              onChange={(e) => onChange({ port: e.target.value.replace(/\D/g, "") })} />
            <SelectField label="Transport" disabled={disabled} value={draft.transport} error={errors.transport} options={TRANSPORTS}
              onChange={(e) => onChange({ transport: e.target.value as TrunkTransport })} />
          </div>
        </div>
        <Switch label="Enabled" description="Disabled trunks are kept but left out of the engine configuration, and routes using them fail over." checked={draft.is_enabled} disabled={disabled}
          onChange={(e) => onChange({ is_enabled: e.target.checked })} />
      </FormSection>
      <hr className="divider" />
      <FormSection title="Authentication" description={registration ? "Veyra registers with the carrier and authenticates outbound calls with these credentials." : "The carrier trusts Veyra's address. A user name and password are only needed if it challenges outbound calls."}>
        <SelectField label="Mode" required disabled={disabled} value={draft.auth_mode} error={errors.auth_mode} options={AUTH_MODES}
          onChange={(e) => onChange({ auth_mode: e.target.value as TrunkAuthMode, clear_password: false })} />
        <div className="form-grid">
          <TextField label="User name" required={registration} disabled={disabled} value={draft.username} error={errors.username} autoComplete="off" spellCheck={false}
            onChange={(e) => onChange({ username: e.target.value })} />
          <TextField label="Authentication user name" disabled={disabled} value={draft.auth_username} error={errors.auth_username} autoComplete="off" spellCheck={false}
            help="Only when the carrier's authentication name differs from the user name." onChange={(e) => onChange({ auth_username: e.target.value })} />
        </div>
        <TextField label="Set new password" type="password" disabled={disabled || draft.clear_password} value={draft.password} error={errors.password} autoComplete="new-password"
          help={hasPassword ? "A password is stored and is never shown. Enter a new one to replace it; leave empty to keep it." : registration ? "No password is stored yet; registration needs one." : "No password is stored."}
          onChange={(e) => onChange({ password: e.target.value })} />
        {!registration && hasPassword ? (
          <Checkbox label="Clear the stored password" description="Removes the password when saved. Only possible in IP mode." checked={draft.clear_password} disabled={disabled || !!draft.password}
            onChange={(e) => onChange({ clear_password: e.target.checked })} />
        ) : null}
      </FormSection>
      <hr className="divider" />
      <FormSection title="Identification" description="How incoming calls from the carrier are recognised.">
        <TextArea label="Match addresses" rows={3} disabled={disabled} value={draft.match_addresses} error={errors.match_addresses}
          help={registration ? "Optional in registration mode: extra source addresses accepted as this trunk." : MATCH_HELP}
          placeholder={registration ? "" : draft.host.trim() || "203.0.113.10\n198.51.100.0/24"} spellCheck={false} onChange={(e) => onChange({ match_addresses: e.target.value })} />
      </FormSection>
      <hr className="divider" />
      <FormSection title="Calling" description="Media, capacity and caller ID for calls over this trunk.">
        <div className="field">
          <span className="field__label">Codecs</span>
          <Checkbox label="Installation default" description="Use the codec list from System → Telephony Engine." checked={draft.codecs === null} disabled={disabled}
            onChange={(e) => onChange({ codecs: e.target.checked ? null : ["ulaw", "alaw"] })} />
          {draft.codecs !== null ? (
            <div className="row" role="group" aria-label="Codecs" style={{ gap: "var(--space-4)", marginTop: 4 }}>
              {CODECS.map((c) => (
                <Checkbox key={c} label={<span className="mono">{c}</span>} checked={draft.codecs?.includes(c) ?? false} disabled={disabled} onChange={(e) => toggleCodec(c, e.target.checked)} />
              ))}
            </div>
          ) : null}
          {errors.codecs ? <p className="field__error" role="alert">{errors.codecs}</p> : null}
        </div>
        <div className="form-grid">
          <TextField label="Maximum channels" inputMode="numeric" disabled={disabled} value={draft.max_channels} error={errors.max_channels} placeholder="Unlimited"
            help="Concurrent calls allowed on this trunk." onChange={(e) => onChange({ max_channels: e.target.value.replace(/\D/g, "") })} />
          <TextField label="Default caller ID" disabled={disabled} value={draft.default_caller_id} error={errors.default_caller_id} inputMode="tel"
            help="Used when the route and extension set none." onChange={(e) => onChange({ default_caller_id: e.target.value })} />
        </div>
        <div className="form-grid">
          <SelectField label="Caller ID header" disabled={disabled} value={draft.caller_id_header} error={errors.caller_id_header} options={CALLER_ID_HEADERS}
            help="How the caller's number is passed to the carrier." onChange={(e) => onChange({ caller_id_header: e.target.value as CallerIdHeader })} />
          <SelectField label="DTMF" disabled={disabled} value={draft.dtmf_mode} error={errors.dtmf_mode} options={DTMF_MODES}
            onChange={(e) => onChange({ dtmf_mode: e.target.value as DtmfMode })} />
        </div>
        <Checkbox label="Fax over T.38 (offer T.38 fax relay to this carrier; audio fax when it declines)" checked={draft.fax_t38} disabled={disabled}
          onChange={(e) => onChange({ fax_t38: e.target.checked })} />
        <div className="form-grid">
          <TextField label="Qualify frequency (seconds)" inputMode="numeric" disabled={disabled} value={draft.qualify_frequency} error={errors.qualify_frequency}
            help="How often the carrier is checked for reachability; 0 disables status monitoring." onChange={(e) => onChange({ qualify_frequency: e.target.value.replace(/\D/g, "") })} />
          <TextField label="Registration expiry (seconds)" inputMode="numeric" disabled={disabled || !registration} value={draft.register_expiry} error={errors.register_expiry}
            help="How long each registration lasts (60–86400)." onChange={(e) => onChange({ register_expiry: e.target.value.replace(/\D/g, "") })} />
        </div>
      </FormSection>
      <hr className="divider" />
      <FormSection title="Advanced" description="Usually left empty; some carriers require specific From values or a proxy.">
        <div className="form-grid">
          <TextField label="From user" disabled={disabled} value={draft.from_user} error={errors.from_user} autoComplete="off" spellCheck={false}
            help="User part of the From header. Defaults to the user name." onChange={(e) => onChange({ from_user: e.target.value })} />
          <TextField label="From domain" disabled={disabled} value={draft.from_domain} error={errors.from_domain} autoComplete="off" spellCheck={false}
            help="Domain part of the From header. Defaults to the host." onChange={(e) => onChange({ from_domain: e.target.value })} />
        </div>
        <TextField label="Outbound proxy" disabled={disabled} value={draft.outbound_proxy} error={errors.outbound_proxy} autoComplete="off" spellCheck={false}
          placeholder="sip:proxy.example.net:5060" help="All SIP traffic for this trunk is sent through this proxy." onChange={(e) => onChange({ outbound_proxy: e.target.value })} />
        <TextArea label="Description" rows={2} disabled={disabled} value={draft.description} error={errors.description} onChange={(e) => onChange({ description: e.target.value })} />
      </FormSection>
    </>
  );
}

export function TrunkModeBadge({ mode }: { mode: TrunkAuthMode }) {
  return <Badge tone="outline">{mode === "ip" ? "IP" : "Registration"}</Badge>;
}
