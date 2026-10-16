# FreePBX feature gap analysis

Veyra 0.23.0 compared with FreePBX 16/17, every free module and every
Sangoma commercial module (FreePBX add-ons and PBXact), as of
2026-10-16. Written before Milestone 18 (public release) so that no
FreePBX feature is left out of the roadmap only because the current
feature set felt good enough.

Companion documents: the raw catalogues this analysis was built from are
[research/freepbx-open-source-catalogue.md](research/freepbx-open-source-catalogue.md)
(91 free modules and areas, with the option lists and feature codes) and
[research/freepbx-commercial-catalogue.md](research/freepbx-commercial-catalogue.md)
(38 commercial modules, bundles, licensing and 2026 reseller prices). Both
cite the Sangoma wiki page for every section. The Veyra side comes from
the code, `docs/` and the milestone reports at 0.23.0.

## 1. How to read this document

Each row names a FreePBX capability, says what Veyra has today, and rates
the gap:

| Mark | Meaning |
|---|---|
| ✔ | Veyra has it (equal or better) |
| ◐ | Veyra has part of it; the missing part is named |
| ✘ | Veyra does not have it |
| — | Deliberately not planned, with the reason |

Priority is a recommendation for the owner, not a decision:

| Priority | Meaning |
|---|---|
| P1 | Anyone coming from FreePBX in a school, municipality or small business expects it; should be in place for 1.0 |
| P2 | Wanted by a meaningful share of installations; first releases after 1.0 unless the owner pulls it forward |
| P3 | Niche, or better as an optional module |

Where FreePBX charges for a feature the commercial module is named, so the
comparison also covers what a PBXact buyer gets.

## 2. Summary

Counting every capability row below: Veyra has 60 (✔), has part of 43
(◐), lacks 134 (✘) and deliberately leaves out 19 (—). The numbers flatter
neither side: many missing rows are small dialplan features that a day of
work closes, while several things Veyra has (multi-tenancy, a central
console, signed updates, built-in HA, the paging engine, OIDC) FreePBX
does not offer at any price.

The gaps that matter most, in the order a FreePBX administrator would
notice them on day one:

1. **Everyday call features on the extension**: do-not-disturb, call
   forwarding (always, busy, no answer), find-me/follow-me to a mobile,
   call waiting, intercom and auto-answer, per-extension outbound caller
   ID. None exist in Veyra. (§3.1)
2. **Call parking and conferences**: both absent; FreePBX has had both
   for twenty years. (§3.5)
3. **Transfer to voicemail, "press 0 for the operator", voicemail
   greeting management from the browser, a web inbox**: Veyra's voicemail
   is solid underneath but managed only from the phone. (§3.6)
4. **Dialing restrictions**: Class of Service, Extension Routing and PIN
   sets. A classroom phone that must not dial long distance has no
   control in Veyra today beyond "which organization owns the route".
   (§3.4)
5. **Day/night call flow toggles and time-condition overrides from a
   phone key**: the receptionist's most-used button. (§3.5)
6. **Queues for people who run a front desk**: agent log-in/log-out and
   pause, a "press 1 to leave a message" break-out, callback, a live
   view. (§3.5)
7. **Phone provisioning breadth**: FreePBX's EndPoint Manager covers 22
   brands; Veyra ships Poly VVX templates only, marked experimental.
   Yealink and Grandstream are the volume brands in Veyra's market, and
   ATAs, Algo and CyberData devices are what schools attach. (§3.9)
8. **A user portal**: FreePBX's UCP gives every user voicemail, call
   history with recordings, forwarding and follow-me controls, contacts
   and presence in a browser. Veyra has an account page and the Companion
   extension. (§3.8)
9. **Small destinations FreePBX users take for granted**: announcements,
   dial-by-name directory, blacklist of callers, misc destinations and a
   custom-dialplan escape hatch, language switching, callback and DISA.
   (§3.5)
10. **Migration path**: bulk CSV import of extensions and DIDs, and an
    importer for FreePBX backups. Without one, every FreePBX site
    re-keys its configuration by hand. (§3.11)
11. **Let's Encrypt** certificates and off-box backup destinations (SFTP,
    S3). (§3.11)
12. **Fax**: not even inbound fax-to-email. (§3.10)

What FreePBX does not have and Veyra does: installation-wide signed
updates with maintenance windows, a signed module catalogue, built-in
active/passive HA, verified and encrypted backups with restore to a new
server, nftables firewall with feeds and a permanent allow list, OpenID
Connect sign-in with MFA policy per role, a full audit log, retention
policies, data encryption at rest with key rotation, multi-tenancy, a
central console for many installations, the paging engine (multicast and
Poly group pages in step, calendar-driven bells, priority pages),
emergency-call readiness per site with on-site notification and ELIN
callback, the report builder with scheduled delivery, recording playback
that is audited and policy-driven, the Companion browser extension, and
signed outgoing webhooks. These are the reasons to choose Veyra; the gaps
below are the reasons a FreePBX site would hesitate.

## 3. Detailed comparison

### 3.1 Extensions and per-user call features

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| PJSIP extension with generated strong secret | PJSIP only, 24-character generated secret, encrypted at rest, show/rotate audited | ✔ | |
| IAX2 and DAHDI (FXS card) extensions | not supported | — analog ports belong on an ATA or gateway registered as PJSIP; no card support planned | |
| Virtual extension (voicemail and follow-me without a device) | an extension can exist without a device, shared inboxes exist; no "virtual" type and no follow-me | ◐ | P2 (with follow-me) |
| Custom/other extension (free-form dial string) | no | ✘ | P3 |
| Display name and internal caller ID | yes | ✔ | |
| **Outbound caller ID per extension** (`"name" <number>` on trunks) | outbound calls carry the route or trunk caller ID; per-extension value applies to internal calls only | ✘ | **P1** |
| Emergency caller ID per extension | yes, plus ELIN per site, location per extension and device, readiness checks | ✔ ahead | |
| Do Not Disturb (`*78/*79/*76`, portal, presence-driven) | no | ✘ | **P1** |
| Call forwarding unconditional, busy, no-answer (`*72/*73`, `*90/*91`, `*52/*53`, remote variants, ring timer) | no | ✘ | **P1** |
| Find Me / Follow Me (external numbers, strategies, confirm calls, calendar-linked, `*21`) | no; ring group members are extensions only | ✘ | **P1** |
| Call waiting toggle (`*70/*71`) | ring groups can ring busy members; no per-extension toggle | ✘ | P2 |
| Internal auto-answer / intercom per extension | no | ✘ | **P1** (with intercom, §3.5) |
| Outbound concurrency limit per extension | no | ✘ | P2 (toll-fraud control) |
| Ring time per extension | yes (voicemail ring time 5–120 s) | ✔ | |
| Optional destinations: no answer, busy, not reachable | voicemail only | ◐ | P2 |
| Recording options per extension (four directions, on-demand allow/override, priority) | recording policies can select extensions; no per-direction extension flags, no on-demand `*1` | ◐ | P2 |
| Call screening (caller says name) | no | ✘ | P3 |
| Dictation service | no | — not planned | |
| Media encryption per extension (SRTP, DTLS) and TLS transport | transports UDP/TCP/TLS installation-wide; no SRTP | ✘ | **P1** (secure SIP, design question 4 in PRODUCTION_HARDENING.md) |
| Max contacts (several phones on one extension) | yes, up to 16 | ✔ | |
| Call groups and pickup groups | yes | ✔ | |
| Account code, CID number alias, SIP alias | no | ✘ | P3 |
| Language per extension | installation-wide default only | ✘ | P2 (with sound languages) |
| Hot desking (Device & User mode, log-in/log-out codes, phone app) | no | ✘ | P2 |
| Camp-on (CCSS) | no | — rarely used; not planned | |
| Queue state detection flag | queues use device state; no override | ◐ | P3 |
| Add inbound DID from the extension page | inbound routes are created on their own page | ◐ | P3 |
| **Bulk CSV import/export of extensions** (Bulk Handler) | no | ✘ | **P1** (see migration, §3.11) |
| Extension Settings report (DND/CF/FM state table) | no | ✘ | P3 after the features exist |
| Print Extensions (every dialable number) | no | ✘ | P3 |
| Weak password detection | not needed: secrets are generated and never typed | ✔ by construction | |

### 3.2 Trunks

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| PJSIP trunk, registration or IP authentication, UDP/TCP/TLS | yes | ✔ | |
| IAX2 trunks | no | — not planned unless an installation asks | |
| DAHDI/PRI/analog trunks (cards) | no | — gateways (Sangoma Vega, Grandstream, Patton) register as PJSIP trunks; no card support planned | |
| ENUM and DUNDi trunks | no | — DUNDi is gone from FreePBX 17 too | |
| Custom trunk (dial string) | no | ✘ | P3 |
| Outbound caller ID per trunk | yes | ✔ | |
| CID options: allow any / block foreign / remove CNAM / force trunk CID | trunk default only | ◐ | P2 |
| Maximum channels | yes | ✔ | |
| Continue if busy | no | ✘ | P3 |
| Dial manipulation rules per trunk (prepend/prefix/match) | per outbound route only | ◐ | P2 |
| Registration tuning (retry interval, forbidden retry, max retries, expiration) | expiration only | ◐ | P2 |
| **Registration state shown** (registered / rejected / retrying) | reachability from qualify only | ✘ | **P1** |
| Outbound proxy, contact user, codecs, qualify, DTMF mode, PAI/RPID | yes | ✔ | |
| Inbound channel counting per trunk | no | ✘ | P3 |
| Trunk down alert | yes | ✔ | |
| Carrier presets / provider-specific settings | no | ✘ | P3 (document presets for the common US carriers) |
| SIPStation-style provider wizard (DIDs, E911, SMS from the carrier account) | no | — carrier-specific; a module if a partner carrier appears | |

### 3.3 Inbound routing

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| DID match, catch-all, per-trunk restriction | yes, with NANP aliasing | ✔ | |
| DID patterns (`_1NXX...`) | exact DIDs only | ◐ | P3 |
| Caller-ID based routing (CID number, anonymous/blocked/unknown) | no | ✘ | P2 |
| CID priority routes | no | ✘ | P3 |
| Alert-Info (distinctive ring, auto-answer) | no | ✘ | P2 |
| CID name prefix | yes | ✔ | |
| Music on hold class per route | per organization, queue and ring group | ◐ | P3 |
| Signal RINGING, pause before answer | no | ✘ | P3 |
| Reject reverse charges | no | — PRI only | |
| Privacy Manager (callers without CID enter their number) | no | ✘ | P3 |
| Fax detection on the route | no | ✘ | P2 (with fax, §3.10) |
| Recording policy per route | recording policies can select DIDs | ✔ | |
| CID lookup source (OpenCNAM, HTTP, MySQL, internal) | no | ✘ | P2 |
| CID Superfecta (~90 sources, spam interception) | no | ✘ | P2 (spam interception is the valuable part) |
| Language per route | no | ✘ | P2 |
| Time condition on the route | yes (after-hours destination) | ✔ | |
| Destination types | extension, voicemail, shared inbox, IVR, ring group, queue, hang-up; the rest of this document adds more | ✔ | |
| **Bulk DID import** | no | ✘ | **P1** (migration) |

### 3.4 Outbound routing and dialing restrictions

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| Ordered routes with prepend/prefix/match patterns, trunk failover sequence | yes | ✔ | |
| CallerID column per pattern (route only for some extensions) | no | ✘ | P2 |
| Route caller ID override | yes | ✔ | |
| Emergency route type (forces emergency CID) | yes, evaluated first, site-bound routes, notification | ✔ ahead | |
| Route password | no | ✘ | P3 |
| PIN sets (prompt for PIN, record in CDR) and Pinset Pro (per-extension pinless dialing, PIN reports) | no | ✘ | P2 |
| **Class of Service** (allow/deny routes, feature codes, groups, queues, conferences, paging per class of extensions) and **Extension Routing** (allowed extensions per route) | routes can be owned by one organization; nothing per extension | ✘ | **P1** |
| Intra-company route type | no | ✘ | P3 |
| Time group restriction on a route | no | ✘ | P2 |
| Music on hold on outbound | no | ✘ | P3 |
| Destination on congestion, Route Congestion Messages | congestion tone only | ◐ | P3 |
| Dial pattern wizards (local NPA-NXX, toll-free, N11, 911/933 with prefixes) | no | ✘ | P3 |
| CSV import/export of patterns, duplicate route | no | ✘ | P3 |
| Caller ID Management (CID presets by feature-code prefix) | no | ✘ | P3 |
| Outbound Call Limit (same number N times per period) | no | ✘ | P3 (compliance niche) |
| Outbound CNAM lookup | no | ✘ | P3 |
| Loop prevention, Max-Forwards | yes | ✔ ahead | |

### 3.5 Call handling applications and feature codes

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| IVR: prompt, timeout, retries, direct dial, fallbacks, nesting | yes | ✔ | |
| IVR: multi-digit and hidden entries | single keys 0–9, *, # | ◐ | P2 |
| IVR: return to parent IVR on invalid/timeout, return after voicemail | fixed fallbacks | ◐ | P2 |
| IVR Pro (speech) | no | — a module, after transcription exists | |
| **Announcements** (play a recording, then go on; repeat key, skip, early media) | no standalone destination | ✘ | **P1** |
| **Directory** (dial by name, name announcements, custom entries) | no | ✘ | **P1** |
| Languages destination and **Sound Languages** packs (Spanish, French…) | English only | ✘ | P2 (Spanish is a P1 wish in US schools) |
| Text to Speech destination and engines | no | ✘ | P3 (module) |
| Time conditions with time zone, holidays, "open now" | yes | ✔ | |
| Reusable time groups | schedule lives in the condition | ◐ | P3 |
| Floating holidays (fourth Thursday) and month-day ranges | fixed MM-DD holidays | ◐ | P2 |
| Calendar-driven time conditions (Google, iCal, CalDAV, Outlook) | calendars exist and drive bells, not time conditions | ◐ | P2 (small: link the existing calendars) |
| **Time condition override** (feature code, BLF, temporary vs permanent, PIN) | no | ✘ | **P1** |
| **Call Flow Control** (day/night toggles `*28x`, BLF, 100 switches) | no | ✘ | **P1** |
| Ring groups: ringall, sequential | yes | ✔ | |
| Ring groups: hunt, memory hunt, first available, random, `-prim` variants | no | ◐ | P2 |
| **Ring groups: external numbers as members** | no | ✘ | **P1** (with follow-me) |
| Ring groups: confirm calls (press 1), remote announce | no | ✘ | P2 |
| Ring groups: alert-info, ringer volume, progress, ignore CF, answered elsewhere | no | ✘ | P2 |
| Ring groups: CID prefix, MOH, skip busy, failover, pickup | yes | ✔ | |
| Queues: eight strategies | six (no rrordered, wrandom) | ◐ | P3 |
| **Queues: dynamic agents, log in/out and pause** (`*45/*46/*47`, BLF hints) | static agents only | ✘ | **P1** |
| Queues: pause reason codes (VQ Plus) | no | ✘ | P2 |
| Queues: auto-pause on no answer, member delay, agent announcement, report hold time | no | ✘ | P2 |
| Queues: join/leave-empty modes, max callers, max wait, failover, wrap-up, penalties, announcements, periodic announcements | yes | ✔ | |
| **Queues: IVR break-out menu** (press a key during hold to leave voicemail) | no | ✘ | **P1** |
| Queues: hold-time announcement | off | ✘ | P2 |
| Queues: queue weight, Queue Priorities destination | no | ✘ | P3 |
| Queues: call confirm for external agents | no | ✘ | P2 |
| Queue Callback, virtual queues, penalty rules (VQ Plus, $475) | no | ✘ | P2 |
| Queue Wallboard ($395/yr) and live queue view | no live view | ✘ | P2 |
| Q-Xact queue reports ($795) | report builder covers distribution by queue, hour, day, agent and service level; no agent availability or missed-call detail | ◐ | P2 |
| Supervisor monitor/whisper/barge (Sangoma Desktop queue licences) | no | ✘ | P2 |
| **Conferences** (ConfBridge rooms, PINs, `*` menu, recording, max participants) | no | ✘ | **P1** |
| Conference Pro (user control from the portal, personal rooms, conference IVR) | no | ✘ | P2 |
| **Parking** (lot, slots, BLF per slot, timeout return, courtesy tone) | no | ✘ | **P1** |
| Park Pro (several lots, private lots, `*86`) and Park & Announce | no | ✘ | P2 / P3 |
| Paging groups, priority, pre-announcement, multicast, scheduler, calendar schedules (Page Pro) | yes: zones, multicast and Poly group pages in step, priority and emergency kinds, pre-tone, repeat, bell schedules from calendars, page log | ✔ ahead | |
| Outbound notification on an outbound route (page on 911 with barge) | emergency on-site notification (email, page, responder phones, webhook) | ✔ (no barge) | |
| **Intercom** (`*80<ext>`, allow/deny per user) | no | ✘ | **P1** |
| Duplex paging, busy handling skip/force/whisper | no | ✘ | P2 |
| Valet (airport-style recorded) paging | no | ✘ | P3 |
| Live page from the browser | no | ✘ | P2 |
| Callback destination | no | ✘ | P3 |
| DISA | no | ✘ | P2 |
| **Blacklist** (block numbers, block anonymous, `*30/*32`, CSV, statistics) | firewall blocks addresses, not callers | ✘ | **P1** |
| Allow list (only known callers get through) | no | ✘ | P3 |
| Set CallerID destination | no | ✘ | P3 |
| Misc Destinations, Misc Applications (own feature codes to any destination) | no | ✘ | P2 |
| **Custom Destinations / custom dialplan** (`extensions_custom.conf`, Config Edit) | configuration is generated and verified; no escape hatch | ✘ | P2: a reviewed "custom dialplan include" that the verifier checks, not a raw file editor |
| Dynamic Routes (DTMF or lookup-based routing) | no | ✘ | P3 (module) |
| Wake Up Calls | no | ✘ | P3 (module) |
| Voicemail Blasting | no | ✘ | P3 |
| Speed dial codes (`*0`, `*75`, Contact Manager `*10`) | Companion personal speed dials | ◐ | P3 |
| Info services: `*43` echo, `*60` clock | yes | ✔ | |
| Info services: `*65` speak extension, `*69` call trace | no | ✘ | P3 |
| **In-call feature codes**: `*2` attended / `##` blind transfer, `*1` on-demand recording | not configured (phone transfer keys work through SIP REFER) | ✘ | P2 (softphones and ATAs need them; `*1` goes with recording) |
| ChanSpy `555`, `777` simulate call | no | ✘ | P3 |
| **Direct transfer to voicemail** (`*<ext>`) | `*98` any box with PIN | ✘ | **P1** |
| Feature Codes admin (rename, enable per code) | fixed codes | ✘ | P2 |
| Presence State (admin-defined states driving DND/follow-me) | no | ✘ | P2 (with the portal) |

### 3.6 Voicemail

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| Mailbox per extension: PIN, email, attach, delete after email, envelope, CID | yes, PIN encrypted and user-changeable | ✔ | |
| Shared mailboxes with MWI on member phones | yes | ✔ ahead | |
| Voicemail to email with retrying queue | yes | ✔ | |
| MWI | yes | ✔ | |
| Pager (short) email, several addresses | no | ✘ | P3 |
| Per-mailbox options (review, operator, callback, timezone, maxmsg…) | global settings | ◐ | P3 |
| **Operator extension ("press 0")** and VmX Locater (press 0/1/2 to other destinations) | no | ✘ | **P1** |
| Greetings: unavailable, busy, name, temporary | from the phone menu | ◐ | |
| **Greeting upload and browser recording** | no | ✘ | **P1** (with the portal) |
| **Web inbox / visual voicemail** (play, forward, download, delete, folders) | no | ✘ | **P1** (with the portal) |
| Transcription and summaries (Scribe, $24.99/month) | no | ✘ | P2 (module; a local model keeps audio on premises) |
| Voicemail Admin: usage and stats, delete messages, edit any mailbox | box settings only | ◐ | P2 |
| Email subject/body templates | fixed | ◐ | P3 |
| IMAP / ODBC storage | no | — not planned | |
| VM Notify (call a list until someone accepts, $75) | no | ✘ | P3 |
| Voicemail Reports ($25) | no | ✘ | P3 |
| BLF hint on a mailbox | MWI yes; hint no | ◐ | P3 |
| Voicemail pruning by age | retention does not cover voicemail | ✘ | P2 |

### 3.7 Recording, call history, reports

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| CDR search and CSV | call history with folded legs, filters, CSV, recent calls per user | ✔ (equals CDR Pro's unified record) | |
| Call Event Logging (per-call event detail) | no | ✘ | P3 |
| Recording playback and download in CDR and the portal | yes, audited, permission for own calls | ✔ ahead | |
| Call Recording Reports ($99): by month, archive, push archives to remote storage | listing yes; archive to remote storage no | ◐ | P2 |
| On-demand recording | no | ✘ | P2 |
| CDR Pro ($299/yr): graphs, scheduled reports, exports | report builder, scheduled CSV email, dashboards | ✔ | |
| Media Experience Score | no | ✘ | P3 |
| PBX Call Accounting ($400/yr): rate decks, cost reports | no | — billing is out of scope (REPORTING.md §11); a module if asked | |
| Asterisk Info (registries, channels, BLF subscriptions, queues, voicemail counts live) | registrations and active calls | ◐ | P2 (a live queue and subscription view) |
| Asterisk Logfiles and Asterisk CLI in the browser | no | ✘ | P2 (a diagnostics page: log tail, `pjsip show`, with audit) |
| System dashboard with graphs and notifications | yes | ✔ | |
| Alerts by email | yes, 20 built-in rules | ✔ ahead | |
| Prometheus metrics | yes | ✔ ahead | |
| Pinset reports | no | ✘ | with PIN sets |

### 3.8 End-user tools

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| **UCP user portal**: dashboards with widgets for voicemail, call history, call forwarding, call waiting, DND, follow-me, contacts, presence, settings | account page (PIN, recent calls, sessions, tokens, MFA, SSO, theme) | ◐ | **P1** |
| UCP templates per group | no | ✘ | P3 |
| Click-to-dial from the desk phone | yes (web and Companion) | ✔ | |
| Incoming-call pop-up with caller lookup | Companion notification (internal directory) | ◐ | P2 (external lookup) |
| Missed call notification by email | Companion notification only | ◐ | P2 |
| Contact Manager (external contacts, groups, speed dials, CID source, visibility per group) | internal directory only | ◐ | P2 |
| WebRTC browser phone | no | ✘ | P2 |
| Sangoma Talk / Phone Desktop softphones ($19/user/yr), push notifications, video, chat, SMS | no own softphone | ✘ | P2: document and provision third-party SIP softphones first; an own client later |
| Presence (states, auto DND/follow-me) | no | ✘ | P2 |
| Chat / XMPP | no | — out of scope | |
| SMS/MMS (SIPStation DIDs) | no | ✘ | P3 (module per carrier API) |
| Sangoma Meet video | no | — out of scope | |
| CRM Link ($275): call logging, screen pop, click-to-call for Salesforce, Sugar, Zoho, ConnectWise; Zapier | REST API, signed webhooks, integration tokens; no CRM connectors | ◐ | P3 (Zapier/Make recipe on webhooks first) |
| Phone Apps ($499): visual voicemail, parking, queue login, DND, follow-me, time conditions on the phone screen | no | ✘ | P3 (after the features; Yealink/Poly XML apps) |
| Web Call Me ($50) | no | ✘ | P3 |
| Browser extension (Companion): tel: links, directory, notifications, SSO | yes | ✔ ahead (FreePBX has nothing comparable) | |

### 3.9 Devices and provisioning

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| **EndPoint Manager ($199): 22 brands, several hundred models** | Poly VVX 410/411/450 official templates (experimental, not hardware-verified); other brands as local templates | ✘ | **P1**: Yealink (T3x/T4x/T5x), Grandstream (GRP/GXP), Poly Edge/CCX, an ATA (Grandstream HT, Cisco ATA 19x), Algo and CyberData paging endpoints; P2: Snom, Cisco MPP, Fanvil, Sangoma |
| Template editor with raw parameter override (basefile edit) | template editor, customize, import/export, facts | ✔ ahead | |
| Button types: line, BLF, speed dial, park, transfer, voicemail, intercom, DND, record, XML app | line, BLF, speed dial, page | ◐ | **P1** (park, voicemail, transfer, intercom, DND once those exist) |
| Expansion modules (sidecars) | no | ✘ | P2 |
| Background image, ring tones, screensaver | no | ✘ | P3 |
| Firmware slots and Sangoma's firmware list | upload and assign | ◐ | P3 |
| Zero-touch: PnP, option 66, vendor redirect (Sangoma RPS) | DHCP 66/160 plus Poly HTTP bootstrap | ◐ | P2: Yealink RPS and Poly ZTP registration, Grandstream GDMS |
| Network scan for unprovisioned phones | "phones seen but not registered" list | ◐ | P3 |
| Extension mapping, multi-account phones, DECT bases | devices with several lines | ✔ | |
| Phone directory served to phones (LDAP/XML) | no | ✘ | P2 |
| Hot desking (EndPoint Login app) | no | ✘ | P2 |
| UCP for EPM (users edit their own keys) | no | ✘ | P3 |
| VPN pairing for remote phones (Sysadmin Pro OpenVPN) | no | ✘ | P3 |
| HTTPS provisioning with credentials | yes, plus per-device credentials and a CA bootstrap | ✔ ahead | |
| TFTP/FTP provisioning | no | — insecure; HTTPS only by design | |
| Reboot and resync over SIP NOTIFY | Poly and Yealink | ✔ | |
| Hardware verification | Poly VVX not yet verified on hardware | ✘ | **P1** |

### 3.10 Fax

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| Inbound fax to email (res_fax, T.38, SpanDSP), fax detection, system fax number | nothing | ✘ | P2 |
| Fax Pro ($150): outbound fax from the portal, cover pages, storage, folders, retries, per-user settings, T.38 gateway on routes | nothing | ✘ | P3 (module) |
| Fax through an ATA (G.711 pass-through, T.38 to the ATA) | works today as a plain extension; not documented | ◐ | P2 (document and test; the pragmatic answer for most sites) |

### 3.11 System administration

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| Installer (Debian 12 script or ISO) | Ubuntu 24.04/26.04 installer with preflight, verify, upgrade, uninstall | ✔ ahead | |
| Installable ISO | no | ✘ | P3 |
| Module Admin, Edge track, rollback | signed modules, catalogue, channels, rollback | ✔ | |
| Automatic updates with schedule | signed releases, maintenance windows, approval, idle wait | ✔ ahead | |
| OS package updates from the GUI | listed, not applied | ◐ | P2 |
| Backup & Restore: per-module selection, schedule, retention | full backups, verified by test restore, encrypted, pruned, restore to a new server | ✔ ahead on verification | |
| **Filestore destinations: FTP/SFTP, SSH, S3, Dropbox, email** | local store plus a mounted copy directory | ✘ | **P1**: SFTP and S3 (design question 1) |
| Warm spare | HA (active/passive) covers it | ✔ | |
| Advanced Recovery ($400/server/yr): warm spare with automatic switchover | HA with operator-run switchover; no automatic failover, no witness | ◐ | P2 (automatic failover after stage 2) |
| Firewall: zones, responsive firewall, intrusion detection, trunk auto-allow | nftables table, per-service allow lists, timed bans from engine/NGINX/provisioning events, permanent allow list, feeds, self-block protection | ✔ ahead | |
| Firewall: custom rules files | no | ✘ | P3 |
| Certificate Manager: **Let's Encrypt** | own CA with name constraints; custom certificate by hand | ✘ | **P1** |
| Certificate Manager: upload, CSR, per-use assignment | by hand | ◐ | P2 |
| Sysadmin: network settings (static/DHCP, VLAN), hostname, DNS, time zone in the GUI | time zone per organization; the rest at OS level ("coming later" on the Settings page) | ◐ | P2 |
| Sysadmin Pro ($39): email setup | SMTP with test button | ✔ | |
| Sysadmin Pro: DDNS, DHCP server, OpenVPN server, support VPN, UPS, packet capture, port management, power | no | ✘ | P3 (packet capture and UPS first) |
| Intrusion detection (fail2ban) | built in | ✔ | |
| Storage thresholds and alerts | disk_space alert | ✔ | |
| User Management: users, groups, permissions | users, six system roles, custom roles, scoped by organization and site | ✔ | |
| Directories: Active Directory / OpenLDAP sync | no | ✘ | P2 |
| Login with Google/Microsoft (OIDC) | yes, with silent sign-in in managed Chrome | ✔ ahead (FreePBX has none; SAML is paid) | |
| SAML | no | ✘ | P3 |
| MFA: TOTP, email OTP, call-to-extension, trusted device 30 days (free since 2025) | TOTP and recovery codes, policy per role | ◐ | P2 (trusted device, passkeys) |
| Password policy: expiry, complexity | minimum 12 characters, lockout | ◐ | P3 |
| Welcome email to new users | no | ✘ | P3 |
| **Bulk Handler** (CSV import/export of extensions, DIDs, users, contacts) | no | ✘ | **P1** |
| **Import from FreePBX** (backup tarball or CSV: extensions, DIDs, voicemail, ring groups, queues, IVRs, time conditions) | no | ✘ | **P1** for adoption |
| API: GraphQL + REST with OAuth2 app flows | REST, WebSocket events, integration tokens with scopes, signed webhooks | ✔ (no GraphQL by design) | |
| AMI / ARI user management for third-party tools (FOP2, wallboards, dialers) | ARI internal only | ✘ | P3 (scoped external ARI access) |
| Config Edit (raw Asterisk files) | no | — generated configuration by design; see custom dialplan include in §3.5 | |
| Asterisk SIP settings: NAT, RTP range, codecs, transports | yes | ✔ | |
| Advanced Settings (hundreds of toggles) | opinionated defaults | — by design; specific toggles are added as needed | |
| GUI translations | English only, no i18n framework | ✘ | P2 |
| Multi-tenancy, central console, audit log, retention, key rotation | yes | ✔ ahead (none in FreePBX) | |

### 3.12 Vertical and campaign modules

| FreePBX capability | Veyra 0.23.0 | Gap | Priority |
|---|---|---|---|
| Sangoma Property Management (hotel PMS, free to 10 rooms) | no | — not a Veyra market | |
| Appointment Reminder ($795) | no | ✘ | P3 (module) |
| **Broadcast / XactDialer ($795)**: voice broadcast campaigns, CSV lists, AMD, remote toggle (school closings) | no | ✘ | P2 (module; the school-closing case is Veyra's audience) |
| Web Call Me ($50) | no | ✘ | P3 |
| Outbound Call Limit ($195) | no | ✘ | P3 |
| Contact Image (door phone still image) | no | — Sangoma-phone specific | |
| Scribe (transcription, summaries, sentiment, TTS) | no | ✘ | P2 (module, see §3.6) |
| Sangoma Meet | no | — out of scope | |
| SMS | no | ✘ | P3 |
| High Availability (legacy DRBD module, EOL) | built in | ✔ | |

## 4. Recommendations

The P1 rows cluster into four pieces of work. Each is sized for one
milestone in the project's usual rhythm, and together they are what
"FreePBX parity for the core" would mean on the public release.

1. **Everyday call features** (extension and dialplan work, mostly
   generator and small UI): DND, call forwarding, find-me/follow-me with
   external numbers (and external members in ring groups), call waiting,
   intercom and auto-answer, per-extension outbound caller ID, parking
   with BLF, conferences, announcements, dial-by-name directory,
   transfer to voicemail and "press 0", call-flow toggles and
   time-condition overrides, blacklist, queue agent log-in/pause and the
   break-out menu, class of service with allowed routes, in-call
   transfer and on-demand recording codes, a feature-code page. Secure
   SIP (TLS and SRTP per device profile) belongs here or in 17b.
2. **User portal**: a self-service area for standard users (web first,
   Companion second): voicemail inbox with playback, greetings upload and
   recording, forwarding, DND and follow-me controls, call history with
   recordings they may hear, personal contacts and speed dials, presence.
   Most of the backend exists; this is the FreePBX UCP in Veyra's style.
3. **Provisioning breadth**: official, hardware-verified templates for
   Yealink, Grandstream, Poly (VVX verified, Edge added), one ATA, Algo
   and CyberData; key types for park, voicemail, transfer, intercom and
   DND; a phone directory; vendor redirect services (Yealink RPS, Poly
   ZTP); expansion modules and hot desking as P2 follow-ons.
4. **Adoption and operations**: bulk CSV import and export, an importer
   that reads a FreePBX backup, Let's Encrypt, SFTP and S3 backup
   destinations, trunk registration state, a diagnostics page (log tail
   and engine queries with audit), the custom-dialplan include. This is
   what makes a FreePBX site willing to move.

After 1.0 the P2 items group naturally into optional modules, which is
also where FreePBX charges for them: a contact-centre pack (callback,
wallboard, supervisor functions, pause codes, agent reports), fax
(inbound to email first, then outbound), broadcast campaigns for school
closings and civic notices, voicemail transcription with an on-premises
model, sound-language packs and interface translations, directory sync
from Active Directory, a WebRTC phone, SMS through carrier APIs, CRM
recipes on the webhooks, and automatic HA failover once stage 2 has run
on two real servers.

Deliberately not planned, so that the public release can say so plainly:
telephony cards (DAHDI, PRI, FXS/FXO; gateways and ATAs instead), IAX2,
ENUM and DUNDi, TFTP/FTP provisioning, raw configuration file editing,
IMAP voicemail storage, chat and video meetings, hotel property
management, and billing.

Nothing in this document changes the Milestone 18 scope on its own. The
owner decides which of the four pieces run before the public release and
which follow it; the honest alternative is to release 1.0 with the gaps
stated and the four milestones published on the roadmap.

## 5. Tracking

Every ✘ and ◐ row above becomes a GitHub issue labelled `gap:freepbx`
with its priority label, grouped under four tracking issues that mirror
section 4, so that the roadmap, the issues and this document agree. When
a row is closed, this document is updated in the same pull request.

## 6. Sources

FreePBX and Sangoma material was read on 2026-10-16 from the Sangoma
documentation wiki (sangomakb.atlassian.net, spaces PG, FP, SS1, SAF,
PP), the FreePBX GitHub organizations, the FreePBX community forum and
reseller price lists; the two catalogues under `docs/research/` cite the
page for every section and note what could not be confirmed. Prices are
reseller sale prices in USD and will drift. Veyra facts are from the
repository at 0.23.0 (commit 3bdb81c): `docs/`, the milestone reports,
`backend/veyra/telephony/asterisk/generator.py`, the API routers and the
frontend page tree.
