# FreePBX feature gap analysis

Veyra 0.27.67 compared with FreePBX 16/17, every free module and every
Sangoma commercial module (FreePBX add-ons and PBXact), as of
2026-10-31. First written before the public release (now Milestone 23) so that no
FreePBX feature is left out of the roadmap only because the current
feature set felt good enough.

A ✔ means the code exists. Nearly everything is verified only by automated
tests, not on phones; live tests are tracked on GitHub Project #7. The
interface now calls device profiles "templates" and provisioning templates
"base files".

Companion documents: the raw catalogues this analysis was built from are
[research/freepbx-open-source-catalogue.md](research/freepbx-open-source-catalogue.md)
(91 free modules and areas, with the option lists and feature codes) and
[research/freepbx-commercial-catalogue.md](research/freepbx-commercial-catalogue.md)
(38 commercial modules, bundles, licensing and 2026 reseller prices). Both
cite the Sangoma wiki page for every section. The Veyra side comes from
the code at 0.27.67, `CHANGELOG.md` and `docs/`; the FreePBX side is as read
on 2026-10-16.

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

Counting every capability row below: Veyra has 103 (✔), has part of 58
(◐), lacks 76 (✘) and deliberately leaves out 19 (—). The numbers flatter
neither side: most missing rows are P2 or P3, while several things Veyra has (multi-tenancy, a central
console, signed updates, built-in HA, the paging engine, OIDC) FreePBX
does not offer at any price.

*Historical: this list was written for 0.23.0 and most of it is now built;
the tables in section 3 are current.*

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

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| PJSIP extension with generated strong secret | PJSIP only, 24-character generated secret, encrypted at rest, show/rotate audited | ✔ | |
| IAX2 and DAHDI (FXS card) extensions | not supported | — analog ports belong on an ATA or gateway registered as PJSIP; no card support planned | |
| Virtual extension (voicemail and follow-me without a device) | an extension needs no device; voicemail, forwards and follow-me work without one; no separate "virtual" type | ✔ | P2 (with follow-me) |
| Custom/other extension (free-form dial string) | no | ✘ | P3 |
| Display name and internal caller ID | yes | ✔ | |
| **Outbound caller ID per extension** (`"name" <number>` on trunks) | outbound number and name per extension, checked against the organization's DIDs or an allow list; precedence emergency → forced route → extension → route → trunk default | ✔ | **P1** |
| Emergency caller ID per extension | yes, plus ELIN per site, location per extension and device, readiness checks | ✔ ahead | |
| Do Not Disturb (`*78/*79/*76`, portal, presence-driven) | `*78/*79/*76`, extension page, My Phone and presence rules; lit BLF key; callers who still ring, per phone and per organization | ✔ | **P1** |
| Call forwarding unconditional, busy, no-answer (`*72/*73`, `*90/*91`, `*52/*53`, remote variants, ring timer) | always, busy, no answer and offline, with ring time; `*72/*73`, `*90/*91`, `*52/*53`, extension page, My Phone; no remote-variant codes for another extension's forward | ◐ | **P1** |
| Find Me / Follow Me (external numbers, strategies, confirm calls, calendar-linked, `*21`) | ring-all or in-turn legs, external numbers, desk phone first, press-1 confirm, caller ID mode, no-answer destination, `*21`; not calendar-linked | ◐ | **P1** |
| Call waiting toggle (`*70/*71`) | switch on the call handling card and `*70<number>` for one call; no lasting on/off code from the phone | ◐ | P2 |
| Internal auto-answer / intercom per extension | `*80<ext>` with auto-answer headers, allow or deny per extension with an organization default; base files set the phone's auto-answer | ✔ | **P1** (with intercom, §3.5) |
| Outbound concurrency limit per extension | a class of service caps its phones' outside calls together; no limit per extension | ◐ | P2 (toll-fraud control) |
| Ring time per extension | per extension, from the extension page and My Phone | ✔ | P3 |
| Optional destinations: no answer, busy, not reachable | forward targets for busy, no answer and offline, or voicemail; numbers only, not any destination type | ◐ | P2 |
| Recording options per extension (four directions, on-demand allow/override, priority) | policies select extensions and inbound, outbound or internal calls; on-demand `*1`, allowed per class of service; no per-direction flags or priority on the extension | ◐ | P2 |
| Call screening (caller says name) | no | ✘ | P3 |
| Dictation service | no | — not planned | |
| Media encryption per extension (SRTP, DTLS) and TLS transport | TLS transport installation-wide; SDES SRTP off, optional or required per template, Poly and Yealink only, needs TLS; no DTLS | ◐ | **P1** (secure SIP, design question 4 in PRODUCTION_HARDENING.md) |
| Max contacts (several phones on one extension) | yes, up to 16 | ✔ | |
| Call groups and pickup groups | yes | ✔ | |
| Account code, CID number alias, SIP alias | no | ✘ | P3 |
| Language per extension | installation-wide default only | ✘ | P2 (with sound languages) |
| Hot desking (Device & User mode, log-in/log-out codes, phone app) | no | ✘ | P2 |
| Camp-on (CCSS) | no | — rarely used; not planned | |
| Queue state detection flag | queues use device state; no override | ◐ | P3 |
| Add inbound DID from the extension page | inbound routes are created on their own page | ◐ | P3 |
| **Bulk CSV import/export of extensions** (Bulk Handler) | System → Import and Export, CSV with a check before import | ✔ | **P1** (see migration, §3.11) |
| Extension Settings report (DND/CF/FM state table) | no such report, though the features now exist | ✘ | P3 after the features exist |
| Print Extensions (every dialable number) | no printable list; CSV exports and the phone directory list extensions and ring groups | ◐ | P3 |
| Weak password detection | not needed: secrets are generated and never typed | ✔ by construction | |

### 3.2 Trunks

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| PJSIP trunk, registration or IP authentication, UDP/TCP/TLS | yes | ✔ | |
| IAX2 trunks | no | — not planned unless an installation asks | |
| DAHDI/PRI/analog trunks (cards) | no | — gateways (Sangoma Vega, Grandstream, Patton) register as PJSIP trunks; no card support planned | |
| ENUM and DUNDi trunks | no | — DUNDi is gone from FreePBX 17 too | |
| Custom trunk (dial string) | no | ✘ | P3 |
| Outbound caller ID per trunk | yes | ✔ | |
| CID options: allow any / block foreign / remove CNAM / force trunk CID | trunk default caller ID and PAI/RPID header choice; a route can force its number; no block-foreign or remove-CNAM options | ◐ | P2 |
| Maximum channels | yes | ✔ | |
| Continue if busy | no; the next trunk is tried on unavailable or congestion only | ✘ | P3 |
| Dial manipulation rules per trunk (prepend/prefix/match) | per outbound route only | ◐ | P2 |
| Registration tuning (retry interval, forbidden retry, max retries, expiration) | all four (0.27.8, #142) | ✔ | — |
| **Registration state shown** (registered / rejected / retrying) | registered, rejected, registering or unregistered on the trunk page, Registrations and the `trunk_down` alert | ✔ | **P1** |
| Outbound proxy, contact user, codecs, qualify, DTMF mode, PAI/RPID | yes | ✔ | |
| Inbound channel counting per trunk | no; the trunk report shows only the most calls up at once | ✘ | P3 |
| Trunk down alert | yes | ✔ | |
| Carrier presets / provider-specific settings | no | ✘ | P3 (document presets for the common US carriers) |
| SIPStation-style provider wizard (DIDs, E911, SMS from the carrier account) | no | — carrier-specific; a module if a partner carrier appears | |

### 3.3 Inbound routing

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| DID match, catch-all, per-trunk restriction | yes, with NANP aliasing | ✔ | |
| DID patterns (`_1NXX...`) | exact DIDs only | ◐ | P3 |
| Caller-ID based routing (CID number, anonymous/blocked/unknown) | no | ✘ | P2 |
| CID priority routes | no | ✘ | P3 |
| Alert-Info (distinctive ring, auto-answer) | ring groups send Alert-Info; none on the route, no auto-answer option | ◐ | P2 |
| CID name prefix | yes | ✔ | |
| Music on hold class per route | per queue, ring group and conference room; none on the route | ◐ | P3 |
| Signal RINGING, pause before answer | no | ✘ | P3 |
| Reject reverse charges | no | — PRI only | |
| Privacy Manager (callers without CID enter their number) | no | ✘ | P3 |
| Fax detection on the route | no detection; a route can send a whole DID to a fax inbox | ✘ | P2 (with fax, §3.10) |
| Recording policy per route | recording policies can select DIDs | ✔ | |
| CID lookup source (OpenCNAM, HTTP, MySQL, internal) | no | ✘ | P2 |
| CID Superfecta (~90 sources, spam interception) | no | ✘ | P2 (spam interception is the valuable part) |
| Language per route | no | ✘ | P2 |
| Time condition on the route | yes (after-hours destination) | ✔ | |
| Destination types | extension, voicemail, shared inbox, IVR, ring group, queue, announcement, conference, call flow, directory, fax inbox, custom dialplan context, hang-up | ✔ | |
| **Bulk DID import** | inbound routes in the CSV import and export; also from the FreePBX importer | ✔ | **P1** (migration) |

### 3.4 Outbound routing and dialing restrictions

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| Ordered routes with prepend/prefix/match patterns, trunk failover sequence | yes | ✔ | |
| CallerID column per pattern (route only for some extensions) | no | ✘ | P2 |
| Route caller ID override | yes | ✔ | |
| Emergency route type (forces emergency CID) | yes, evaluated first, site-bound routes, notification | ✔ ahead | |
| Route password | no | ✘ | P3 |
| PIN sets (prompt for PIN, record in CDR) and Pinset Pro (per-extension pinless dialing, PIN reports) | no | ✘ | P2 |
| **Class of Service** (allow/deny routes, feature codes, groups, queues, conferences, paging per class of extensions) and **Extension Routing** (allowed extensions per route) | classes of service per organization: allowed outbound routes and feature codes, outside forwards and follow-me, intercom, fax, monitoring, outside-call cap; no restriction by ring group, queue or conference, and paging is limited per page, not per class | ◐ | **P1** |
| Intra-company route type | no | ✘ | P3 |
| Time group restriction on a route | no | ✘ | P2 |
| Music on hold on outbound | no | ✘ | P3 |
| Destination on congestion, Route Congestion Messages | all-circuits-busy prompt and congestion tone; no destination or per-route message | ◐ | P3 |
| Dial pattern wizards (local NPA-NXX, toll-free, N11, 911/933 with prefixes) | no wizard; a pattern editor with an example | ✘ | P3 |
| CSV import/export of patterns, duplicate route | no | ✘ | P3 |
| Caller ID Management (CID presets by feature-code prefix) | `*67` hides the number on one call; no CID presets | ✘ | P3 |
| Outbound Call Limit (same number N times per period) | no | ✘ | P3 (compliance niche) |
| Outbound CNAM lookup | no | ✘ | P3 |
| Loop prevention, Max-Forwards | yes | ✔ ahead | |

### 3.5 Call handling applications and feature codes

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| IVR: prompt, timeout, retries, direct dial, fallbacks, nesting | yes | ✔ | |
| IVR: multi-digit and hidden entries | single keys 0–9, *, # | ◐ | P2 |
| IVR: return to parent IVR on invalid/timeout, return after voicemail | timeout and invalid destinations can name any menu; no automatic return, no return after voicemail | ◐ | P2 |
| IVR Pro (speech) | no | — a module, after transcription exists | |
| **Announcements** (play a recording, then go on; repeat key, skip, early media) | Telephony → Announcements: skip with any key, repeat key, then any destination; always answers, no early media | ✔ | **P1** |
| **Directory** (dial by name, name announcements, custom entries) | spell a first or last name; custom names and an operator on Telephony → Dial by Name | ✔ | **P1** |
| Languages destination and **Sound Languages** packs (Spanish, French…) | English only: the installer ships only the English sound package and nothing switches language | ✘ | P2 (Spanish is a P1 wish in US schools) |
| Text to Speech destination and engines | no | ✘ | P3 (module) |
| Time conditions with time zone, holidays, "open now" | yes | ✔ | |
| Reusable time groups | schedule lives in the condition | ◐ | P3 |
| Floating holidays (fourth Thursday) and month-day ranges | yearly dates and ranges, one-off dates and ranges, weekday rules (0.27.1, #113) | ✔ | — |
| Calendar-driven time conditions (Google, iCal, CalDAV, Outlook) | calendars exist and drive bells, not time conditions | ◐ | P2 (small: link the existing calendars) |
| **Time condition override** (feature code, BLF, temporary vs permanent, PIN) | `*27<index>`, lit BLF, temporary or permanent, optional PIN, also from the page | ✔ | **P1** |
| **Call Flow Control** (day/night toggles `*28x`, BLF, 100 switches) | Telephony → Call Flows: `*28<index>` (0–99), lit BLF, optional PIN, also from the page and API | ✔ | **P1** |
| Ring groups: ringall, sequential | yes | ✔ | |
| Ring groups: hunt, memory hunt, first available, random, `-prim` variants | circular, round robin, longest idle, skip after missed calls; no random, first available or `-prim` variants | ◐ | P2 |
| **Ring groups: external numbers as members** | up to ten outside numbers | ✔ | **P1** (with follow-me) |
| Ring groups: confirm calls (press 1), remote announce | press 1 for outside members only; no remote announce | ◐ | P2 |
| Ring groups: alert-info, ringer volume, progress, ignore CF, answered elsewhere | Alert-Info, answered elsewhere, ignore forwards; no ringer volume or progress | ◐ | P2 |
| Ring groups: CID prefix, MOH, skip busy, failover, pickup | yes | ✔ | |
| Queues: eight strategies | six (no rrordered, wrandom) | ◐ | P3 |
| **Queues: dynamic agents, log in/out and pause** (`*45/*46/*47`, BLF hints) | `*45/*46/*47`, queue page and API, BLF hints, per queue or all | ✔ | **P1** |
| Queues: pause reason codes (VQ Plus) | no | ✘ | P2 |
| Queues: auto-pause on no answer, member delay, agent announcement, report hold time | no | ✘ | P2 |
| Queues: join/leave-empty modes, max callers, max wait, failover, wrap-up, penalties, announcements, periodic announcements | yes | ✔ | |
| **Queues: IVR break-out menu** (press a key during hold to leave voicemail) | an IVR menu's keys work while waiting | ✔ | **P1** |
| Queues: hold-time announcement | off (`announce-holdtime=no`); no setting | ✘ | P2 |
| Queues: queue weight, Queue Priorities destination | no | ✘ | P3 |
| Queues: call confirm for external agents | no; agents are extensions | ✘ | P2 |
| Queue Callback, virtual queues, penalty rules (VQ Plus, $475) | penalties per agent only; no callback or virtual queues | ✘ | P2 |
| Queue Wallboard ($395/yr) and live queue view | queue page Agents card and `*47` waiting count; no live caller view or wallboard | ◐ | P2 |
| Q-Xact queue reports ($795) | report builder and queue report by queue, hour, day, agent and service level, agent logged-in and paused time, break-outs; no dedicated missed-call detail confirmed | ◐ | P2 |
| Supervisor monitor/whisper/barge (Sangoma Desktop queue licences) | listen, whisper and join by `*222/*223/*224` and from Calls, per class of service, optional beep | ✔ | P2 |
| **Conferences** (ConfBridge rooms, PINs, `*` menu, recording, max participants) | rooms with PINs, participant limit, wait for admin, recording; live control on the room page | ✔ | **P1** |
| Conference Pro (user control from the portal, personal rooms, conference IVR) | room owners get live controls in a My Phone widget; no personal rooms, no conference IVR | ◐ | P2 |
| **Parking** (lot, slots, BLF per slot, timeout return, courtesy tone) | lots, slots, lit BLF per slot, timeout return, courtesy tone, `*85<slot>` | ✔ | **P1** |
| Park Pro (several lots, private lots, `*86`) and Park & Announce | several lots; no private lots, no `*86`, no Park & Announce | ◐ | P2 / P3 |
| Paging groups, priority, pre-announcement, multicast, scheduler, calendar schedules (Page Pro) | yes: zones, multicast and Poly group pages in step, priority and emergency kinds, pre-tone, repeat, bell schedules from calendars, page log | ✔ ahead | |
| Outbound notification on an outbound route (page on 911 with barge) | emergency on-site notification (email, page, responder phones, webhook) | ✔ (no barge) | |
| **Intercom** (`*80<ext>`, allow/deny per user) | `*80<ext>`, allow or deny per extension or class of service | ✔ | **P1** |
| Duplex paging, busy handling skip/force/whisper | no | ✘ | P2 |
| Valet (airport-style recorded) paging | no | ✘ | P3 |
| Live page from the browser | recorded pages can start from the web; no live microphone page | ✘ | P2 |
| Callback destination | no | ✘ | P3 |
| DISA | no | ✘ | P2 |
| **Blacklist** (block numbers, block anonymous, `*30/*32`, CSV, statistics) | Telephony → Blocked Callers: numbers, anonymous, `*30/*31/*32`, CSV, hit counts, optional destination | ✔ | **P1** |
| Allow list (only known callers get through) | no; only per-phone Do Not Disturb exceptions | ✘ | P3 |
| Set CallerID destination | no | ✘ | P3 |
| Misc Destinations, Misc Applications (own feature codes to any destination) | no such objects; the custom dialplan can do it by hand | ✘ | P2 |
| **Custom Destinations / custom dialplan** (`extensions_custom.conf`, Config Edit) | platform administrators' own `[custom-…]` contexts, checked line by line, deployed like any change, usable as a destination; no raw file editor | ✔ | P2: a reviewed "custom dialplan include" that the verifier checks, not a raw file editor |
| Dynamic Routes (DTMF or lookup-based routing) | no | ✘ | P3 (module) |
| Wake Up Calls | no | ✘ | P3 (module) |
| Voicemail Blasting | no | ✘ | P3 |
| Speed dial codes (`*0`, `*75`, Contact Manager `*10`) | personal contacts with a speed-dial slot (1–99), Companion favourites, phone keys; no dial code confirmed | ◐ | P3 |
| Info services: `*43` echo, `*60` clock | yes | ✔ | |
| Info services: `*65` speak extension, `*69` call trace | `*69` here calls back the last caller; no `*65`, no call trace | ◐ | P3 |
| **In-call feature codes**: `*2` attended / `##` blind transfer, `*1` on-demand recording | `*1`, `*2`, `##`, adjustable and allowed per class of service | ✔ | P2 (softphones and ATAs need them; `*1` goes with recording) |
| ChanSpy `555`, `777` simulate call | `*222` listen covers ChanSpy, by class of service; no `777` | ◐ | P3 |
| **Direct transfer to voicemail** (`*<ext>`) | `*<ext>` plays the box's greeting, dialled or as a transfer target; `*98` any box with PIN | ✔ | **P1** |
| Feature Codes admin (rename, enable per code) | Telephony → Feature Codes: change or disable each code, load code sets; a few fixed codes stay | ✔ | P2 |
| Presence State (admin-defined states driving DND/follow-me) | six fixed states with the user's own DND or forward rules, `*37`, calendar; not admin-defined | ◐ | P2 (with the portal) |

### 3.6 Voicemail

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| Mailbox per extension: PIN, email, attach, delete after email, envelope, CID | yes, PIN encrypted and user-changeable | ✔ | |
| Shared mailboxes with MWI on member phones | yes | ✔ ahead | |
| Voicemail to email with retrying queue | yes | ✔ | |
| MWI | yes | ✔ | |
| Pager (short) email, several addresses | no | ✘ | P3 |
| Per-mailbox options (review, operator, callback, timezone, maxmsg…) | per box: ring time, operator, locater keys, message age, absence; review, callback and maxmsg stay global | ◐ | P3 |
| **Operator extension ("press 0")** and VmX Locater (press 0/1/2 to other destinations) | operator on 0, locater keys 1 and 2 during the greeting (follow-me or a number) | ✔ | **P1** |
| Greetings: unavailable, busy, name, temporary | unavailable, busy, name, temporary, plus extended absence and after hours; phone and web | ✔ | |
| **Greeting upload and browser recording** | upload or record in the browser on My Phone and the admin page | ✔ | **P1** (with the portal) |
| **Web inbox / visual voicemail** (play, forward, download, delete, folders) | My Phone and the admin page: play, download, folders, move, forward, email, delete, call me | ✔ | **P1** (with the portal) |
| Transcription and summaries (Scribe, $24.99/month) | no | ✘ | P2 (module; a local model keeps audio on premises) |
| Voicemail Admin: usage and stats, delete messages, edit any mailbox | edit any box, per-box message, new-message and storage counts, play, move, delete, bulk absence | ✔ | P2 |
| Email subject/body templates | fixed | ◐ | P3 |
| IMAP / ODBC storage | no | — not planned | |
| VM Notify (call a list until someone accepts, $75) | no | ✘ | P3 |
| Voicemail Reports ($25) | no; the Voicemail list shows usage per box | ✘ | P3 |
| BLF hint on a mailbox | MWI yes; hint no | ◐ | P3 |
| Voicemail pruning by age | "Delete messages older than" per box, once a day | ✔ | P2 |

### 3.7 Recording, call history, reports

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| CDR search and CSV | call history with folded legs, filters, CSV, recent calls per user | ✔ (equals CDR Pro's unified record) | |
| Call Event Logging (per-call event detail) | no | ✘ | P3 |
| Recording playback and download in CDR and the portal | yes, audited, permission for own calls | ✔ ahead | |
| Call Recording Reports ($99): by month, archive, push archives to remote storage | by policy and filters, ZIP export with CSV; recording archive to folder, SFTP, S3-compatible or Google Drive | ✔ | P2 |
| On-demand recording | `*1` from a phone, Record on Calls, per class of service | ✔ | P2 |
| CDR Pro ($299/yr): graphs, scheduled reports, exports | report builder, scheduled CSV email, dashboards | ✔ | |
| Media Experience Score | no | ✘ | P3 |
| PBX Call Accounting ($400/yr): rate decks, cost reports | no | — billing is out of scope (REPORTING.md §11); a module if asked | |
| Asterisk Info (registries, channels, BLF subscriptions, queues, voicemail counts live) | registrations, active calls, queue agents, voicemail usage and fixed queries (endpoints, contacts, channels, trunk registrations, states); no queue-caller or BLF subscription view | ◐ | P2 (a live queue and subscription view) |
| Asterisk Logfiles and Asterisk CLI in the browser | System → Diagnostics: audited log tail and fixed read-only engine queries; no free-form CLI | ◐ | P2 (a diagnostics page: log tail, `pjsip show`, with audit) |
| System dashboard with graphs and notifications | yes | ✔ | |
| Alerts by email | yes, 20 built-in rules | ✔ ahead | |
| Prometheus metrics | yes | ✔ ahead | |
| Pinset reports | no | ✘ | with PIN sets |

### 3.8 End-user tools

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| **UCP user portal**: dashboards with widgets for voicemail, call history, call forwarding, call waiting, DND, follow-me, contacts, presence, settings | My Phone: widget canvas with voicemail, recent calls, forwards, call waiting, DND, follow-me, contacts, presence, phone keys, fax, conference | ✔ | **P1** |
| UCP templates per group | portal layouts by system, organization, building, department or role, with locked widgets | ✔ | P3 |
| Click-to-dial from the desk phone | yes (web and Companion) | ✔ | |
| Incoming-call pop-up with caller lookup | Companion notification; personal contacts name callers; no external lookup source | ◐ | P2 (external lookup) |
| Missed call notification by email | per-user email for each unanswered call | ✔ | P2 |
| Contact Manager (external contacts, groups, speed dials, CID source, visibility per group) | personal contacts with CSV and speed dials; organization names only for dial-by-name; no contact groups or shared CID source | ◐ | P2 |
| WebRTC browser phone | no | ✘ | P2 |
| Sangoma Talk / Phone Desktop softphones ($19/user/yr), push notifications, video, chat, SMS | no own softphone; a guide for registering third-party SIP apps by hand; no softphone provisioning | ◐ | P2: document and provision third-party SIP softphones first; an own client later |
| Presence (states, auto DND/follow-me) | six states, DND or forward rules, `*37`, presence keys, calendar; no follow-me rule | ◐ | P2 |
| Chat / XMPP | no | — out of scope | |
| SMS/MMS (SIPStation DIDs) | no | ✘ | P3 (module per carrier API) |
| Sangoma Meet video | no | — out of scope | |
| CRM Link ($275): call logging, screen pop, click-to-call for Salesforce, Sugar, Zoho, ConnectWise; Zapier | REST API, signed webhooks, integration tokens, automation rules; no CRM connectors | ◐ | P3 (Zapier/Make recipe on webhooks first) |
| Phone Apps ($499): visual voicemail, parking, queue login, DND, follow-me, time conditions on the phone screen | no phone-screen apps; line keys cover park, voicemail, DND, queue log-in and toggles | ✘ | P3 (after the features; Yealink/Poly XML apps) |
| Web Call Me ($50) | no | ✘ | P3 |
| Browser extension (Companion): tel: links, directory, notifications, SSO | yes | ✔ ahead (FreePBX has nothing comparable) | |

### 3.9 Devices and provisioning

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| **EndPoint Manager ($199): 22 brands, several hundred models** | 4 brands in 20 official base files, all experimental: Poly VVX, Edge E, CCX; Yealink T3x–T8x, CP; Grandstream GRP, GXP, HT; Algo. Other brands as local base files; no CyberData, Cisco ATA, Snom, Cisco MPP, Fanvil or Sangoma | ◐ | **P1**: Yealink (T3x/T4x/T5x), Grandstream (GRP/GXP), Poly Edge/CCX, an ATA (Grandstream HT, Cisco ATA 19x), Algo and CyberData paging endpoints; P2: Snom, Cisco MPP, Fanvil, Sangoma |
| Template editor with raw parameter override (basefile edit) | base file editor: customize, import/export, facts and variables, parent updates; Base File Edit per model | ✔ ahead | |
| Button types: line, BLF, speed dial, park, transfer, voicemail, intercom, DND, record, XML app | line, BLF, speed dial, page, user's choice, park, voicemail, transfer, intercom, DND, toggle, presence; no record or XML app key | ◐ | **P1** (park, voicemail, transfer, intercom, DND once those exist) |
| Expansion modules (sidecars) | no; the VVX 450 base file marks them as later | ✘ | P2 |
| Background image, ring tones, screensaver | screen saver and backlight variables on Poly VVX only; no background image or ring tones | ◐ | P3 |
| Firmware slots and Sangoma's firmware list | upload and assign | ◐ | P3 |
| Zero-touch: PnP, option 66, vendor redirect (Sangoma RPS) | DHCP 66/160, Poly and Yealink HTTP bootstrap, per-brand help and MAC CSV for Yealink RPS, Poly ZTP, Grandstream GDMS; registered by hand, not by API | ◐ | P2: Yealink RPS and Poly ZTP registration, Grandstream GDMS |
| Network scan for unprovisioned phones | "phones seen but not registered" list and the Requests page; no active scan | ◐ | P3 |
| Extension mapping, multi-account phones, DECT bases | devices with several lines | ✔ | |
| Phone directory served to phones (LDAP/XML) | organization's extensions and ring groups as Yealink, Poly, Grandstream XML and CSV; served with the phone's credential | ✔ | P2 |
| Hot desking (EndPoint Login app) | no | ✘ | P2 |
| UCP for EPM (users edit their own keys) | My Phone Phone keys: open slots the template leaves to the user, with locked keys | ✔ | P3 |
| VPN pairing for remote phones (Sysadmin Pro OpenVPN) | no | ✘ | P3 |
| HTTPS provisioning with credentials | yes, plus per-device credentials and a CA bootstrap | ✔ ahead | |
| TFTP/FTP provisioning | no | — insecure; HTTPS only by design | |
| Reboot and resync over SIP NOTIFY | check-sync NOTIFY from the phone's page and Update Phones; Poly and Yealink named in the code | ✔ | |
| Hardware verification | every official base file is still `status = "experimental"`; a checklist exists (PROVISIONING_HARDWARE_CHECKS.md) | ✘ | **P1** |

### 3.10 Fax

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| Inbound fax to email (res_fax, T.38, SpanDSP), fax detection, system fax number | fax inboxes emailed to recipients, a destination for routes, T.38 per trunk; no detection on a voice route | ◐ | P2 |
| Fax Pro ($150): outbound fax from the portal, cover pages, storage, folders, retries, per-user settings, T.38 gateway on routes | My Phone sends a PDF with cover sheet, retries, status, PDF download, per class of service; no folders or per-user settings; T.38 by trunk and extension, no gateway | ◐ | P3 (module) |
| Fax through an ATA (G.711 pass-through, T.38 to the ATA) | official Grandstream ATA base files with fax mode, extension **Fax machine (T.38)** switch, and a guide | ✔ | P2 (document and test; the pragmatic answer for most sites) |

### 3.11 System administration

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| Installer (Debian 12 script or ISO) | Ubuntu 24.04/26.04 installer with preflight, verify, upgrade, uninstall | ✔ ahead | |
| Installable ISO | no | ✘ | P3 |
| Module Admin, Edge track, rollback | signed modules, catalogue, channels, rollback | ✔ | |
| Automatic updates with schedule | signed releases, maintenance windows, approval, idle wait | ✔ ahead | |
| OS package updates from the GUI | check, install security, all except Asterisk or everything, from the Updates page or in a maintenance window | ✔ | P2 |
| Backup & Restore: per-module selection, schedule, retention | full backups, verified by test restore, encrypted, pruned, download and restore from the web, restore to a new server; no per-module selection | ✔ ahead on verification | |
| **Filestore destinations: FTP/SFTP, SSH, S3, Dropbox, email** | folder (NAS), SFTP, S3-compatible and Google Drive; no FTP, Dropbox or email | ◐ | **P1**: SFTP and S3 (design question 1) |
| Warm spare | HA (active/passive) covers it | ✔ | |
| Advanced Recovery ($400/server/yr): warm spare with automatic switchover | HA with operator-run switchover; no automatic failover, no witness | ◐ | P2 (automatic failover after stage 2) |
| Firewall: zones, responsive firewall, intrusion detection, trunk auto-allow | nftables table, per-service allow lists, timed bans from engine/NGINX/provisioning events, permanent allow list, feeds, self-block protection | ✔ ahead | |
| Firewall: custom rules files | no | ✘ | P3 |
| Certificate Manager: **Let's Encrypt** | Let's Encrypt or another ACME authority by DNS challenge, renewal, HA takeover, optional for SIP TLS | ✔ | **P1** |
| Certificate Manager: upload, CSR, per-use assignment | ACME or the Veyra CA; no upload or CSR page; by hand otherwise | ◐ | P2 |
| Sysadmin: network settings (static/DHCP, VLAN), hostname, DNS, time zone in the GUI | time zone per organization and site; the rest at OS level | ◐ | P2 |
| Sysadmin Pro ($39): email setup | SMTP with test button | ✔ | |
| Sysadmin Pro: DDNS, DHCP server, OpenVPN server, support VPN, UPS, packet capture, port management, power | packet capture in System → Diagnostics; no DDNS, DHCP server, OpenVPN, support VPN, UPS, port management or power control | ◐ | P3 (packet capture and UPS first) |
| Intrusion detection (fail2ban) | built in | ✔ | |
| Storage thresholds and alerts | disk_space alert | ✔ | |
| User Management: users, groups, permissions | users, six system roles, custom roles, scoped by organization and site | ✔ | |
| Directories: Active Directory / OpenLDAP sync | no | ✘ | P2 |
| Login with Google/Microsoft (OIDC) | yes, with silent sign-in in managed Chrome | ✔ ahead (FreePBX has none; SAML is paid) | |
| SAML | no | ✘ | P3 |
| MFA: TOTP, email OTP, call-to-extension, trusted device 30 days (free since 2025) | TOTP, recovery codes, passkeys, trusted browser, policy per role; no email OTP or call-to-extension | ◐ | P2 (trusted device, passkeys) |
| Password policy: expiry, complexity | minimum 12 characters, lockout | ◐ | P3 |
| Welcome email to new users | no | ✘ | P3 |
| **Bulk Handler** (CSV import/export of extensions, DIDs, users, contacts) | extensions, users, ring groups, queues, IVR menus, time conditions, inbound routes, shared inboxes, phones; personal contacts on My Phone | ✔ | **P1** |
| **Import from FreePBX** (backup tarball or CSV: extensions, DIDs, voicemail, ring groups, queues, IVRs, time conditions) | From FreePBX: SQL dump or FreePBX 14 backup, `voicemail.conf`, queue agents and sound archive become checked imports: extensions, DIDs, voicemail, ring groups, queues, IVRs, time conditions | ◐ (not yet tried on a real FreePBX dump, #42) | **P1** for adoption |
| API: GraphQL + REST with OAuth2 app flows | REST, WebSocket events, integration tokens with scopes, signed webhooks | ✔ (no GraphQL by design) | |
| AMI / ARI user management for third-party tools (FOP2, wallboards, dialers) | ARI internal only | ✘ | P3 (scoped external ARI access) |
| Config Edit (raw Asterisk files) | no | — generated configuration by design; see custom dialplan include in §3.5 | |
| Asterisk SIP settings: NAT, RTP range, codecs, transports | yes | ✔ | |
| Advanced Settings (hundreds of toggles) | opinionated defaults | — by design; specific toggles are added as needed | |
| GUI translations | English only, no i18n framework | ✘ | P2 |
| Multi-tenancy, central console, audit log, retention, key rotation | yes | ✔ ahead (none in FreePBX) | |

### 3.12 Vertical and campaign modules

| FreePBX capability | Veyra 0.27.67 | Gap | Priority |
|---|---|---|---|
| Sangoma Property Management (hotel PMS, free to 10 rooms) | no | — not a Veyra market | |
| Appointment Reminder ($795) | no | ✘ | P3 (module) |
| **Broadcast / XactDialer ($795)**: voice broadcast campaigns, CSV lists, AMD, remote toggle (school closings) | no campaigns; automation rules can send a page or email | ✘ | P2 (module; the school-closing case is Veyra's audience) |
| Web Call Me ($50) | no | ✘ | P3 |
| Outbound Call Limit ($195) | no | ✘ | P3 |
| Contact Image (door phone still image) | no | — Sangoma-phone specific | |
| Scribe (transcription, summaries, sentiment, TTS) | no | ✘ | P2 (module, see §3.6) |
| Sangoma Meet | no | — out of scope | |
| SMS | no | ✘ | P3 |
| High Availability (legacy DRBD module, EOL) | built in | ✔ | |

## 4. Recommendations

*Historical: written for 0.23.0, and Milestones 18 to 22 have since acted on
it; section 3 shows what is built.*

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

**Decision (owner, 2026-10-16):** all four pieces run before the public
release, split into smaller milestones so nothing is bitten off at once:
Milestone 18 (diagnostics and the extension-centred half of item 1, with
the owner's requests for registration addresses and packet capture),
19 (the call-flow half of item 1), 20 (item 2), 21 (item 3), 22 (item 4),
then Milestone 23, the public release, after intensive testing. The
roadmap carries the rows; the GitHub milestones match.

## 5. Tracking

Every P1 row above has its own GitHub issue labelled `gap:freepbx` and
`P1`, grouped under four tracking issues that mirror section 4 and
assigned to the matching candidate milestone. P2 and P3 rows are listed in
the tracking issues (and in "Tracking: post-1.0 modules and the remaining
P2/P3 rows") until they are scheduled, when each gets its own issue. When
a row is closed, this document is updated in the same pull request, so the
roadmap, the issues and this document agree.

## 6. Sources

FreePBX and Sangoma material was read on 2026-10-16 from the Sangoma
documentation wiki (sangomakb.atlassian.net, spaces PG, FP, SS1, SAF,
PP), the FreePBX GitHub organizations, the FreePBX community forum and
reseller price lists; the two catalogues under `docs/research/` cite the
page for every section and note what could not be confirmed. Prices are
reseller sale prices in USD and will drift. Veyra facts are from the
repository at 0.27.67: `backend/veyra`, `frontend/src`,
`provisioning/templates`, `modules`, `CHANGELOG.md` and `docs/`.
