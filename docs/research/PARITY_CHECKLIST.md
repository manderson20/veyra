# Parity checklist

Owner goal, 2026-11-01: support every FreePBX commercial module, plus concepts from
Metaswitch, FreeSWITCH and Grandstream that Veyra lacks. The lab is about a month away.
Checked items exist in code; none is proven until its Test: card passes.

Sources: `freepbx-commercial-catalogue.md`, `FREEPBX_GAP_ANALYSIS.md`, the Metaswitch
comparison (PR #162) and a code-checked review of the Grandstream UCM6300 manual
(firmware 1.0.13.9) and FreeSWITCH module reference, 2026-11-01. Size is an estimate.
"Lab" means final proof needs phones, a carrier or an outside service.

## Stage 1: small call and voicemail items (S)

- [x] Remote forward codes for busy and no answer (FreePBX)
- [ ] Follow-me linked to a calendar (FreePBX, P1)
- [ ] Pause reason codes (VQ Plus)
- [ ] Queue auto-pause on no answer, written to the database row (FreeSWITCH, FreePBX)
- [ ] Queue weight and importance (FreeSWITCH, FreePBX)
- [ ] DISA (FreePBX, Grandstream)
- [ ] Wake-up calls (Grandstream, FreePBX Hotel)
- [ ] Extension-to-extension allow list (Grandstream)
- [ ] IVR multi-digit, allow and block lists, key by time (FreePBX, Grandstream)
- [ ] Voicemail: automatic extra recipients, per-box quota, alternate greeting, spoken intro on forward (FreeSWITCH)
- [ ] Conference: announce count, ghost member, end on silence, auto outcall, record at N members (FreeSWITCH)
- [ ] Pickup Incall privilege, Seamless Transfer allow list (Grandstream)
- [ ] Delayed paging (Grandstream)
- [ ] Emergency call: record and email the file (Grandstream); needs a legal note
- [ ] Trunk: weighted distribution, concurrency alarm (FreeSWITCH, Grandstream)
- [ ] Refuse calls at high CPU or disk use (Grandstream)
- [ ] Logs off the box by syslog; SNMP (FreeSWITCH)
- [ ] Caller name lookup over HTTP (FreePBX CID Superfecta, FreeSWITCH)

## Stage 2: commercial modules not yet met

- [ ] **Pinset Pro**: PIN sets, pinless per extension, reports (M)
- [ ] **VQ Plus**: queue callback, virtual queues, penalty rules, post-hangup destinations (M)
- [ ] **Queue Wallboard**: live caller view and board (M)
- [ ] **Q-Xact**: missed-call detail (S)
- [ ] **Conference Pro**: web controls and PIN for personal rooms, conference IVR, scheduled rooms (M)
- [ ] **Park Pro and Park & Announce**: private lots, `*86`, announce (M, Lab)
- [ ] **Page Pro**: duplex paging, busy handling, browser page (M, Lab)
- [ ] **VM Notify**: call a list until someone accepts (S)
- [ ] **Voicemail Reports** (S)
- [ ] **Caller ID Management**: block foreign, remove CNAM, per-call caller ID (S)
- [ ] **Outbound Call Limit**: per extension and by time window (S)
- [ ] **Extension Routing**: allowed extensions per route, beyond class of service (S)
- [ ] **Web Call Me** (M, follows the browser phone for visitors)
- [ ] **Appointment Reminder** (M)
- [ ] **Broadcast / XactDialer**: campaigns, CSV lists, answering machine detection, closings toggle (L, Lab)
- [ ] **Fax Pro**: remaining items, fax detection on routes, email to fax, folders (M, Lab)
- [ ] **Call Recording Reports**: auto-archive and zero-length cleanup checks (S)
- [ ] **CDR Pro and Call Accounting**: rate tables and bills, call quality (M)
- [ ] **Sysadmin Pro**: DDNS, DHCP, OpenVPN, support VPN, UPS, port management (M; network changes are risky remotely)
- [ ] **Filestore**: FTP, Dropbox, email (S)
- [ ] **Advanced Recovery**: automatic failover and witness (L, needs a second server)
- [ ] **EndPoint Manager**: 18 more brands, images, network scan (L, Lab)
- [ ] **Phone Apps**: XML apps on phone screens, XML app key (M, Lab)
- [ ] **CRM Link**: Salesforce, Zoho, Sugar, ConnectWise connectors, Zapier (M each; needs sandboxes)
- [ ] **Contact Image** (S)
- [ ] **Scribe**: transcription and summaries, on premises (L)
- [ ] **Softphones**: browser phone (L); mobile with push is larger and needs app stores
- [ ] **Sangoma Meet**: video rooms (L, follows the browser phone)
- [ ] **Property Management**: hotel rooms, housekeeping, PMS link (L; simulator only without a PMS)
- [ ] **SMS**: through a carrier API (M, needs a provider)

Met already, by code: Class of Service, MFA, SAML, EndPoint Manager core, Call Recording Reports core.
Not targets: Zulu UC, XactView and XMPP, discontinued by Sangoma.

## Stage 3: other concepts

**Metaswitch**
- [ ] Personal call rules: selective accept, reject, forward, personal schedules (M)
- [ ] Executive / assistant (M)
- [ ] Shared line appearance (L, Lab)
- [ ] Voicemail notification by outdial and pager (S)

**Grandstream**
- [ ] Call Flip (M), Busy Camp-on (M), Stop Ringing (S, Lab)
- [ ] Virtual queue callback (shared with VQ Plus), Queue Chairman role (M), satisfaction survey (M), QueueMetrics export (S)
- [ ] Operator panel (M), team chat (L), scheduled meetings and report (M), live call into a room (S)
- [ ] LDAP server for phones (M), TR-069 (M, Lab), zero-config discovery (M, Lab)
- [ ] Sound language packs (M), SIP MESSAGE (S), block collect calls (S, Lab), STIR/SHAKEN (M, Lab)
- [ ] Camera streams to extensions (M, Lab), CTI (M, Lab), SLA stations (L, Lab)
- [ ] RemoteConnect-style relay and GDMS-style cloud (L; needs a hosted service, owner decision)
- [ ] Emergency trunk seizure (M, Lab; legal review first)

**FreeSWITCH**
- [ ] Least-cost routing (M), prepaid balance (M), number rewrite profiles (M)
- [ ] Tier rules, abandoned resume, on-demand agents (M)
- [ ] Noise gate and level control (S, real audio), stream a room (M), video MCU (L)
- [ ] Beep and machine detection (M, real audio), save last N seconds of a call (M), follow a user's calls (S)
- [ ] Text to speech, offline speech recognition (M each), call control by web server (M), event bus (M)

## Decisions for the owner

These don't block stages 1 and 2:
- Hosted services (relay, cloud fleet) would make Veyra depend on something you run.
- Team chat, video and hotel features were skipped on purpose earlier; this goal brings them back.
- Automatic failover, trunk seizure and emergency recording have safety or legal weight.
