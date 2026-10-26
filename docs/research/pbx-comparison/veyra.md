# Veyra feature inventory (current state)

Source: repository `manderson20/veyra` at HEAD f5b12b4, version **0.27.18 (2026-10-20)**. Self-hosted (Ubuntu 24.04/26.04 installer), AGPL-3.0-or-later, Asterisk 22 engine with generated + verified config, FastAPI/PostgreSQL backend, Next.js admin/user UI, Chrome/Edge "Companion" extension. Pre-1.0: Milestones 0–21 released; M22 (adoption/ops) and M23 (public release 1.0) not started. Repo is private during development; README is stale (still says "Milestone 1"), CHANGELOG/ROADMAP/milestone reports are authoritative.

> Kept as researched at 0.27.18. For what changed in 0.27.19 to 0.27.37 (bulk import and export, FreePBX importer, passkeys, live conference control, calendar presence, automation rules, the web Record button, voicemail retention) see `CHANGELOG.md` and the "since 0.27.x" notes in [COMPARISON.md](COMPARISON.md).

Important caveats that apply across categories:
- **No official phone template is hardware-verified.** Every official template (Poly VVX/Edge E/CCX, Yealink, Algo) is `status = "experimental"`; the results table in docs/PROVISIONING_HARDWARE_CHECKS.md is empty (issue #34 open).
- Many M18/M19 phone-side behaviours were verified only in the engine config / API on dev1 with software phones, not on real handsets or a real carrier (M18 §3–4, M19 §3–4 "Not verified"). Emergency calling "not certified by Veyra".
- docs/FREEPBX_GAP_ANALYSIS.md is frozen at 0.23.0 (except two rows updated: trunk registration tuning 0.27.8 and holidays 0.27.1); it overstates gaps closed by M18–M21 and 0.27.x.

Status legend: Has / Partial / Missing / Not planned. Evidence = file path or changelog version (CL = CHANGELOG.md).

---

## Feature codes (complete list, from backend/veyra/telephony/features.py)

Adjustable/disable-able codes (Telephony → Feature Codes; FreePBX-style defaults; generator refuses collisions; allowable per class of service):

| Code | Function | Since |
|---|---|---|
| `*78` / `*79` / `*76` | DND on / off / toggle (`*76<ext>` BLF hint) | 0.24.0 |
| `*72[num]` / `*73` | Call forward always on / off (`*72<ext>` hint) | 0.24.0 |
| `*90[num]` / `*91` | Forward on busy on / off | 0.24.0 |
| `*52[num]` / `*53` | Forward on no answer on / off | 0.24.0 |
| `*21` | Find me / follow me toggle (`*21<ext>` hint) | 0.24.0 |
| `*80<ext>` | Intercom (auto-answer headers) | 0.24.0 |
| `*<ext>` | Direct to voicemail (greeting played since 0.27.3) | 0.24.0 |
| `*28<index>` | Call flow (day/night) toggle, optional PIN, BLF | 0.25.0 |
| `*27<index>` | Time-condition override toggle, optional PIN, BLF | 0.25.0 |
| `*30` / `*31` / `*32` | Block a caller / unblock / block last outside caller | 0.25.0 |
| `*45` / `*45<queue>` | Queue agent log in/out (all or one queue); BLF `*45*<ext>` | 0.25.0 |
| `*46` / `*46<queue>` | Queue pause/unpause; BLF `*46*<ext>` | 0.25.0 |
| `*47<queue>` | Callers waiting count | 0.25.0 |
| `*1` (in call) | On-demand recording start/stop | 0.25.0 (working since 0.25.5) |
| `*2` (in call) | Attended transfer | 0.25.0 (working since 0.25.5) |
| `##` (in call) | Blind transfer | 0.25.0 (working since 0.25.5) |
| `*36<ext>` | Colleague presence BLF / call | 0.27.3 |

Fixed codes: `*43` echo test, `*60` speaking clock, `*8` group pickup, `**<ext>` directed pickup, `*95` record a prompt from phone, `*97` own voicemail, `*98` any voicemail box. Emergency `911`/`933` reserved, dial without prefix.
Conference in-room keys: `*1` mute, admin `*2` lock, `*3` drop last, `*8` mute all (0.25.0).
NOT present (verified by grep of generator/features): `*70/*71` call waiting, `*69` call return/trace, `*65` say extension, `*0`/`*75` speed-dial codes, last-number redial code, `555`/ChanSpy, `*86` park pro, hot-desk login codes, wake-up-call code, DISA, `*67`-style per-call CLI block code (not a Veyra feature code).

## Destination types (backend/veyra/api/v1/routing.py `DestinationType`, telephony/snapshot.py)

extension, voicemail (of an extension), voicemail_box (shared inbox), ivr, ring_group, queue, announcement, conference, call_flow, fax (fax-to-email inbox), directory (dial-by-name), plus hangup (IVR/failovers; not for inbound routes). Used on inbound routes (normal + after-hours branch), IVR keys/fallbacks, ring-group and queue failovers, announcements, call flows, parking-lot timeout, block-list policy. Not destinations: paging zone/page, parking lot, misc/custom destination, callback, DISA, language, set-CID, TTS.

---

## A. Per-user calling features

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Do Not Disturb | Has | Extension page switch, My Phone, `*78/*79/*76`, BLF `*76<ext>`, live via AstDB (no deploy); callers get busy or busy greeting; presence state can auto-set DND | Presence driven by calendar/Teams | 0.24.0; CALL_FEATURES §3.2 |
| Call forwarding all / busy / no-answer | Has | Always, busy, no-answer + per-extension ring time; page, My Phone, codes; outside targets via org outbound routes with extension outbound CID; max 3 chained; class of service can forbid outside forwards | Separate "unreachable/not registered" forward (only voicemail/no-answer); remote (`*93`-style for another ext) variants | 0.24.0; CALL_FEATURES §3.3 |
| Forward when unreachable | Partial | Unregistered phone falls to no-answer handling / voicemail | No distinct CF-not-reachable target | gap §3.1 "not reachable" row |
| Selective call forwarding / acceptance / rejection (by caller) | Missing | Org-wide caller block list only | Per-user caller-based rules | — |
| Simultaneous ring / sequential ring (find me / follow me) | Has | Up to 10 legs (extensions or external), ringall or sequential, desk phone first with initial ring, press-1 confirm for outside legs, CID mode (caller/extension), no-answer destination, `*21` | Calendar-linked follow-me; strategies beyond ringall/sequential | 0.24.0; api/v1/extensions.py FollowMeIn |
| Remote office / single number reach | Partial | Follow-me to a mobile; forwards; click-to-dial rings desk phone | No "use mobile as my phone" outbound with office CID, no FMC client | — |
| Anonymous call rejection | Has (org-level) | Block list "withheld number" rule, refused → not in service or destination | Per-user setting | 0.25.0 Blocked Callers |
| Priority / distinctive ring (Alert-Info) | Missing | Only intercom auto-answer Alert-Info | Alert-Info on routes/groups | gap §3.3 |
| Call waiting toggle | Missing | Ring groups can skip busy members; no per-extension `*70/*71` | Per-extension toggle | grep generator: none |
| Per-call CLI blocking | Missing | — | No feature code / privacy option | — |
| Call return `*69` / call trace | Missing | `*32` blocks last caller (stores last outside caller) | `*69`, trace | features.py |
| Last-number redial | Missing (phone-side only) | — | — | — |
| Speed dial | Partial | Personal contacts with speed-dial slots 1–99; user-set phone keys (speed dial from contact); Companion favourites | No `*0`/`*75` speed-dial dial codes, no system speed dials | 0.26.0 (#60, #75) |
| 3-way / ad hoc conference | Partial | Phone-native; conference rooms (meet-me) | No server-side ad hoc conference code | — |
| Hold / transfer | Has | SIP REFER from phones; `*2` attended, `##` blind in-call codes; transfer key type; parking | Transfer key ignored by Poly (softkey kept) | 0.25.0/0.25.5; 0.27.0 |
| Call screening (say name) | Missing | — | P3 | gap §3.1 |
| CLIP / CNAM display | Partial | Internal caller ID; contacts name the other party in portal/voicemail; route CID name prefix | No CNAM lookup / CID Superfecta / spam scoring | 0.26.0; gap §3.3 |
| Privacy manager | Missing | — | P3 | gap §3.3 |
| Outbound caller ID per user | Has | Number + name per extension, validated against org DIDs/allow list; precedence emergency → forced route → extension → route → trunk | Built-in admin roles bypass DID check (owner decision pending) | 0.24.0 (#17) |
| Intercom / auto-answer | Has | `*80<ext>`, allow/deny per extension + org default, class of service; Poly/Yealink templates auto-answer on speaker (vars `intercom_auto_answer`, `intercom_mic_muted`) | Not hardware-verified | 0.24.0; 0.27.4 (#129) |
| Direct transfer to voicemail | Has | `*<ext>` plays unavailable greeting | New box needs a deployment | 0.24.0; 0.27.3 fix |
| Ring time per extension | Has | ring_seconds on extension state | — | 0.24.0 |
| Multiple phones per extension | Has | 1–16 registrations, `max_contacts` | — | 0.24.2 (#82) |
| Language per extension | Missing | Installation-wide `default_language` only; English prompts only | Per-ext/route language, sound packs (Spanish) | gap §3.1/§3.5 |
| Hot desking | Missing | — | P2 (#61) | M21 report §4 |
| Outbound concurrency limit per extension | Has (via CoS) | Class of service `max_outbound_calls` (1–500) | — | 0.24.0 (#30) |

## B. Business group features

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Ring (hunt) groups | Partial | ringall / sequential; ring time; CID prefix; skip busy; music or ring; failover destination; up to 10 external numbers with press-1 confirm; BLF hint | Hunt, memory hunt, first available, random, `-prim`; alert-info, remote announce, ignore-CF | api/v1/ring_groups.py; 0.10.0; 0.24.0 |
| Auto attendant / IVR | Partial | Prompt, keys 0–9 * #, direct extension dial, timeout/retry limits, separate fallbacks, invalid prompt, nesting, `problems` check; all destination types | Multi-digit/hidden entries, return-to-parent, speech/TTS | 0.9.0; gap §3.5 |
| Announcements | Has | Recording then destination; skip with any key, repeat key; chaining with loop guard | Early media | 0.25.0 (#21) |
| Call park | Has | Lots with park extension, slot range with BLF hints (`parkinghints=yes`), timeout ring-back then destination, courtesy tone; Park key type (lot or watched slot) | Park Pro (private lots, `*86`), park & announce | 0.25.0 (#19); 0.27.0 |
| Call pickup | Has | Pickup groups `*8`; directed `**<ext>` (org-wide or restricted to same pickup group, 0.27.11); BLF pickup | Choose among several ringing calls | 0.10.0; 0.27.11 |
| Intercom | Has | see A | — | — |
| Paging | Has | Paging zones (multicast address/port + Poly group 1–24, 25 emergency), dialable zone numbers, policy who may page (everyone/members/administrators), max length; Pages = zones + live or recorded audio, pre-tone, repeats, priority normal/priority/emergency; `veyra-pager` sends speaker multicast and Poly group page in sync; send from UI/API (`POST /pages/{id}/send`, door triggers via integration token); page log; phone-dialled pages logged + `page.sent` webhook (0.27.14) | Duplex paging, busy skip/force/whisper, valet paging, live page from browser; "not a life-safety system" | 0.13.0; 0.27.14; PAGING_RECORDINGS.md |
| Bells / scheduled paging | Has | Calendars from iCal (Google secret URL or any feed), bell schedules ring a recorded page at event start/end, 5-s tick, ring now, history; built-in bell/chime/alert sounds (0.27.3) | Time conditions not calendar-driven | 0.13.0; 0.27.3 |
| BLF / busy lamp | Has | Hints for extensions, groups, DND, CF, follow-me, call flows, TC override, parking slots, conference rooms, queue agent/pause, presence | Not hardware-verified on new key types | 0.27.0 |
| Shared lines / SCA / bridged line | Missing | Multiple phones on one extension only | SCA/BLA | — |
| Executive–assistant (boss/admin) | Missing | — | — | — |
| Barge / whisper / silent monitor | Missing | Active Calls page with hang-up (0.27.1) only | ChanSpy-style supervisor tools (P2) | grep: none |
| Night service / call-flow toggles | Has | Call Flows: normal/override destination, `*28<n>` with PIN and BLF, UI/API switch, live | — | 0.25.0 (#25) |
| Schedules / holidays | Has | Time conditions with time zone, weekly ranges, yearly dates/ranges, one-off dates/ranges, rules (4th Thursday), override `*27<n>` temporary/permanent | Reusable time groups; calendar-linked conditions | 0.27.1 (#113); 0.25.0 (#26) |
| Music on hold | Has | Hold music sets (ordered/shuffled) per org, queue, ring group; internet radio stream source with recording fallback; 3 built-in Veyra pieces | MOH per inbound route; MOH on outbound | 0.13.0; 0.27.11–13 |
| Dial-by-name directory | Has | `Directory()` first/last name over voicemail boxes + custom names (e.g., "Front office") + operator 0 | — | 0.25.0 (#22); 0.27.10 (#135) |
| Operator / attendant console | Missing | Colleagues widget with presence/on-call + click-to-dial; Active Calls | No switchboard/attendant console | — |
| Extension dialing across sites | Has | One numbering plan per org across sites; multi-org namespaces | Inter-installation dialing | MULTI_TENANCY.md |
| Conference (meet-me) | Has | see E | — | — |
| Caller blacklist | Has | Org-wide, anonymous rule, destination, hit counts, CSV import/export, `*30/*31/*32`; refused calls in call history as "Blocked caller" (0.27.9) | Allow-list mode; `*32` only for direct outside calls | 0.25.0 (#27); 0.27.9 |

## C. Voicemail and messaging

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Voicemail boxes | Has | Per extension, PIN encrypted at rest, user-changeable; `*97`/`*98`; MWI; operator extension on 0, `*` opens box; greeting keys 1/2 (follow-me numbers or another org number) per box or user | Per-mailbox advanced options (review, maxmsg, tz) global only | 0.9.0; 0.24.0; 0.27.3 (#131) |
| Shared voicemail inboxes | Has | Box without phone, own number, member lamps | — | 0.13.0 |
| Visual voicemail / web inbox | Has | My Phone + admin Voicemail page: folders (New/Old/Work/Family/Friends/Urgent), play, download, move, forward, delete; MWI follows (`veyra-vmstore` helper); **Call me to play** (0.27.18); audited | Byte-range streaming; voicemail admin stats | 0.26.0 (#31); 0.27.18 (#136) |
| Greetings management | Has | Unavailable/busy/name/temporary: play, upload, record in browser (≤60 s), remove | — | 0.26.0 (#32) |
| Voicemail to email | Has | Attach recording, delete after email (now only after SMTP accepts, 0.27.17); queued with retries; Email button per message, optional delete | Pager short email, templates | 0.9.0; 0.27.17 (#148) |
| Missed-call email | Has | Account → "Email me about missed calls" | — | 0.27.5 (#136) |
| Voicemail transcription | Missing | — | P2 module (on-prem model) | grep: none |
| Voicemail reports / pruning by age | Missing | Spool size shown in retention inventory | Pruning not done by Veyra | PRODUCTION_HARDENING §14 |
| Fax to email (inbound) | Has | "Fax inboxes" as destination for DIDs/routes/menus/groups/queues; ReceiveFAX → PDF emailed to recipients; listed on Fax page | `faxdetect` on voice DIDs | 0.26.3 (#77) |
| Send fax (web to fax) | Has | My Phone Fax widget: PDF ≤20 MB/50 pages, optional cover sheet, state tracking, cancel/retry, 3 attempts, email result; org fax header/station ID; T.38 per trunk; CoS "May send faxes"; 90-day retention | Email-to-fax; fax trunk choice per org; not verified with a carrier | 0.26.3 |
| SMS / MMS | Missing | — | P3 module per carrier API | gap §3.8 |
| Chat / IM / team messaging | Not planned | — | "out of scope" | gap §3.8 |

## D. Clients and mobility

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Desktop softphone | Missing | Third-party SIP softphones can register (up to 16 contacts) | Own softphone (P2) | gap §3.8 |
| Mobile app | Missing | My Phone is responsive (widgets stack) | Native app, push | — |
| Web client / WebRTC phone | Missing | — | WebRTC browser phone P2 | USER_PORTAL §14 |
| Browser extension (Companion) | Has | Chrome/Edge MV3: sign in with password+MFA or OIDC (silent on managed Chromebooks), click-to-dial (popup, context menu, tel: links), directory search incl. ring groups/queues, incoming/missed call notifications with Call back, favourites from My Phone, emergency pop-up for site responders (0.27.5), force-install via Google Admin policy (signed .crx, update manifest) | Firefox/Safari, store listing, call control (answer/hang up), screen pops into other apps, BLF | COMPANION.md; 0.8.0; 0.19.0; 0.27.2; 0.27.5 |
| Click-to-dial | Has | Web (extension page, contacts, recent calls, colleagues), Companion, `POST /calls/originate` | — | 0.6.0 |
| Presence | Has | 6 states + message, auto DND/forward rules, Colleagues widget/directory shows presence, registered, on-call; presence BLF `*36<ext>` | Phone-side presence menu, calendar integration | 0.26.0; 0.27.3 (#132) |
| FMC / single number reach | Partial | Follow-me/forward to mobile | No mobile client/handoff | — |
| Call pull/move between devices | Missing | — | — | — |
| Hot desking | Missing | — | P2 | M21 §4 |
| User portal | Has | see J | — | — |

## E. Conferencing and collaboration

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Audio conference bridge / meet-me | Has | ConfBridge rooms: number, participant + admin PINs (encrypted), limit, join/leave announcements, MOH when alone, wait for admin, recording (listed on Call Recording page since 0.27.2), in-room menu, BLF | Personal rooms/portal control (Conference Pro), conference IVR; PINs in clear in generated dialplan | 0.25.0 (#20); 0.27.2 (#133) |
| Ad hoc conferencing | Partial | Phone-native 3-way only | Server-side ad hoc | — |
| Video meetings / screen share | Not planned | — | "out of scope" | gap §3.8 |

## F. Contact center

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| ACD queues | Has | Strategies ringall, rrmemory, leastrecent, fewestcalls, random, linear; penalties, retry, wrap-up, max wait/callers, join-empty, join/periodic announcements, position announcements, MOH or ring, failover per exit reason | rrordered/wrandom; weight/priority; hold-time announcement; auto-pause; member delay | api/v1/queues.py; 0.10.0 |
| Agent states (dynamic login/pause) | Partial | Dynamic agents `*45`/`*46`, per-queue toggles, BLF, queue page Agents card, API | Pause reason codes; agent state not in reports | 0.25.0 (#28); 0.27.6 (#130) |
| Queue break-out (IVR in queue) | Has | Queue names an IVR menu (press 1 for voicemail) | — | 0.25.0 (#29) |
| Queue callback | Missing | — | P2 | gap §3.5 |
| Wallboard / live queue view | Missing | `*47` waiting count; static reports | Live view/wallboard (P2/module) | REPORTING §11 |
| Supervisor monitor/whisper/barge | Missing | — | P2 | — |
| Queue reporting | Partial | Offered/answered/abandoned/wait/agents from queue log; report builder by queue, hour, agent, service level; break-out returns counted once (0.27.14) | Agent availability, missed-call detail | 0.15.0; 0.16.0; 0.27.14 |
| Skills routing, omnichannel, WFM | Missing | Penalties only | — | — |

## G. Dialing control and carrier/regulatory

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Class of service / call restriction | Has | Per org classes: allowed outbound routes, allowed feature codes, outside forwards, external follow-me, intercom, fax, max simultaneous outside calls; emergency always allowed; refusals logged as "Not allowed" (0.27.9) | In-call codes not CoS-guarded; time-group restrictions on routes | 0.24.0 (#30); 0.27.9 |
| Account codes | Missing | — | P3 | gap §3.1 |
| Authorization codes / PIN sets | Missing | — | P2 | gap §3.4 |
| E911 / Kari's Law | Has | Emergency routes evaluated first, 911/933 direct, per-site routes chaining to global, ELIN per site, emergency CID per extension, on-site notification (email, recorded page, responder phones hear extension, `emergency.call` webhook, Companion pop-up), PSAP callback window (rings caller ext, else responder), carrier test-call records, readiness page per site, verify.sh readiness warning | Not certified; NG911/PIDF-LO location conveyance | EMERGENCY_CALLING.md; 0.23.0; 0.27.1; 0.27.5 |
| RAY BAUM'S dispatchable location | Partial | Site civic address, buildings with own address, floor/room per extension/device (Location card 0.27.1) | Conveyance relies on ELIN + carrier registration; no dynamic location for nomadic users | 0.27.1 (#126) |
| STIR/SHAKEN | Missing | Carrier-side only; nothing in repo | — | grep: none |
| Robocall / spam blocking | Partial | Manual block list + anonymous rule | CNAM/spam scoring (CID Superfecta P2) | gap §3.3 |
| CNAM lookup | Missing | — | P2 | gap §3.3 |
| Number porting | Not planned | Carrier matter | — | — |
| Toll fraud protection | Has | nftables firewall with automatic bans from Asterisk security events, permanent allow list, feeds/CrowdSec; CoS outside-call caps; trunk max channels; generated 24-char SIP secrets | Per-extension rate limits beyond CoS cap | 0.14.0; 0.24.0 |
| Caller ID per user/group | Has | Per-extension outbound CID; per-route (forceable) and per-trunk CID; ring-group CID name prefix; inbound route name prefix | CID-based inbound routing; per-trunk CID manipulation options | 0.24.0; gap §3.2–3.3 |
| Trunks | Has | PJSIP registration or IP auth, UDP/TCP/TLS, codecs, outbound proxy, from user/domain, PAI/RPID, DTMF mode, qualify, max channels, default CID, T.38 flag, registration state shown, retry tuning (interval, forbidden retry, max retries, expiry), keep retrying after outage (0.27.8), trunk_down alert, peak concurrent calls report | Dial manipulation per trunk; carrier presets; IAX2/DAHDI not planned | 0.7.0; 0.24.0 (#45); 0.27.8 (#142) |
| Outbound routing | Has | Ordered routes, prefix/match/prepend patterns, trunk failover, route CID override/force, org-owned or shared routes, loop detection | Time-based/LCR selection, pattern wizards, route CSV | 0.7.0 |
| Inbound routing | Partial | Exact DIDs with NANP 1/+1 aliasing, per-trunk restriction, catch-all, time condition with after-hours branch, CID name prefix | DID patterns, CID-based routing, alert-info, language, fax detection | 0.7.0; api/v1/routing.py |
| Secure SIP (TLS + SRTP) | Partial | TLS transport installation-wide; HTTPS provisioning with Veyra CA | SRTP (`media_encryption`) not built — "17b" (gap marked P1) | PRODUCTION_HARDENING §3.3/§14; grep none |

## H. Recording, analytics and compliance

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Call recording | Has | Policies per org (inbound/outbound/internal; all or chosen phones/groups/queues/DIDs; announcement; retention); on-demand `*1`; conference recordings; Ogg Opus; encrypted on disk per-recording key (0.27.4); hold against deletion; audited playback/download; users may play own recordings (org switch) | Archive to remote storage | 0.15.0; 0.25.0; 0.27.4 (#122) |
| CDR / call history | Has | Folded legs, direction, who answered, ring/talk, outcomes incl. Blocked caller/Not allowed, search, CSV, 400-day default, My Phone recent calls | Per-call event log | 0.15.0; 0.27.9 |
| Reports / dashboards | Has | Reports page; report builder (group by period/hour/weekday/ext/DID/trunk/queue/group/direction/outcome/caller; measures incl. answered within N s; business-hours filter; table/bars/line; saved/shared; scheduled CSV email); dashboard graphs (channels, internal vs external, phones online, calls today vs last week); trunk peak concurrency | — | 0.16.0; 0.26.5; 0.27.2 |
| Live monitoring | Partial | Active Calls with hang-up; Registrations (source vs contact address, NAT); Prometheus metrics; alerts (20 rules, email) | Listen/whisper/barge; live queue view | 0.6.0; 0.24.0; 0.27.1 |
| Quality (MOS) | Missing | Packet capture with RTP for troubleshooting | MOS/quality scoring | — |
| Diagnostics | Has | Packet capture (tcpdump via polkit unit; SIP/extension/trunk/address, RTP optional; SIP dialog summary; audited download), log tail with filter, fixed read-only engine queries | Captures per node only | 0.24.0 (#73, #74) |
| Retention | Has | Per data class (audit ≥1 yr, calls, alerts, captures 7 d, faxes 90 d, recordings, etc.), daily job, inventory | Voicemail not pruned | 0.23.0 |
| Audit log | Has | Every change/listen/self-service action; step-up re-auth for sensitive actions (0.27.15) | — | 0.27.15 (#137) |
| AI transcription / summaries / sentiment | Missing | — | Discussed as optional module | REPORTING §11 |

## I. Integrations and APIs

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| REST API | Has | Full REST under `/api/v1` (OpenAPI), `me`-scoped self-service routes, WebSocket call-event stream | GraphQL (by design no) | API.md |
| Integration tokens | Has | Org tokens `vyi_…` with scopes, allowed addresses, expiry, service account in audit | OAuth apps | 0.19.0 |
| Webhooks | Has | Signed HMAC-SHA256: call.ringing/answered/ended, voicemail.message, page.sent, bell.rang, alert.raised/resolved, registration.changed, deployment.finished, emergency.call, module events; retries, log, redeliver, secret rotation | Incoming webhooks in other formats | INTEGRATIONS §3 |
| SSO OIDC | Has | Google Workspace, Microsoft Entra ID, any OIDC (PKCE, nonce), domain restriction, JIT creation, require-SSO; Companion SSO | SAML (P3), group-to-role mapping | 0.19.0 |
| Directory sync AD/LDAP/SCIM | Missing | — | P2 | INTEGRATIONS §10 |
| CRM | Missing | Webhooks/API only | CRM connectors, screen pops | INTEGRATIONS §10 |
| Microsoft Teams / Slack | Missing | Webhook can feed them | Native integration | INTEGRATIONS §10 |
| Google | Partial | Google OIDC sign-in; Google Calendar iCal feeds for bells | Google contacts/Meet | — |
| Zapier/Make | Partial | Generic signed webhooks + API | No published recipes | gap §3.8 |
| Door controller / external triggers | Has | Integration token → `POST /pages/{id}/send` | — | PAGING_RECORDINGS §2.6 |
| External ARI/AMI for third-party tools | Missing | ARI internal only | P3 | gap §3.11 |
| Metrics | Has | Prometheus `/api/v1/metrics` | — | 0.15.0 |

## J. Administration, provisioning and platform

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Self-service user portal (My Phone) | Has | Canvas of widgets on named tabs (drag/resize/add/remove, keyboard, undo, reset). Widgets: My phone (registration, DND, forwards, follow-me), Presence, Voicemail (messages+greetings, call me to play, email), Recent calls (30 d, call back, add to contacts, CSV, own recordings if allowed), Contacts (5 numbers, favourites, speed-dial slots, CSV), Colleagues, Phone keys (user slots; admin-locked keys), Fax, Codes you can dial, Announcement (lockable). Admin default layouts by system/org/building/department/role with locked widgets and push-to-users. Account page: PIN, sessions, tokens, MFA, trusted browsers, greeting keys, missed-call email | Module-contributed widgets; user-group object; touch drag unverified | 0.26.0; frontend/src/portal/widgets.ts; 0.27.x |
| Admin portal | Has | Next.js UI, flyout nav (Overview, My Phone, Directory, Telephony, Provisioning, Modules, System); RBAC 6 system roles (platform admin, org admin, site admin, technician, standard user, read-only) + custom roles scoped by org/site | GUI translations (English only) | frontend/src/lib/nav.ts; permissions.py |
| Multi-tenancy | Has | Per-org engine namespace (contexts, voicemail, queues, MOH, pickup), numbers per org, routes per org or shared, isolation verifier blocks bad revisions, activation after checks | Per-org SMTP/SSO/numbering, billing, quotas, channel limits, RLS | 0.20.0; MULTI_TENANCY §8 |
| Reseller hierarchy / white-label | Missing | Platform admin → organizations only | Reseller tiers, branding per org | — |
| Billing | Not planned | — | "out of scope" | gap §3.7 |
| Central management | Has | Any install can be a central console; instances enroll, signed check-ins every 60 s (outbound only); health, counts, alerts, update state, 30-day graphs; policies (update policy/window, firewall allow-list, alert recipients, notice) accept/refuse locally; commands (check/download/approve updates, refresh catalogs); "Instance update failed" alert | Pushing config (extensions/routes/templates), central CDR/recordings, SSO into instances | 0.21.0; 0.27.6 (#120) |
| HA / geo-redundancy | Partial | Active/passive two nodes: PostgreSQL streaming (async or sync), file sync, service IP with GARP, root HA agent, audited manual switchover and failover, Proxmox fencing, epoch split-brain rules, HA-aware updates | **Automatic failover, witness/quorum**, >2 nodes, routed (non-L2) addresses, call preservation; **stage 2 on two real servers pending** (veyra-dev2) | 0.22.0; HIGH_AVAILABILITY §14; ROADMAP row 16 |
| Phone auto-provisioning | Partial (breadth Has, verification Missing) | HTTPS with per-org enrollment + per-device credentials, Veyra CA bootstrap over HTTP (Poly, Yealink since 0.27.4), DHCP 66/160, redirect-service guidance + MAC CSV export (Yealink RPS, Poly ZTP, Grandstream GDMS, Algo DHCP), device profiles, provisioning variables (installation→org→site→profile, `{{ vars.x }}`, `$name` keys, auto re-provision), template editor/customize/import/export, firmware upload/assign, reboot/resync via SIP NOTIFY, unregistered-phone list, phone directory (Yealink/Poly/Grandstream/CSV) | No hardware verification; see brands below | 0.11.0; 0.27.0; 0.27.4 |
| Supported brands/models | Partial | **Poly VVX 410/411, VVX 450**; **Poly Edge E** E100/E220/E300/E320/E350/E400/E450/E500/E550; **Poly CCX** 350/400/500/505/600/700; **Yealink** T30/T30P/T31/T31G/T31P/T31W/T33G/T34W, T42U/T43U/T44U/T44W/T46U/T48U, T53/T53W/T54W/T57W/T58W/T58W Pro/VP59, T73U/T73W/T74U/T74W/T77U, T85W/T87W/T88, CP925/CP935W/CP965; **Algo** 8180/8186/8188/8189/8190/8196–8199/8507, 8410/8420, 8301/8305/8312/8373, 8028/8028V/8039/8063/8201/8203, 8128/8138, 8401/8402, 8450. ALL `experimental`, none hardware-verified | Grandstream (#36), ATA HT80x/HT81x (#37), CyberData, Poly Edge V, Yealink DECT/Wi-Fi, Snom, Cisco MPP, Fanvil, Sangoma; AND clocks not SIP-provisioned | provisioning/templates/official/*; M21 report |
| Line key types | Has | line, BLF, speed dial, page, user's choice, park, voicemail, transfer (Poly keeps softkey), intercom, DND, toggle (call flow / TC / agent / queue:<slug>), presence | Expansion modules (sidecars), XML apps, background images | api/v1/device_common.py |
| User-set keys with locked admin keys | Has | "User's choice" slots; admin edits user keys (0.27.16) | — | 0.26.0 (#75); 0.27.16 |
| Bulk import/export | Missing | CSV only for contacts, block list, call history, reports, MAC export | Extensions/DIDs/users bulk CSV, FreePBX importer → **M22** | ROADMAP row 22 |
| Backups | Partial | Scheduled, verified by test restore, age-encrypted, pruned, mounted copy directory, restore to new server, alerts | **SFTP/S3 destinations → M22** | 0.23.0 |
| Certificates | Partial | Own Veyra CA with name constraints; custom cert by hand | **Let's Encrypt → M22**; CSR/upload UI | gap §3.11 |
| Security / MFA | Has | TOTP + recovery codes, MFA policy per role, trusted browser N days (0.27.8), step-up re-auth (0.27.15), lockout, rate limits, password reset links/forgot password, CSP by hash, nftables firewall with auto-bans, installation key encryption + rotation, encrypted recordings, signed modules/updates, CodeQL review | Passkeys/WebAuthn (schema stub only), email OTP, password expiry/complexity | 0.5.0; 0.27.8; 0.27.15; mfa.py |
| Updates | Has | Signed release feed (Ed25519), download/verify/approve, maintenance windows, auto-install policy, idle wait, live progress, `veyra updates install` CLI (0.27.18); signed module catalog, upload, rollback; OS packages listed | OS package apply from GUI | 0.18.0; 0.24.2; 0.27.18 |
| Module system | Has | Signed `.vmod`, catalog on GitHub, module API 1.2; modules shipped: AND Clock Messages (`veyra.and-clocks` 0.2.0), example-notes | Modules can't add portal widgets | modules/; 0.27.5 |
| Custom dialplan escape hatch | Missing | Generated config only | Reviewed custom-dialplan include → **M22** | ROADMAP row 22 |
| Installer | Has | Ubuntu 24.04/26.04 preflight/install/verify/upgrade/uninstall | ISO (P3) | INSTALLATION.md |
| Network settings in GUI | Partial | Time zone per org; SIP NAT/RTP/transports | Static IP/VLAN/DNS/hostname at OS level | gap §3.11 |

## K. Vertical / specialty

| Feature | Status | What Veyra has | What is missing | Evidence |
|---|---|---|---|---|
| Education: bells | Has | Calendar-driven bell schedules, built-in school bell/chimes/drill tones | — | 0.13.0; 0.27.3 |
| Mass notification / lockdown | Partial | Emergency-priority pages, all-call key locked on every phone via variables (`$all_call` per building), AND clock text/alert messages module, Algo visual alerters/strobes templates | "Not a life-safety notification system"; no broadcast dial-out campaigns | PAGING_RECORDINGS; 0.27.0 |
| Broadcast / voice campaigns (school closings) | Missing | — | P2 module (XactDialer equivalent) | gap §3.12 |
| Emergency notification on 911 | Has | see G | — | 0.23.0 |
| Door phones / intercoms | Partial | Algo 8028/8028V/8039/8063/8201/8203 templates (experimental); door controller triggers pages via API | CyberData; door-release DTMF control not documented | 0.27.0 |
| Clocks/displays | Has (module) | AND clocks messaging (Clockwise-like); Algo 8401/8402 clocks | AND not SIP-provisioned | 0.13.0; 0.27.5 |
| Hospitality / PMS | Not planned | — | "not a Veyra market" | gap §3.12 |
| Wake-up calls | Missing | — | P3 module | gap §3.5 |
| Healthcare | Missing | (named dial-by-name entries like "Nurse") | — | — |
| Appointment reminder | Missing | — | P3 | gap §3.12 |

---

## Remaining roadmap

- **M22 — Adoption and operations (0.28.0), Not started**: bulk CSV import/export (extensions, DIDs, users), FreePBX importer (backup tarball), Let's Encrypt, SFTP and S3 backup destinations, custom-dialplan include; plus Updates-page cleanup items #84/#85/#88/#89 and buildings/departments page completion carried into it (M20 report §6).
- **M23 — Public release preparation (1.0.0), Not started**: license decision (AGPL chosen in ADR 0013; final), disclosure policy, packaging, after intensive testing of M18–22.
- Other open items: hardware checks of all templates (#34); Grandstream (#36) and ATA (#37) on request; CyberData on request; HA stage 2 on two real servers; secure SIP (SRTP) "17b"; owner decision on admin roles bypassing outbound-CID DID check; passkeys (planned since M4b, not built).

## Open P2 / P3 items from the gap analysis still NOT done (as of 0.27.18)

P1 rows still open: bulk CSV import/export of extensions and DIDs (M22), FreePBX importer (M22), SFTP/S3 backups (M22), Let's Encrypt (M22), SRTP/secure SIP per profile (unscheduled "17b"), hardware verification of templates (#34).

P2 (not done): virtual extension type; call waiting toggle; optional destinations for busy/unreachable; per-direction recording flags per extension; language per extension/route and Spanish sound packs; hot desking (+EndPoint login); trunk CID options and dial manipulation per trunk; caller-ID based inbound routing; Alert-Info/distinctive ring; fax detection on voice DIDs; CNAM lookup and CID Superfecta/spam scoring; CallerID column per outbound pattern; PIN sets; time-group restriction on routes; IVR multi-digit entries and return-to-parent; calendar-driven time conditions; ring group hunt/memory/first-available/random strategies, ring-group confirm/remote announce/alert-info/ignore-CF; queue pause reason codes, auto-pause, member delay, agent announcement, hold-time announcement, external-agent confirm, queue callback/virtual queues, wallboard/live queue view, Q-Xact-level agent reports, supervisor monitor/whisper/barge; Conference Pro (personal rooms); Park Pro; duplex paging and busy handling; live page from browser; DISA; misc destinations/applications; custom dialplan include (M22); feature-code admin is done but Presence State admin-defined states not; voicemail transcription (module); voicemail admin stats; voicemail pruning; call-recording archive to remote storage; live Asterisk info (queues, subscriptions); incoming pop-up with external lookup (partial: contacts); WebRTC browser phone; own softphone; Contact Manager org-wide external contacts (#93 external directory); phone directory external entries; expansion modules; vendor redirect APIs beyond CSV (Yealink RPS/Poly ZTP API registration); Advanced Recovery-style automatic failover (after HA stage 2); OS package updates applied from GUI; certificate upload/CSR UI; network settings in GUI; AD/LDAP directory sync; MFA passkeys (trusted device done 0.27.8); GUI translations; broadcast campaigns module; Scribe-like transcription module.

P3 (not done): custom/other extension; account code/CID alias; queue state detection override; add DID from extension page; Extension Settings report; Print Extensions; custom trunk; continue-if-busy; inbound channel counting; carrier presets; DID patterns; CID priority routes; MOH per route/outbound; signal ringing/pause before answer; privacy manager; route password; intra-company route; congestion destinations/messages; dial pattern wizards; pattern CSV/duplicate route; CID management presets; outbound call limit; outbound CNAM; TTS destination; reusable time groups; queue strategies rrordered/wrandom, queue weight/priorities; valet paging; callback destination; allow-list mode; set-CID destination; dynamic routes; wake-up calls; voicemail blasting; speed-dial codes `*0/*75`; `*65`/`*69`; ChanSpy/`555`/`777`; pager email; per-mailbox options; email templates; VM Notify; voicemail reports; BLF hint on mailbox; call event logging; MES; Phone Apps (XML apps); Web Call Me; UCP-for-EPM is done (user keys); background images/ringtones; firmware lists; network scan; VPN pairing; installable ISO; custom firewall rules; Sysadmin Pro extras (DDNS, DHCP, OpenVPN, UPS); SAML; password expiry/complexity; welcome email; external ARI/AMI; appointment reminder; SMS; CRM connectors.

Closed since 0.23.0 (for reference): DND, CF, follow-me, ring-group external members, intercom, outbound CID per ext, direct-to-VM, VM operator/locater keys, CoS + call cap, trunk registration state and retry tuning, diagnostics page/packet capture, announcements, directory (+custom entries/operator), conferences, parking + BLF, call flows, TC override, blacklist, queue dynamic agents/pause/break-out, in-call `*1/*2/##`, feature-code admin, user portal (inbox, greetings, contacts, presence, keys, layouts), call me to play, missed-call email, fax in/out, Yealink/Edge/CCX/Algo templates, more key types, phone directory, provisioning variables, floating holidays, refused calls in CDR, encrypted recordings, conference recordings listed, trusted browser MFA, hang-up from Active Calls, buildings/departments, hold music streams + built-in music, built-in sounds, directed pickup by group, forgot-password.

## Metaswitch

The only mention of Metaswitch in the repository is docs/ROADMAP.md row 6b: the Veyra Companion browser extension was an "owner request 2026-10-12 (replaces a Metaswitch desktop dialler)". docs/COMPANION.md and MILESTONE_6B_REPORT.md say it "replaces a vendor desktop dialler" (likely Metaswitch MaX UC / CommPortal-style click-to-dial). Companion functions mirror that dialler: click-to-dial with desk phone ringing first, directory lookup, incoming caller-ID pop-up, speed dials/favourites. No Metaswitch import, interop, CommPortal parity or migration doc exists; the migration tooling planned (M22) targets FreePBX only.
