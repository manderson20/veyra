# Veyra vs Metaswitch and Other PBX Platforms: Feature Comparison

Oct 20, 2026 · Mathew Anderson

> Snapshot of the living document at https://claude.ai/code/artifact/c4c1e5fd-d336-4895-9ea6-7b7c95b443d2, exported 2026-10-26. It describes Veyra as of 0.27.18; later releases may have closed some gaps. The owner's decisions on the roadmap table are recorded in the living document.

## Summary

Veyra 0.27.18 already matches or beats Metaswitch on most of what a school, town hall or small business uses every day. The real gaps are the telco-style per-user call rules, hunt algorithms, shared lines, supervisor listen-in, voicemail transcription and Metaswitch's own softphone apps. Against the wider market (3CX, Yeastar, Grandstream, RingCentral, Teams, Zoom, Webex and others), Veyra's biggest gaps are a browser or mobile softphone, a receptionist console, live queue boards, directory sync and the AI features every cloud vendor added in 2025 and 2026.

Where Veyra is ahead of Metaswitch: paging and calendar-driven bells, 911 on-site notification with room-level location, day/night toggles on a phone key, an open REST API with webhooks, single sign-on with MFA, a built-in firewall, encrypted and audited recordings, and no per-seat licence. Metaswitch's business features show their telco roots: they were built for a carrier selling lines, not for a building with speakers and bells.

My top recommendations, in order:

1. Finish Milestone 22 (bulk import, backups off the box) and hardware-verify the phone templates. These block every migration, from Metaswitch or FreePBX alike.
2. Add the small "telco habit" features that Metaswitch users will reach for on day one: `*67`, `*69`, `*70`, forward-when-unreachable, round-robin and longest-idle hunting, and a star-code preset that matches the codes staff already know.
3. Add supervisor listen, whisper and barge (with an audit trail), plus hotline phones and a summer-break voicemail greeting.
4. After 1.0, build a WebRTC phone in My Phone and the Companion, a receptionist console, a live queue board, Google and Microsoft directory sync, and on-premises voicemail transcription.
5. Skip chat, video meetings, omnichannel inboxes, workforce management and telephony cards. Schools and towns already have tools for those.

Every recommendation is yours to accept or reject. The roadmap section near the end has a decision column for that.

## Platforms covered

Twenty-one platforms were researched against one feature list: Metaswitch in depth, ten self-hosted or appliance PBXs, and ten cloud services. FreePBX is left out here because `docs/FREEPBX_GAP_ANALYSIS.md` already covers it row by row.

**Metaswitch today.** Microsoft bought Metaswitch in July 2020, issued an end-of-life notice for the MaX UC apps in May 2024 and laid off most of the staff in June 2024. [Alianza](https://www.alianza.com/whats-new/alianza-completes-acquisition-of-metaswitch-from-microsoft/) completed its purchase of the products on 4 March 2025 and now sells them as "Alianza Core". Alianza says operators [can stay on it for years](https://www.fierce-network.com/cloud/alianzas-metaswitch-assets-arent-going-anywhere), while steering them toward its own cloud tiers. Its core is the CFS switch (calling and Business Group features), the EAS server (voicemail, fax, auto attendant, call centre queues), the CommPortal web portal and the MaX UC (formerly Accession) apps. I could not confirm from a public page that Chariton Valley runs Metaswitch, so the feature list below comes from guides published by other Metaswitch operators (Sparklight, Momentum, FirstLight, FirstComm, Allstream, Grid4 and others). Each operator sets its own star codes, so codes differ from carrier to carrier.

| Platform | Type | How it is sold | Typical customer |
| --- | --- | --- | --- |
| [Metaswitch / Alianza Core](https://www.alianza.com/products/alianza-core/) | Carrier hosted PBX (Class 5 switch) | Licensed to telcos, resold per line under the telco's brand | Rural telcos, cable companies and their business customers |
| [NetSapiens](https://netsapiens.com/snapsolution/) | Carrier hosted PBX | Per platform, no per-seat fees; resold by providers | Small telcos and MSPs (a Metaswitch competitor) |
| [Webex Calling / BroadWorks](https://help.webex.com/article/nsyoaiy) | Cloud and carrier hosted PBX | About $14.50 to $23 per user per month; free hot-desk licence | Enterprises and carriers (also a Metaswitch competitor) |
| [RingCentral RingEX](https://assets.ringcentral.com/us/datasheet/all-about-ringcentral-phone.pdf) | Cloud | About $20 to $45 per user per month, AI receptionist $39 to $49 extra | SMB to enterprise |
| [Microsoft Teams Phone](https://learn.microsoft.com/da-dk/microsoftteams/here-s-what-you-get-with-phone-system) | Cloud | About $10 per user per month plus calling plan; included in A5/E5 | Microsoft 365 organizations, including schools |
| [Zoom Phone](https://www.zoom.com/en/products/voip-phone/features/) | Cloud | $10.50 to $24.50 per user per month | Zoom Meetings customers |
| [8x8](https://www.kcom.com/home/media/oehjnpz5/kc_6432-8x8-x-series-feature-matrix-uk-public-sector-edition.pdf) | Cloud | About $24 to $57 per user per month | Mid-market and enterprise |
| [GoTo Connect](https://review.goto.com/-/media/pdfs/data-sheet/ds-goto-connect.pdf) | Cloud | About $26 to $80 per user per month | SMB, multi-site |
| [Dialpad](https://help.dialpad.com/docs/dialpad-feature-comparison.md) | Cloud, AI-first | $15 to $25 per user per month and up | Sales and support teams |
| [Vonage Business](https://fitsmallbusiness.com/vonage-business-communications-review) | Cloud | About $13 to $40 per user per month, many add-ons | SMB |
| [Nextiva](https://nextiva.com/?amp=1) | Cloud | $15 to $75 per user per month | US SMB, healthcare |
| [3CX v20](https://www.3cx.com/ordering/pricing/features/) | Self-hosted or hosted software | Annual, per simultaneous call: 8 calls $300 to $575 | SMB, hotels |
| [Yeastar P-Series](https://www.yeastar.com/p-series-ip-pbx/) | Appliance, software or cloud | Annual plan, about $899 a year for 100 users (Ultimate) | SMB, multi-branch, hotels |
| [Grandstream UCM6300](https://www.grandstream.com/hubfs/Partner_Marketing_Kit/IPPBX%20Solutions/Sales%20Kit/ucm-sales-kit-q1-2025.pdf) | Appliance | One-time purchase (UCM6304 about $680), free apps | SMB, schools, hotels |
| [VitalPBX](https://vitalpbx.com/pbx-plans-and-pricing-vitalpbx-system/) | Self-hosted, Asterisk-based | Free to 12 users, then $100 to $250 a month flat | SMB, call centres, MSPs |
| [FusionPBX](https://docs.fusionpbx.com/en/latest/features/features.html) | Self-hosted, FreeSWITCH-based | Free, open source | Hosting providers, MSPs |
| [Wazo Platform](https://wazo-platform.org) | Self-hosted, API-first | Free, open source | Developers, carriers |
| [Issabel](https://ccmanual.issabel.com/en/contact-center-description/implemented-features.html) | Self-hosted, Asterisk-based | Free; contact centre add-on per agent | SMB, Latin America |
| [Cisco CUCM 15](https://webex.com/content/dam/www/us/en/documents/pdf/ucm-15-data-sheet.pdf) | On-premises enterprise | Subscription, quote only (education SKU exists) | Large enterprises, universities, K-12 districts |
| [Avaya IP Office](https://www.avaya.com/content/dam/aem-avaya-portal/en_us/documents/fs-ipo-platform-sme8093en.pdf) | Appliance or server | Perpetual or about $15 to $30 per user per month | SMB, schools, municipalities |
| [Mitel MiVoice Business / MX-ONE](https://www.mitel.com/lp/UC-Solutions-Private-Cloud-or-On-Site) | On-premises enterprise | Perpetual or subscription | Government, healthcare, education |

Prices are 2026 list or reseller figures, several from competitor-written roundups, so treat them as ballpark.

## What Veyra has today

Veyra 0.27.18 (repository commit f5b12b4, 2026-10-20) has shipped Milestones 0 to 21, so the everyday call features, call flow features, user portal, fax and provisioning breadth from the FreePBX gap analysis are now in place. Milestone 22 (bulk import, FreePBX importer, Let's Encrypt, SFTP/S3 backups, custom dialplan include) and Milestone 23 (1.0 release) have not started. Note that `docs/FREEPBX_GAP_ANALYSIS.md` was written at 0.23.0 and the README still says Milestone 1, so both understate what exists.

| Area | What is in place | Notable holes |
| --- | --- | --- |
| Per-user calling | DND `*78/*79/*76`; forward always `*72/*73`, busy `*90/*91`, no answer `*52/*53` with ring time; follow-me `*21` (up to 10 legs, press-1 confirm); outbound caller ID per extension validated against owned numbers; intercom `*80<ext>` with auto-answer; direct to voicemail `*<ext>` with operator key | No call waiting toggle, no `*69` call return, no selective (per-caller) forwarding or rejection, no anonymous call rejection, no speed-dial codes, no SRTP |
| Call flow | IVR, ring groups (ring all, sequential), queues (6 strategies, dynamic agents `*45/*46/*47`, break-out menu), parking with lamps, ConfBridge rooms with PINs and recording, announcements, dial-by-name, day/night toggles `*28<n>`, time-condition override `*27<n>`, holidays, caller block list `*30/*31/*32`, pickup `*8` and `**<ext>`, presence `*36<ext>` | No hunt/round-robin ring group modes, no shared lines, no boss/assistant, no barge/whisper/monitor, no queue callback or wallboard |
| Voicemail, fax | Voicemail to email, shared inboxes, web inbox, browser greetings, call-me-to-play, email-and-delete; fax from a PDF on My Phone, inbound fax to email, T.38 per trunk | No transcription, no fax detection on voice numbers, fax untested with a real carrier |
| Users and clients | My Phone portal (widget canvas with admin-locked layouts), Companion browser extension (click-to-dial, directory, caller pop-up, SSO), missed-call email | No softphone, no mobile app, no WebRTC phone, no SMS, no chat |
| Provisioning | HTTPS with Veyra CA, scoped variables, 12 key types, user keys around locked keys, phone directory; Poly VVX/Edge/CCX, all current Yealink, Algo | Every template is experimental and none is hardware-verified; Grandstream, ATAs and CyberData on request |
| Paging, bells, emergency | Zones dialable from phones, multicast plus Poly group pages in step, priority and emergency pages, calendar-driven bells, AND clock module; 911/933 per site with dispatchable location, on-site notification and readiness page | Not a certified life-safety or NG911 system |
| Platform | Multi-tenancy with isolation verifier, central console, active/passive HA (manual switchover), signed updates and modules, nftables firewall, OIDC sign-in, TOTP, audit log, encrypted backups, report builder, REST API, signed webhooks, Prometheus | No automatic failover, no SAML, no AD/LDAP sync, no CRM or Teams link, no reseller tier or billing |

On Metaswitch, the repository mentions it once: the Companion extension was built to replace a Metaswitch desktop dialler (`docs/ROADMAP.md`, Milestone 6b). There is no Metaswitch import or interop tooling.

## Feature comparison chart

Each row explains a feature in a sentence, shows what Metaswitch does, names the other platforms that have it, marks what Veyra has (and what part of the feature it still lacks), and gives my recommendation. Star codes in the Metaswitch column come from the named operators' guides; your carrier may use different ones.

**Veyra marks:** ✔ has it · ◐ has part of it · ✘ missing · — deliberately not planned.

**Recommendations:** **Done** (nothing to add) · **Build next** (small, or blocks adoption; before or right after 1.0) · **After 1.0** (worth building, larger) · **Module** (optional add-on for sites that want it) · **Skip** (not worth it for Veyra's schools, towns and small businesses).

"All 20" in the Others column means every other platform researched has it.

### A. Per-user calling features

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Do not disturb | Stops your phone ringing; callers go to voicemail. | ✔ `*78/*79`; a VIP list can still ring through | All 20 | ✔ `*78/*79/*76`, BLF key, My Phone, presence can set it. Missing: VIP callers who bypass DND | **Build next** (small): "these callers still ring" list |
| Call forwarding: always, busy, no answer | Sends calls elsewhere unconditionally, when busy, or after N rings. | ✔ `*72/*73`, `*90/*91`, `*92/*93` | All 20 | ✔ All three with ring timer, codes, My Phone, outside numbers allowed by class of service | **Done** |
| Forward when unreachable | Sends calls to a cell phone when the desk phone is offline (power, network or internet outage). | ✔ "Forward if unavailable" | Webex, NS, Vital, Fusion | ◐ An offline phone falls through to voicemail; no separate target | **Build next** (small, and matters in outages) |
| Remote access to forwarding | Change your forwarding by calling in from any phone with a PIN. | ✔ RACF | Webex (remote office) | ✘ My Phone and Companion cover this from a browser | **Skip** (the web covers it) |
| Selective forward, accept and reject | Per-user lists: forward these callers, only ring for these callers, reject these callers. | ✔ `*63/*83`, `*95/*96`, `*60/*80`; up to 20 rule sets | Webex (BroadWorks), NS, Teams (presence rules) | ✘ Only the organization-wide block list | **After 1.0**: "personal call rules" in My Phone |
| Anonymous call rejection | Refuses callers who hide their number. | ✔ `*77/*87` per line | Webex, NS, Vital, Fusion | ◐ Organization-wide rule only | **After 1.0** with personal call rules |
| Personal schedules | Your own weekly schedule and holidays deciding how your calls are handled. | ✔ Incoming Call Manager with weekly schedule and holidays | 3CX (status profiles), Teams | ◐ Presence states switch DND and forwarding, but by hand | **After 1.0**: let presence change on a schedule or from Google Calendar |
| Simultaneous and sequential ring (follow-me) | Rings desk, cell and other numbers together or in turn. | ✔ Follow Me, up to 6 steps | All 20 | ✔ Up to 10 legs, ring-all or in turn, press-1 confirm on outside legs, `*21` | **Done** |
| Call waiting toggle | Turns call waiting off, for good or for one call. | ✔ `*70` for one call | All 20 | ✘ Phones handle it locally; no server toggle | **Build next** (small; gap P2) |
| Hide caller ID | Hides your number on one call, or by default. | ✔ `*67` per call; `*65/*85` permanent | CUCM, Webex, NS, Vonage | ✘ No code or privacy option | **Build next** (small; staff expect `*67`) |
| Call return | Calls back the last person who called you. | ✔ `*69` | Webex, GoTo | ✘ (Veyra already stores the last caller for `*32`) | **Build next** (small) |
| Automatic callback (camp-on) | Rings you back when a busy line frees up. | ✔ `*66/*86` | CUCM, Vital, Grandstream | ✘ | **Skip** (rarely used) |
| Trace a threatening call | Marks a harassing or threatening call so it can be reported. | ✔ `*57` (carrier trace) | CUCM (malicious call ID) | ✘ | **After 1.0**: a "flag this call" code that locks the call record and recording against deletion and alerts the office, useful after a threat |
| Speed dial codes | Dial `*74x`/`*75xx` for stored numbers. | ✔ 8 and 100-entry lists | Most | ◐ Personal contacts have slots 1–99 and can be phone keys, but cannot be dialled as codes | **After 1.0** (small) |
| Three-way calling | Adds a third person to a call. | ✔ | All 20 | ◐ Phones do it themselves | **Skip** on desk phones; revisit for analog ATAs |
| Call Jump / call pull | Moves a live call from desk phone to cell or softphone without hanging up. | ✔ Call Jump; push/pull in MaX UC | RC, Teams, 8x8, GoTo, Vonage, NS | ✘ | **After 1.0**, together with a softphone |
| Live voicemail screening | Listen while the caller leaves a message and pick up. | ✔ | Few | ✘ | **Skip** |
| Reminder and wake-up calls | The system rings you at a set time. | ✔ One-off, daily, weekly | 3CX, Vital, Grandstream, Yeastar | ✘ | **Skip** (hotel feature) |
| Hotline (ring-down) phone | Lifting the handset dials a set number straight away or after a delay. | ✔ Hot line and warm line | CUCM, Teams | ✘ | **Build next** (small): elevator, lobby, vestibule and emergency phones |
| Choose caller ID per call | Pick which number shows when you call out (yours, the main line, a department). | ◐ Set per line or group by the admin | RC, Zoom, Dialpad, GoTo, NS, Teams | ◐ One number per extension, validated against owned numbers | **After 1.0**: a prefix code (for example to call parents as the school's main number) |
| Distinctive ring | Different rings for internal, external or VIP calls. | ✔ `*61/*81`, internal vs external rings | Webex, Teams, CUCM | ✘ Only intercom uses Alert-Info | **After 1.0** (small): internal vs external, and per ring group |
| Call screening | Asks unknown callers to say their name first. | ✘ Not found | Vonage, NS, GoTo, Vital | ✘ | **Skip** |
| Several phones per user | Desk phone, softphone and others on one extension. | ✔ SIP forking | All 20 | ✔ Up to 16 | **Done** |
| Outbound caller ID per user | The number your calls show to the outside. | ✔ Per line or group | All 20 | ✔ Validated against the organization's numbers | **Done** |
| Personal call history | Missed, dialled and received calls for each user. | ✔ Including rejected calls and the rule that matched | All 20 | ✔ 30 days in My Phone with call back and CSV | **Done** |
| Click-to-dial | Start a call from a browser; the desk phone rings first. | ✔ CommPortal, CommPortal Assistant, Outlook | Most | ✔ Web and the Companion extension | **Done** (ahead: Companion force-installs on managed Chromebooks) |

### B. Business group features

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Hunt group algorithms | The order a group's phones ring in. | ✔ Linear, circular, round robin, longest idle, ring all; per-member ring time and skip-after-no-answer | All 20 | ◐ Ring groups: ring all or in order. Queues already have round robin and longest idle. Missing in ring groups: circular, round robin, longest idle, per-member ring time | **Build next** (small; Asterisk already does these in queues) |
| Hunt group log in and out | Members leave and rejoin a group from a key. | ✔ From CommPortal or a phone key | CUCM, NS | ◐ Queues only (`*45/*46`) | **After 1.0** (or steer such groups to queues) |
| Auto attendant (IVR) | "Press 1 for the office" menus. | ✔ Easy and Premium Attendant, multi-level, refuses to activate a broken menu | All 20 | ✔ Nesting, all destinations, timeout and invalid handling, problem check. Missing: multi-digit entries, "return to previous menu", speech | **After 1.0** (small parts) |
| Schedules and holidays | Different routing after hours and on holidays. | ✔ Weekly schedule, special days, automatic public holidays | All 20 | ✔ Time zone, weekly ranges, dates, rules like "4th Thursday", override code | **Done**; optional one-click US holiday set |
| Day/night toggle key | One key or code flips routing to "closed" (snow day, emergency). | ◐ Only through attendant schedules; no toggle key found | Fusion, Vital, NS | ✔ `*28<n>` with PIN and BLF, also from the web and API | **Done** (ahead of Metaswitch) |
| Call park | Park a call in a slot; anyone picks it up. | ✔ Codes vary by operator; park keys | All 20 | ✔ Lots, slots with lamps, timeout ring-back, park key. Missing: park-and-page, private lots | **After 1.0**: park-and-page ("call for Mrs. Smith on 71") |
| Call pickup | Answer a colleague's ringing phone. | ✔ Group `*11`, directed `*12`+ext | All 20 | ✔ `*8`, `**<ext>`, BLF pickup | **Done** |
| Busy lamp field | Keys showing colleagues' state. | ✔ Idle, ringing, busy, parked | All 20 | ✔ Extensions, DND, forwarding, toggles, parking, conferences, queues, presence | **Done** (ahead) |
| Shared line (shared call appearance) | One number appears on several phones; anyone can answer it or pick it up from hold. | ✔ MADN, up to 1,000 per group | CUCM, Webex, Zoom, RC, GoTo, NS, Teams, Grandstream | ✘ Several phones can share an extension, but hold and line state are not shared | **After 1.0**, needs design: Asterisk has no built-in shared appearance for PJSIP phones, so it would likely be BLF plus park-on-hold (my assessment) |
| Intercom | Calls a phone that answers itself on speaker. | ◐ Phone-side keys only | Most | ✔ `*80<ext>`, allow/deny per user, auto-answer in templates | **Done** (ahead) |
| Paging | Broadcast to phone speakers and overhead speakers. | ◐ Phone-side multicast only; no server paging | All except Teams | ✔ Zones, multicast and Poly pages in step, priority and emergency pages, bells. Missing: talk-back paging, live page from the browser | **After 1.0**: live page from the browser (office staff on a laptop in a lockdown) |
| Listen, whisper, barge | A supervisor silently listens, coaches the staff member, or joins the call. | ✔ `*47/*48/*49` on hunt groups | 3CX, Fusion, Vital, CUCM, RC, Teams, Zoom, Webex, 8x8, NS | ✘ | **Build next**, with permissions and an audit trail (Asterisk ChanSpy does the audio) |
| Executive / assistant | An assistant screens and places calls for a boss. | ✘ Not found | Webex, Teams, Zoom, 3CX, CUCM, Wazo | ✘ | **After 1.0** (principal and superintendent offices) |
| Receptionist console | A screen for the front desk: every call, drag-to-transfer, park, presence. | ◐ Partner product (Voice Operator Panel) | 3CX, Fusion, Vital, Wazo, Yeastar, Grandstream, IPO, 8x8, GoTo, Zoom | ✘ Colleagues widget with presence and click-to-dial only | **After 1.0**, high priority: most pieces exist (live calls, parking, presence) |
| Music on hold | Audio for waiting callers. | ✔ Upload, per line | All 20 | ✔ Sets, shuffle, internet streams, built-in music. Missing: per inbound number | **Done** |
| Dial-by-name directory | Callers spell a name. | ✔ In the attendant | Most | ✔ With custom entries and operator | **Done** |
| Company short codes | Short numbers for common destinations (district office, the other school). | ✔ Up to 1,000, CSV import | Webex, CUCM | ◐ Personal contacts and phone directory only | **After 1.0** (small) |
| Settings templates for many users | Default forwarding, barring and caller ID applied to a group of lines. | ✔ Call Service Groups | Webex, CUCM | ◐ Classes of service and device profiles; no user template | **Build next** together with bulk import |
| Departments with limits | Sub-groups with their own admin and call limits. | ✔ Nested departments with concurrent call limits | Webex, NS | ◐ Organizations, sites, buildings, departments and scoped admin roles; call caps per class of service, not per department | **After 1.0** (small) |
| Hot desking | Log in to any shared phone and it becomes yours. | ✘ Not found | 3CX, Fusion, Vital, Yeastar, Mitel, CUCM, Webex (free licence), RC, 8x8 | ✘ | **After 1.0**: substitutes and travelling staff; 911 location must follow the phone, not the user |
| Classroom and common-area phones | Phones that belong to a room, not a person. | ✔ Lines without a user | Teams, Webex, Zoom (paid licences) | ✔ Extensions need no person or number, and there is no per-seat fee | **Done** (ahead on cost) |
| Dialling between buildings | Short extension dialling across sites. | ✔ One group up to 40,000 lines | CUCM, IPO, Yeastar, Mitel | ◐ One numbering plan per organization on one installation; none between separate installations | **After 1.0**, only if a district runs more than one installation |
| DISA | Call in, enter a PIN, get an outside line. | ✘ | Fusion, Vital, Grandstream | ✘ | **Skip** (toll-fraud risk) |

### C. Voicemail and messaging

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Voicemail boxes | Callers leave a message; PIN, MWI lamp. | ✔ | All 20 | ✔ Encrypted PIN, `*97/*98`, operator key, shared inboxes with lamps | **Done** |
| Situational greetings | Different greetings for busy, after hours, extended absence or internal callers. | ✔ Including an extended-absence greeting that can refuse new messages | Teams (out of office) | ◐ Unavailable, busy, name and temporary. Missing: after-hours greeting from a schedule, and an absence greeting that refuses messages | **Build next** (small): a summer-break greeting for teachers |
| Web inbox (visual voicemail) | Play, download and manage messages in a browser or app. | ✔ CommPortal, MaX UC | Most | ✔ Folders, download, forward, "call me to play", email and delete | **Done** |
| Voicemail to email | Messages arrive as email attachments. | ✔ | All 20 | ✔ Deletes only after the mail server accepts it | **Done** |
| Voicemail transcription | Turns messages into text in the email and inbox. | ✔ Since 2010 (Nuance) | All cloud services, 3CX, Fusion, Vital, Yeastar | ✘ | **After 1.0** as a module, with an on-premises speech model so audio stays on site |
| Distribution lists | Leave one message for many mailboxes (all staff). | ✔ Group mailboxes and nested lists | Vital, Yeastar, Grandstream, NS | ◐ Shared inboxes only | **After 1.0** (small) |
| Keep voicemail inside the organization | Stops messages being forwarded to outside addresses. | ✔ Restricted messaging | Teams (protected voicemail) | ✘ Email can go to any address an admin types | **After 1.0** (small; student-privacy angle) |
| Notification options | Pager, outdial or several email addresses on a new message. | ✔ | Few | ◐ Email, lamp and missed-call email | **Skip** beyond what exists |
| Inbound fax to email | Faxes arrive as PDFs. | ✔ Fax mailboxes | Most | ✔ Fax inboxes as a destination, T.38 per trunk. Missing: fax detection on voice numbers; untested with a real carrier | **Build next**: test with your carrier; fax detection **after 1.0** |
| Send a fax | Send a PDF as a fax. | ✘ No email-to-fax found | RC, Zoom, 8x8, GoTo, 3CX | ✔ From My Phone with cover sheet and retries. Missing: email-to-fax | **Done** (ahead of Metaswitch) |
| Business texting (SMS) | Text from the business number. | ◐ Needs a third-party SMPP provider | All cloud services, 3CX, Fusion, Yeastar | ✘ | **Module**, through a carrier API; US texting needs 10DLC registration |
| Chat and team messaging | Staff instant messaging. | ✔ MaX UC IM | All cloud services, most PBXs | — | **Skip** (Google Chat or Teams already does this) |
| WhatsApp, website chat | Social and web chat in the phone system. | ✘ | 3CX, Yeastar, Grandstream, Issabel | ✘ | **Skip** |
| Video mail | Video messages. | ✔ | Few | ✘ | **Skip** |

### D. Apps, portals and mobility

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| User web portal | Users manage their own settings, voicemail and history. | ✔ CommPortal | All 20 | ✔ My Phone: widget layout, admin-locked widgets and keys, presence, contacts, fax | **Done** (ahead) |
| Browser phone (WebRTC) | Make and take calls in a browser tab, no install. | ◐ Old CommPortal web calling | 3CX, Yeastar, Grandstream, Vital, Fusion, Wazo, RC, Teams, NS | ✘ | **After 1.0**, high priority: Asterisk supports WebRTC, and it works on Chromebooks |
| Desktop softphone | A calling app for Windows and Mac. | ✔ MaX UC Desktop (end-of-life notice in 2024; Alianza still sells it) | All cloud services, 3CX, Yeastar, Grandstream, Vital, CUCM, IPO, Mitel | ✘ Third-party SIP softphones can register | **Skip** a native app; the browser phone covers it |
| Mobile app with push | Your extension on your cell phone, ringing even when the app is closed. | ✔ MaX UC Mobile | All cloud services, 3CX, Yeastar, Grandstream (free), Vital, CUCM, IPO, Mitel | ✘ | **After 1.0**: provision a proven third-party app with push rather than building one |
| Single number reach | Your cell acts as your office line, including showing the office number when you call out. | ✔ Twinning, Call Jump | Webex, CUCM, Mitel, IPO, NS | ◐ Follow-me rings the cell, but calls out from the cell show the cell number | **After 1.0**, with the mobile app |
| Browser extension | Click any number on a web page to call it; caller pop-ups. | ◐ Windows CommPortal Assistant | 3CX, Yeastar, Grandstream, 8x8 | ✔ Companion: click-to-dial, directory, pop-ups, SSO, emergency pop-up, force-install on managed Chrome. Missing: answer and hang up from the browser | **Done** (ahead) |
| Presence | Shows colleagues as available, busy, away or in a meeting. | ✔ | All 20 | ✔ Six states with automatic DND and forwarding. Missing: "in a meeting" from Google or Outlook calendars | **After 1.0** (calendar-driven presence) |
| Contacts sync | Pull Google or Outlook contacts into the directory and phones. | ✔ Outlook sync | 3CX, Yeastar, Grandstream | ◐ Personal contacts with CSV import | **After 1.0** |
| Apps on the desk phone screen | Voicemail list, presence and settings on the phone's display. | ✔ CommPortal phone apps on Yealink | FreePBX (paid) | ✘ Keys and lamps only | **Skip** for now |
| Hot desking | See section B. | ✘ | Many | ✘ | **After 1.0** |

### E. Conferencing

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Conference bridge | A dial-in room with PINs. | ◐ Depends on the operator (older conference server) | All 20 | ✔ Rooms with participant and admin PINs, recording, in-room keys, lamps | **Done** |
| Personal rooms | Each user owns a room and runs it from the portal. | ✘ | Fusion, NS, FreePBX (paid) | ✘ | **After 1.0** (small) |
| Video meetings and screen share | Browser video meetings. | ✔ Zoom-powered MaX Meeting | All cloud services, 3CX, Grandstream, Yeastar, Vital | — | **Skip** (Meet, Zoom or Teams already in place) |

### F. Queues and call centre

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Call queues | Callers wait in line for the next free person. | ✔ Integrated ACD on hunt groups | All 20 | ✔ Six strategies, penalties, wrap-up, position announcements, break-out menu, failover | **Done** (ahead: Metaswitch has no position announcements per one operator's guide) |
| Agent log in and pause | Agents join, leave and pause. | ✔ Plus up to 30 "unavailable" reasons | 3CX, NS, Teams, Zoom, Webex | ◐ `*45/*46` with lamps. Missing: pause reasons | **After 1.0** (small) |
| Disposition codes | Agents tag each call's outcome. | ✔ Up to 30 per queue | NS, Dialpad | ✘ | **Skip** |
| Live queue board (wallboard) | Live callers waiting, wait times and agent states on a screen. | ✔ Supervisor dashboard, 30-second refresh | 3CX, Yeastar, Zoom, Teams, NS, 8x8, Webex | ✘ `*47` reads the waiting count; reports are after the fact | **After 1.0**, high priority (attendance lines, utility billing, front offices) |
| Supervisor listen, whisper, barge | See section B. | ✔ | Most | ✘ | **Build next** |
| Scheduled queue reports | Emailed reports on waits and abandons. | ✔ | Most | ✔ Report builder with scheduled CSV email | **Done** |
| Queue callback | Callers keep their place and get called back. | ✘ | 3CX, Vital, Yeastar, Teams, 8x8, GoTo, NS | ✘ | **After 1.0** (city utility and tax lines) |
| Skills routing, omnichannel, workforce management | Full contact-centre tooling. | ✘ Partners only | Big cloud contact centres | ✘ | **Skip** |

### G. Dialling rules, 911 and carrier features

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Class of service | Controls who can dial long distance, international and so on. | ✔ Call barring per line or template | Most | ✔ Allowed routes and codes, outside forwards, fax, outside-call cap. Missing: time-of-day limits | **Done**; time limits **after 1.0** |
| Concurrent call limits | Caps simultaneous calls per group or department. | ✔ Per group and department, in and out | Vital, Grandstream, NS | ◐ Per class of service (outbound) and per trunk | **After 1.0** (useful when hosting several organizations) |
| Account codes | Users enter a code to tag calls for billing. | ✔ Optional or forced, per call type, lockout | Vital, CUCM, NS, Zoom | ✘ | **Skip** unless a town wants department billing |
| Authorization PINs | A PIN unlocks restricted dialling (a teacher's long-distance call from a classroom phone). | ✘ Account codes used instead | Vital, CUCM, NS | ✘ | **After 1.0** (small; gap P2) |
| Direct 911 and on-site notification (Kari's Law) | 911 dials without a prefix and alerts the office. | ◐ Left to the operator; not documented | Grandstream, Yeastar, IPO, Teams, Zoom, NS; CUCM needs an add-on | ✔ Email, recorded page, responder phones, webhook and Companion pop-up; readiness page per site | **Done** (well ahead) |
| Dispatchable location (RAY BAUM'S) | Sends building, floor and room to the 911 centre. | ◐ Through the operator's location database | Teams, Zoom, RC, NS, Webex (dynamic); Yeastar, Grandstream (per room or subnet) | ◐ ELIN per site and building, room per extension. Missing: location for remote softphones | **After 1.0**, only when softphones arrive (needs a carrier E911 API) |
| 911 callback routing | Callbacks from 911 reach the caller or the office. | Not documented | Yeastar, Grandstream, CUCM | ✔ Callback window rings the caller, then responders | **Done** |
| 911 when all lines are busy | Drops or reserves a channel so 911 always gets out. | Not documented | Grandstream | ✘ Not found in the repository | **Build next** (small; a reserved channel per trunk) |
| STIR/SHAKEN and verified caller ID | Carrier signs outbound calls and marks inbound ones verified or failed. | ✔ QCall, carrier side | Carriers for all | ✘ Carrier's job; Veyra ignores the carrier's verification result | **After 1.0** (small): show "verified" in call history and let the block list refuse failed calls |
| Spam and robocall blocking | Labels or blocks likely spam. | ✔ Carrier analytics (TNS) | Teams, Zoom, RC | ◐ Manual block list and anonymous rule | **Module**: spam score or CNAM lookup service |
| Caller name lookup (CNAM) | Shows the caller's name from a database. | ✔ Carrier | Most | ◐ Internal names and personal contacts only | **Module**; first check whether your carrier already sends names |
| Toll-fraud protection | Stops hackers making expensive calls. | ✔ Lockouts and call limits | Most | ✔ Firewall with automatic bans, call caps, generated secrets | **Done** (ahead) |
| Encrypted calls (TLS and SRTP) | Encrypts signalling and audio. | ✔ | All 20 | ◐ TLS yes; SRTP audio encryption not built | **Build next** (still-open P1 from the FreePBX analysis) |
| Analog lines and old digital trunks | Analog phones, fax machines, PRI and T1 lines. | ✔ Carrier-grade (GR-303, MGCP, PRI, ATAs) | Yeastar, Grandstream, IPO, CUCM | — Gateways and ATAs instead; ATA template still on request | **Build next**: the ATA template (fax machines, door phones, elevator lines, alarm panels) |
| Least-cost routing | Picks the cheapest trunk per call. | ✔ Carrier selection | Vital, Grandstream | ✘ | **Skip** (flat-rate SIP trunks) |

### H. Recording, reports and AI

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Call recording | Records calls by rule or on demand. | ✔ Group recording; partner cloud (CallCabinet) | All 20 | ✔ Policies by direction and target, `*1` on demand, encrypted per recording, audited playback, holds | **Done** (ahead) |
| Pause recording | Pauses during card payments or sensitive talk. | ✘ | NS, Dialpad, Webex, 8x8 | ◐ `*1` stops and starts on-demand recording only | **After 1.0** (small; town payment lines) |
| Archive recordings off the box | Copies recordings to SFTP or S3. | ◐ Through the partner cloud | Yeastar, Grandstream | ✘ | **Build next** alongside Milestone 22's SFTP and S3 backups |
| Call history and reports | Searchable call records and charts. | ✔ CSV for 30 days; licensed reports (frequent callers, long ringing, missed calls) | All 20 | ✔ 400 days, report builder with saved and scheduled reports | **Done** (ahead) |
| Call quality scores | Jitter, packet loss and MOS per call. | ◐ Operator-side tools | RC, Zoom, 8x8, NS, Webex | ✘ Packet capture only | **After 1.0**: store Asterisk's per-call RTP stats in call history |
| AI call transcripts, summaries, sentiment | Text and summaries of recorded calls. | ✘ Voicemail only; Alianza promises an AI layer | 3CX, Yeastar, Vital, all cloud services | ✘ | **Module**, after voicemail transcription; mind student-privacy rules |
| Retention and audit | How long data is kept; who did what. | ◐ Operator controlled | Few | ✔ Per data class, full audit log, re-confirm for sensitive actions | **Done** (ahead) |

### I. Integrations and APIs

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Open API and webhooks | Lets other systems read and drive the phone system. | ✘ Closed, partner-gated | Wazo, Yeastar, Grandstream, all cloud services | ✔ REST, WebSocket events, signed webhooks, scoped tokens | **Done** (well ahead) |
| Single sign-on | Sign in with Google or Microsoft. | ✘ Not found | Yeastar, Grandstream, IPO, cloud services | ✔ OpenID Connect (Google, Entra) with MFA policy. Missing: SAML | **Done**; SAML **skip** unless asked |
| Directory sync | Creates and removes users from Google Workspace, Entra ID or AD. | ◐ LDAP in the operator panel only | Yeastar, Grandstream, CUCM, IPO, Teams | ✘ | **After 1.0**, high priority (staff turnover every August) |
| Microsoft Teams calling | Use the PBX line from inside Teams. | ✔ MaX UC Connector for Teams; certified Direct Routing SBC | RC, Zoom, Webex, 8x8, 3CX, Yeastar, Grandstream | ✘ | **Skip** unless a Teams district asks |
| CRM or student-system lookup | Caller pop-up from a CRM or the student information system. | ◐ MaX UC lookup | 3CX, Yeastar, Grandstream, cloud services | ✘ Webhooks only | **Module**: a student-system lookup could show which family is calling |
| AI receptionist | An AI answers the main line, answers questions and routes calls. | ✘ (Alianza AI layer planned for 2026) | 3CX, Yeastar, Vital, RC, Zoom, Webex, GoTo, Dialpad, Nextiva, NS | ✘ | **Module**, later: per-minute AI costs and accuracy need care; not before the core is finished |
| Door and building systems | External systems trigger pages or calls. | ✘ | Few | ✔ Integration token starts a page (for example a door controller) | **Done** (ahead) |
| Third-party tool access (AMI/ARI) | Lets operator panels and wallboards connect. | ✘ | Vital, Grandstream, IPO | ✘ Internal only | **Skip** while the API grows |

### J. Administration and platform

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Admin portal and scoped admins | Manage the system; local admins see only their part. | ✔ Group admin and department admins; many changes need an operator ticket | All 20 | ✔ Roles scoped by organization and site, custom roles | **Done** (ahead: no ticket to the carrier) |
| Log in as a user | Help desk sees exactly what a user sees. | ✔ | NS | ✘ | **After 1.0** (small, audited) |
| Phone auto-provisioning | Plug in a phone and it configures itself. | ✔ Yealink, Poly, Cisco | All 20 | ◐ Poly VVX, Edge and CCX, all current Yealink, Algo, with HTTPS and locked keys. Missing: none hardware-verified; Grandstream, ATA, CyberData on request | **Build next**: hardware checks first |
| Bulk import and export | Load users, extensions and numbers from a spreadsheet. | ◐ Short codes, contacts, line lists | Most | ✘ Planned in Milestone 22 | **Build next** (Milestone 22) |
| High availability | A standby takes over if the main server fails. | ✔ Clustered, geo-redundant, run by the carrier | 3CX, Vital, Yeastar, CUCM, cloud services | ◐ Active/passive with manual switchover; two-server test pending | **Build next**: finish the two-server test, then automatic failover |
| Branch survivability | A building keeps calling locally if its link to the main site fails. | — Carrier network | CUCM, Mitel, Zoom, Webex | ✘ | **Skip** for now; revisit for multi-building districts on one server |
| Multi-tenancy | One system hosts several separate organizations. | ✔ Reseller hierarchy with white-label | NS, Fusion, Vital, 3CX, Yeastar | ✔ Isolated namespaces with a verifier, central console. Missing: reseller tier, per-organization branding | **After 1.0**, only if the MSP market matters |
| Updates and security | Patching, MFA, firewall. | ◐ Operator controlled; password policy only | Mixed | ✔ Signed updates with maintenance windows, TOTP, firewall with auto-bans, encrypted secrets | **Done** (ahead) |
| Off-box backups and Let's Encrypt | Backups to SFTP or S3; trusted certificates. | — Carrier | Most | ◐ Verified encrypted local backups; own CA | **Build next** (Milestone 22) |
| Billing | Rates and bills calls. | ✔ Through billing partners | Vital, Yeastar, Grandstream | — | **Skip** |

### K. Schools, towns and specialty

| Feature | What it does | Metaswitch | Others with it | Veyra today | Recommendation |
| --- | --- | --- | --- | --- | --- |
| School bells | Calendar-driven bells over the speakers. | ✘ | Few (paging schedulers) | ✔ Google or iCal calendars, built-in bell sounds | **Done** (unique) |
| Lockdown and mass alerts | All-call, strobes and clock messages in an emergency. | ✘ | Mitel (Revolution), Cisco (InformaCast), 8x8 Resolve | ◐ Emergency pages, locked all-call key, AND clock messages, Algo strobes; not a certified life-safety system | **After 1.0**: integrate with a certified system rather than become one |
| Voice broadcast dial-out | Calls a list of families with a recorded message (closings). | ✘ | Vital, Yeastar, Issabel | ✘ | **Module**, only if the district doesn't already use a notification service |
| Door phones and vestibules | Door station rings the office; a key unlocks the door. | ◐ SIP endpoints only | Yeastar (video preview), Grandstream | ◐ Algo door templates; no documented door-release key flow, no video | **After 1.0**: a door-release key and a snapshot in the Companion pop-up |
| Hotel features | Check-in, wake-up, room status. | ✘ | 3CX, Yeastar, Grandstream, Mitel | — | **Skip** |
| Live translation | Translates a call between languages. | ✘ | Webex, RC | ✘ | **Skip** for now; watch for an affordable on-premises option |

## Moving people off Metaswitch

Staff coming from a Metaswitch hosted PBX will notice star codes first. Veyra's codes follow FreePBX and can already be changed on the Feature Codes page, so a preset matching the carrier's codes is cheap. Several Veyra defaults collide with common Metaswitch codes, which is the part that would confuse people.

| Function | Metaswitch (Sparklight guide; others vary) | Veyra default | Match? |
| --- | --- | --- | --- |
| Forward always on / off | `*72` / `*73` | `*72` / `*73` | Same |
| Forward on busy on / off | `*90` / `*91` | `*90` / `*91` | Same |
| Forward on no answer on / off | `*92` / `*93` | `*52` / `*53` | Different |
| Do not disturb on / off | `*78` / `*79` | `*78` / `*79` | Same |
| Group pickup | `*11` | `*8` | Different |
| Directed pickup | `*97` (`*12`+ext at DePauw) | `**<ext>` | Different; Veyra's `*97` opens your voicemail |
| Call park | `*68` (`*53` or `*14` elsewhere) | Dial the parking lot number | Different |
| Voicemail | `*62` or `*98` | `*97` own box, `*98` any box | Partly |
| Selective call rejection | `*60` / `*80` | `*60` is the speaking clock; `*30` blocks a caller | Collides |
| Selective call acceptance | `*95` / `*96` | `*95` records a prompt | Collides |
| Hunt group monitor / whisper / barge | `*47` / `*48` / `*49` | `*47<queue>` reads callers waiting | Collides |
| Hide caller ID, call return, call waiting off | `*67`, `*69`, `*70` | None | Missing |
| Anonymous call rejection | `*77` / `*87` | None per user | Missing |

I recommend a "carrier code set" option, loaded from the code card your current carrier gave staff, plus the three missing codes above. The other things Metaswitch users lean on are Business Call Manager rules (personal schedules and caller lists), the CommPortal call lists that show why a call was rejected, round-robin hunt groups, shared lines, and the MaX UC apps. The chart above covers each of these.

Things Veyra should not copy from Metaswitch: operator tickets for routine changes, a closed API, per-line pricing, and features designed for home phone lines (teen line, IPTV caller ID, carrier selection).

On Metaswitch's future: it is supported by Alianza for now, but the MaX UC apps carry Microsoft's 2024 end-of-life notice and Alianza is moving operators toward its own cloud. A district on a Metaswitch-based service should expect its carrier to change the apps or the platform within a few years. That is a fair argument for owning the phone system with Veyra.

## Recommended roadmap

Thirty-five items, grouped by my recommendation. The decision column is yours: pick Approve, Later, Reject or Discuss on each row. Size is my rough estimate: S is a few days, M a week or two, L a milestone.

| # | Tier | Item | Why | Size | Your decision |
| --- | --- | --- | --- | --- | --- |
| 1 | Build next | Milestone 22 as planned, plus user templates and recording archive to SFTP/S3 | Bulk import and off-box backups block every migration, from Metaswitch or FreePBX | L |  |
| 2 | Build next | Hardware-verify the Poly and Yealink templates; add the ATA template | No template is verified yet; ATAs carry fax machines, door and elevator phones | M |  |
| 3 | Build next | Encrypted audio (SRTP) | Still-open P1 from the FreePBX analysis | M |  |
| 4 | Build next | Two-server HA test, then automatic failover | Metaswitch users are used to a carrier that never goes down | L |  |
| 5 | Build next | Telco habit codes: `*67`, `*69`, `*70`, anonymous call rejection | Staff from a telco hosted PBX dial these on day one | S |  |
| 6 | Build next | Carrier code set (a feature-code preset matching the old carrier's card) | Removes the code collisions listed above | S |  |
| 7 | Build next | Forward when the phone is offline | Keeps calls flowing to cell phones in an outage | S |  |
| 8 | Build next | Round robin, circular and longest-idle ring groups with per-member ring time | Metaswitch has five hunt methods; Veyra ring groups have two | S |  |
| 9 | Build next | Supervisor listen, whisper and barge with permissions and audit | Front-office training and queue supervision | M |  |
| 10 | Build next | Hotline (ring-down) phones | Elevator, lobby, vestibule and emergency phones | S |  |
| 11 | Build next | Extended-absence (summer) voicemail greeting | Teachers away for the summer | S |  |
| 12 | Build next | "These callers still ring" list for DND | Metaswitch has it; small | S |  |
| 13 | Build next | Reserve a channel so 911 always gets out | Life-safety gap; small | S |  |
| 14 | Build next | Test fax with your carrier | Fax is built but untested on a real carrier | S |  |
| 15 | After 1.0 | Browser phone (WebRTC) in My Phone and the Companion | Calls from Chromebooks and laptops without an install | L |  |
| 16 | After 1.0 | Receptionist console | The front desk's main tool; most pieces exist | L |  |
| 17 | After 1.0 | Live queue board and pause reasons | Attendance lines, utility billing | M |  |
| 18 | After 1.0 | Google Workspace and Entra directory sync | Staff turnover every August | M |  |
| 19 | After 1.0 | Voicemail transcription on premises | Metaswitch has had it since 2010 | M |  |
| 20 | After 1.0 | Hot desking | Substitutes and travelling staff | M |  |
| 21 | After 1.0 | Personal call rules: selective accept, reject and forward, schedules, calendar-driven presence | Metaswitch's Business Call Manager | M |  |
| 22 | After 1.0 | Shared line appearance (design first) | Office and principal sharing a line | L |  |
| 23 | After 1.0 | Mobile app (a proven third-party app with push) and single number reach | Replaces MaX UC Mobile | M |  |
| 24 | After 1.0 | Executive / assistant | Principal and superintendent offices | M |  |
| 25 | After 1.0 | Queue callback | Long waits on town lines | M |  |
| 26 | After 1.0 | "Flag this call" for threats | Locks the record and recording and alerts the office | S |  |
| 27 | After 1.0 | Park-and-page and live page from the browser | Front office habits and lockdowns | M |  |
| 28 | After 1.0 | Door-release key and a snapshot in the Companion pop-up | School vestibules | M |  |
| 29 | After 1.0 | Small items: company short codes, speed-dial codes, distinctive ring, caller ID per call, authorization PINs, distribution lists, IVR multi-digit and return, call quality stats, verified-caller display, personal conference rooms, log in as a user | Each is a day or two of work | S each |  |
| 30 | Module | Business texting (SMS) | Needs a carrier API and 10DLC registration | M |  |
| 31 | Module | Spam score and caller name lookup | Check first what the carrier already sends | S |  |
| 32 | Module | AI receptionist and AI call summaries | Per-minute costs and privacy need care | L |  |
| 33 | Module | Voice broadcast dial-out (closings) | Only if no notification service is in use | M |  |
| 34 | Module | Student information system caller lookup | Shows which family is calling | M |  |
| 35 | Skip | Chat, video meetings, omnichannel inboxes, skills routing and workforce management, Teams calling, telephony cards, billing, hotel features, camp-on, live voicemail screening | Other tools already cover them, or Veyra's users don't need them | — |  |

## Sources and confidence

Veyra facts come from the repository at commit f5b12b4 (0.27.18): `CHANGELOG.md`, the milestone reports 18 to 21, `docs/` and the code (`backend/veyra/telephony/features.py`, the generator, the API routers, the provisioning templates). Platform facts come from 168 pages opened on 2026-10-20. The full research notes, with a source for every row, are next to this file: [metaswitch.md](metaswitch.md), [onprem.md](onprem.md), [ucaas.md](ucaas.md) and [veyra.md](veyra.md). Where a row says "not found", I found no evidence, which is not proof the feature is missing. Rows built on general knowledge rather than a page are marked "(inferred)" in those notes.

Key sources:

- Metaswitch ownership and status: [Fierce Network, Dec 2024](https://www.fierce-network.com/cloud/exclusive-alianza-buys-metaswitch-microsoft-deal-years-making), [Alianza completes acquisition](https://www.alianza.com/whats-new/alianza-completes-acquisition-of-metaswitch-from-microsoft/), [Fierce Network, Sept 2025](https://www.fierce-network.com/cloud/alianzas-metaswitch-assets-arent-going-anywhere), [Alianza on the MaX UC sunset](https://www.alianza.com/blog/threat-level-rising-microsoft-to-sunset-maxuc/), [ECG](https://www.ecg.co/blog/alianza-metaswitch-future)
- Metaswitch features: [Sparklight star codes](https://business.sparklight.com/support/downloads/7671/Metaswitch%20Star%20Code%20v2.pdf), [Momentum CommPortal guide](https://info.momentumtelecom.com/rs/476-ZWP-927/images/CNG%20MaX%20CommPortal%20UG.pdf), [FirstLight admin guide](https://www.firstlight.net/wp-content/uploads/2021/05/13-CommPortal-Admin-Guide.pdf), [FirstComm ACD guide](https://www.firstcomm.com/wp-content/uploads/2019/12/Integrated-ACD-Admin-Guide.pdf), [Allstream admin guide](https://support.allstream.com/wp-content/uploads/2023/01/USER-GUIDE-Hosted-Voice-Service-Admin.pdf), [DePauw hosted PBX guide](https://kb.depauw.edu/wp-content/uploads/2017/01/HPBX-End-User-Guide-2.1.pdf), [Norvado attendant guides](https://norvado.com/wp-content/uploads/2021/06/Easy-and-Premium-Attendant-Guides.pdf), [Grid4 hunt group settings](https://www.grid4.com/?p=2834), [MaX UC client datasheet](https://info.metaswitch.com/hubfs/pdfs/metaswitch-datasheet-max-uc-client.pdf), [QCall datasheet](https://info.metaswitch.com/hubfs/PDFs/metaswitch-datasheet-metasphere-qcall.pdf)
- Self-hosted platforms: [3CX editions](https://www.3cx.com/ordering/pricing/features/), [3CX price list](https://www.3cx.com/ordering/pricing/pricelist/), [Yeastar P-Series](https://www.yeastar.com/p-series-ip-pbx/), [Yeastar emergency calling](https://help.yeastar.com/en/p-series-software-edition/administrator-guide/emergency-calling-overview.html), [Grandstream UCM emergency guide](https://documentationdev.grandstream.com/wp-content/uploads/2021/10/UCM_Emergency_Calls_Guide.pdf), [VitalPBX features](https://vitalpbx.com/wp-content/uploads/2025/02/VITALPBX-FULL-FEATURES-LIST-FEBRUARY-2025.pdf), [FusionPBX features](https://docs.fusionpbx.com/en/latest/features/features.html), [CUCM 15 feature guide](https://www.cisco.com/c/en/us/td/docs/voice_ip_comm/cucm/admin/cucm_b_feature-configuration-guide-for-15.pdf), [Avaya IP Office fact sheet](https://www.avaya.com/content/dam/aem-avaya-portal/en_us/documents/fs-ipo-platform-sme8093en.pdf)
- Cloud platforms: [Webex/BroadWorks feature list](https://help.webex.com/article/nsyoaiy), [Teams Phone](https://learn.microsoft.com/da-dk/microsoftteams/here-s-what-you-get-with-phone-system), [Zoom Phone features](https://www.zoom.com/en/products/voip-phone/features/), [RingCentral datasheet](https://assets.ringcentral.com/us/datasheet/all-about-ringcentral-phone.pdf), [NetSapiens feature list (Momentum)](https://university.gomomentum.com/wp-content/uploads/2025/02/Tutorial-Cloud-PBX-Features-QRG.pdf), [Dialpad feature comparison](https://help.dialpad.com/docs/dialpad-feature-comparison.md)

Limits: the vendor's own Metaswitch feature guide was not reachable, so Metaswitch rows rely on operator guides. No public page confirmed Chariton Valley's platform. Avaya and some Wazo pages could not be read. Prices drift and several come from competitor roundups.
