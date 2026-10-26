# Metaswitch (MetaSphere CFS/EAS, CommPortal, MaX UC / Accession): hosted PBX and Business Group feature set

Research date: 2026-10-20. Rows marked **(inferred)** are my reading or general knowledge and were not confirmed in a page I opened. Star codes **differ between operators**: each carrier configures its own access codes on the CFS. Codes below name the operator guide they came from.

Source keys used in the tables (full URLs are in the Sources list at the end):
- [SPK] Sparklight (Cable One) "Metaswitch Star Code v2" / Feature Access Codes Quick Reference
- [MOM] Momentum/CNG "CommPortal User Guide V9.5.40 Powered by MaX UC" (subscriber and BG Admin)
- [PSTN] Metaswitch "MetaSphere PSTN Emulation Services" brochure (2011)
- [DPW] DePauw University Hosted PBX End User Guide 2.1 (Metaswitch-based, references the "Metaswitch Hosted IP PBX Administrator Guide")
- [ALS] Allstream "Hosted Voice Service Enterprise Administrator Guide" (CommPortal BG Admin, May 2017)
- [FL19] / [FL21] FirstLight CommPortal Admin guides (2019, 2021)
- [FC-CP] FirstComm CommPortal User Guide; [FC-ACD] FirstComm Integrated ACD Admin Guide
- [NOR] Norvado "Easy and Premium Attendant Guides"
- [G4-MLHG] Grid4 MLHG Settings KB; [BTC] BTC Broadband MLHG setup
- [G4-D] / [G4-M] Grid4 MaX UC Desktop / Mobile user guides
- [MCT] Saddleback "QRG MCT" (MaX UC Connector for Teams)
- [MSG] Metaswitch "MetaSphere Messaging" brochure; [VOP] Metaswitch Voice Operator Panel datasheet
- [MAXDS] MaX UC datasheet; [MAXCL] MaX UC Client datasheet
- [YLK] Yealink-Metaswitch Configuring Guide; [MVW] MetaView Web brochure; [QCALL] MetaSphere QCall datasheet

---

## Overview

**What it is.** Metaswitch (originally Data Connection Ltd, founded 1981, renamed Metaswitch Networks in 2009) built the software Class 5 / Class 4 switching and application servers that hundreds of North American ILECs, rural telcos, cable MSOs and CLECs use for residential POTS replacement and hosted business voice. Alianza calls it "the number one supplier of Class 5 softswitch licenses in North America." Small operators white-label it as "Hosted PBX", "Cloud Voice" or "Hosted Voice". Examples confirmed in opened pages: Sparklight/Cable One, Momentum/CNG, FirstComm, FirstLight, Grid4, BTC Broadband, Norvado, Allstream, Allwest and Saddleback. Chariton Valley (MO) was named in the brief, but no opened page confirmed it runs on Metaswitch, so treat it as **unverified**.

**Product lines (hosted business view)**
- **MetaSphere CFS (Call Feature Server):** the softswitch and feature engine. It provides CLASS / residential line features, the Business Group (Centrex/hosted PBX) features, MLHG hunt groups, MADN shared lines, pickup, park, account codes and call limits. CFS is deployed clustered for HA.
- **MetaSphere EAS (Enhanced Application Server):** voicemail and unified messaging, fax mailboxes, Easy/Premium Attendant (auto attendant), Integrated ACD (iACD), Music on Hold (N-Series), reminders, the CommPortal web portal and APIs, and the phone Device Management / Phone Configurator.
- **CommPortal:** the web self-care portal for subscribers and for the Business Group Administrator (BG Admin). Related pieces are the CommPortal Assistant desktop tool and the CommPortal Phone Applications on Yealink and Polycom phones.
- **Accession, renamed MaX UC around 2019-2020:** branded UC softclients for Windows, Mac, iOS and Android, with presence and IM over the Accession Messaging Service (XMPP). Add-ons were Accession Meeting / MaX Meeting (Zoom-powered video and webinar), MCT (MaX UC Connector for Microsoft Teams), and the Voice Operator Panel receptionist console (by partner Joher).
- **MetaView:** the element manager and provisioning system (MetaView Web, MetaView SIP Provisioning Server, Service Assurance Server, ServiceIQ analytics).
- **Perimeta SBC:** the session border controller, including the Microsoft Teams Direct Routing certified SBC. **MetaSphere QCall** does STIR/SHAKEN signing and verification. **Rhino TAS / Mobile Control Point** serve mobile operators, for example Teams Operator Connect Mobile. **Clearwater Core** is the IMS product.

**Ownership and status timeline**
- **May 2020:** Microsoft announced it would acquire Metaswitch. The deal **closed 15 July 2020**, and Metaswitch became part of Azure for Operators.
- **May 2024:** Microsoft issued an **end-of-life notice for the MaX UC app**. Alianza's blog of 20 May 2024 dates it about a month before the layoffs. Microsoft steered operators toward Teams/Teams Phone. **June 2024:** Microsoft laid off most of the traditional Metaswitch staff (sales, SE, professional services and developers). Microsoft referenced **2029** as a "first possible" end-of-support date for other products (ECG).
- **10 Dec 2024:** Alianza announced a definitive agreement to buy nearly all Metaswitch assets, with about 300 staff and more than 400 patents. Microsoft kept Nexus/packet core. Alianza said it would **reverse some of the 2024 EOL announcements**.
- **4 Mar 2025:** Alianza **completed** the acquisition. The combined base is over 1,000 CSPs, including 19 of the top 20 global operators. Metaswitch products are now sold as **"Alianza Core"**: MetaSphere CFS/EAS, QCall, Perimeta, MaX UC, Clearwater Core, Rhino TAS, MetaView, ServiceIQ and protocol stacks. Alianza states it will "actively support and continuously evolve these platforms."
- **Sept 2025 (NAVIGATE 2025):** Alianza CTO Dag Peak said operators "can sit on those platforms for many years to come," with feature, security and regulatory updates. Alianza announced three packaging tiers: **Core** (on-prem Metaswitch), **Fusion** (hybrid, Alianza-managed HA/DR, with Residential, Business and **iACD** editions) and **One** (fully cloud-native). It also announced an "Intelligent Communications Fabric" AI/orchestration layer targeted for 2026.
- **Net status (Oct 2026):** the platform is **not end-of-life** under Alianza. It is in maintenance plus selective enhancement, and Alianza clearly steers operators toward Fusion/One cloud migration. The **MaX UC client EOL** was announced by Microsoft. No firm, published end-of-support date was found after the Alianza takeover: Acrobits (2026) reports an informal 2029 sunset as unconfirmed, and NetSapiens (2026, a competitor) says Alianza sells MaX UC on subscription in its cloud. ECG says some Metaswitch products are EOL, some are in extended maintenance and some still get enhancements, without saying which is which.

---

## A. Per-user calling features

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Call Forward Always (Immediate / Unconditional) | Sends every call to another number. | *72 to activate, *73 to cancel ([SPK], [DPW]). It can be set to prompt for a number each time it is turned on. CommPortal Call Settings. Call Service Groups (V9.5.40+) can push a default to many lines. | [SPK], [MOM], [DPW] |
| Call Forward Busy | Forwards when the line is busy. | [SPK] uses *90/*91. [DPW] uses *68/*88. With twinned devices it applies only when all devices are busy or reject the call ([FC-CP]). | [SPK], [DPW], [FC-CP] |
| Call Forward No Answer (Delayed) | Forwards after a ring timeout. | [SPK] uses *92/*93. [DPW] uses *32/*82. Ring time is configurable in CommPortal. | [SPK], [DPW] |
| Call Forward Not Reachable / Forward If Unavailable | Forwards when the phone is offline (outage, power or internet loss). | No star code. Set in CommPortal (BCM "Forward If Unavailable"). It can be defaulted by a Call Service Group. | [SPK], [MOM] |
| Selective Call Forwarding | Forwards only callers on a list. | *63 to activate, *83 to deactivate, with voice prompts. CommPortal "Forward Selected" list. | [SPK], [DPW], [MOM] |
| Remote Access to Call Forwarding (RACF) | Change your forwarding from any phone. | Dial the local access number, then PIN, then *72/*73 ([DPW]). RACF is listed as a residential feature ([PSTN]). | [DPW], [PSTN] |
| Fixed call forwarding | Forwarding to a provider-set number that the user cannot change. | Listed as a CFS forwarding variant. | [PSTN] |
| Do Not Disturb | Calls go to voicemail and nothing rings. | *78 to turn on, *79 to turn off. A CommPortal Phone Status toggle. A priority/VIP caller list can still ring through (BCM). DND syncs both ways with Yealink phones (DND Key Synchronization). | [SPK], [DPW], [MOM], [YLK] |
| Anonymous Call Rejection | Rejects callers who block their caller ID. | *77 to turn on, *87 to turn off. In CommPortal, anonymous callers can be rejected without voicemail. | [SPK], [MOM] |
| Selective Call Rejection | Blocks callers on a list. | *60 to turn on, *80 to turn off. CommPortal "Reject Selected" / "Unwanted callers" list. The Rejected Calls list shows the rule that matched. | [SPK], [MOM] |
| Selective Call Acceptance | Only callers on an allow list ring through. | *95 to turn on, *96 to turn off. CommPortal Screening accept lists. | [SPK], [MOM] |
| Priority Call / Distinctive Ring | A special ring for chosen callers. | *61 to turn on, *81 to turn off. CommPortal "Distinctive Ringtone" per list. Distinctive ringing for internal vs external calls. Teen Line gives a distinctive ring per called number. | [SPK], [PSTN], [MOM] |
| Simultaneous Ring | Rings several phones at once. | Through Follow Me, by placing several destinations in Step 1 ([FC-CP]). Easy Call Manager "Available" profile. SIP Call Forking rings multiple SIP devices. | [FC-CP], [PSTN], [MOM] |
| Find-Me / Follow-Me (sequential ring) | Tries a list of numbers in order. | CFS Call Manager "Follow Me" supports up to **6 steps**. Destinations in the same step ring together, and ring duration is set per step. | [FC-CP], [MOM] |
| Incoming Call Manager (rule-based routing) | Time and caller rules that decide how calls are handled. | Up to **20 Sets of Rules**, with a Weekly Schedule and Special Days (automatic public holidays). Custom ringback audio can be recorded or uploaded. Variants are Business Call Manager (BCM), Easy Call Manager (ECM, with Available / DND / Forward All profiles) and ICM. | [MOM] |
| Call Waiting | A tone alerts you to a second call. | *70 disables it for one call. Available with or without caller ID (CIDCW). | [SPK], [PSTN] |
| Caller ID per-call blocking | Hides your number for one call. | *67 | [SPK] |
| Caller ID delivery permanent on/off | Default presentation of your number. | *65 to activate delivery, *85 to deactivate. CommPortal Call Settings can withhold caller ID. | [SPK], [FC-CP] |
| Calling Name (CNAM) delivery | Shows the caller's name. | Calling Name Delivery and blocking are CLASS features ([PSTN]). The name lookup itself comes from the operator's external CNAM provider **(inferred)**. | [PSTN] |
| Automatic Recall (*69) | Calls back the last caller. | *69. Two-stage variant: *69 then 1. *89 cancels all pending attempts. | [SPK] |
| Automatic Callback (last number redial / busy callback) | Redials the last number you called, or camps on a busy line. | *66 to activate, *86 to deactivate. | [SPK], [PSTN] |
| Customer Originated Trace | Flags the last call for law enforcement. | *57 | [SPK] |
| Speed Dialing | Short codes for frequently called numbers. | *74 for Speed Dial 8 (1-digit), *75 for Speed Dial 100 (2-digit). Also set in CommPortal (1-2 digit codes). | [SPK], [MOM] |
| Personal short codes | User-defined abbreviated dialing. | "Short codes (group and personal)". | [PSTN] |
| Three-way calling / ad hoc conference | Adds a third party to a call. | Three-way calling, with ringback, on analog lines. Phone Conf key on IP phones. | [PSTN], [DPW] |
| Hold / transfer (blind and announced) | Moves calls. | Xfer and Bxfer softkeys. Transfer to voicemail: Bxfer, then 7 + extension (prefix varies by operator). | [DPW] |
| Call Jump | Moves a live call to another of your devices. | [DPW]: *95 (alternate), *96 (wireless), ** (ring all / jump back). Premium users only. Configurable in CommPortal Call Settings with short codes. MaX UC push/pull is the client equivalent. | [DPW], [MOM] |
| Live voicemail screening | Listen while a caller leaves a message and pick up. | EAS Live Message Screening. Trusted subscribers get a distinctive ring. | [MSG], [MOM] |
| Reminder calls / wake-up | The system calls you with a reminder. | EAS Reminders: one-off, daily or weekly, with a recorded message. CFS Reminders: one-off within 24 hours, daily or weekly. | [MOM], [PSTN] |
| Hot line / warm line | Lifting the handset auto-dials a number, immediately or after a delay. | CFS residential feature. | [PSTN] |
| Call barring / toll restriction (per line) | Blocks outbound call types. | Toll restriction (residential). Call barring per line, with a Call Service Group default (V9.5.40). | [PSTN], [MOM] |
| Message Waiting Indicator | Lamp or stutter tone for new voicemail. | Audible and visual MWI on SIP and analog. The user picks which numbers get MWI. | [PSTN], [MOM] |
| Call logs (Missed / Dialed / Received / Rejected) | Per-user call history. | CommPortal lists with CSV export and device icons. Rejected calls show the matching rule. | [MOM] |
| Click-to-dial / "Make Call" / "Call Me" | Start a call from the web portal. | CommPortal rings your phone and then the destination. "Call Me" buttons. Also from Outlook via CommPortal Assistant. | [MOM], [ALW19], [MSG] |
| Off-premises extension (OPX) / home intercom | Remote extension or in-home intercom. | CFS residential and POTS features. | [PSTN] |

## B. Business Group features

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Business Group (hosted PBX / Centrex) | A customer's set of lines sharing a dial plan and admin. | Up to **40,000 lines**, **4,000 departments** and **10,000 Intercom Code Ranges** per Business Group. Clustered CFS supports 20,000 lines. Groups over 10,000 lines need a "Supports >10k lines" flag. | [MOM] |
| Extension (intercom) dialing | Short internal numbers. | Extensions and ranges, managed by the root BG Admin (search shows the first 1,000 matches). "Station-to-station intercom dialing". Flexible dial plan with 9+ or assume-9. | [MOM], [PSTN] |
| Departments | Sub-groups with their own admin and limits. | Hierarchical and nestable. Each has its own operator number and incoming/outgoing concurrent call limits. A department must be empty before deletion. | [MOM], [FL21], [ALS] |
| Multi-Line Hunt Group (MLHG) | Distributes calls to a group of lines. | Up to **1,000 per BG** (10 with Integrated ACD per [MOM]). A pilot number is built by the operator. Members can log in/out from CommPortal or a phone key. Options: hunt on direct-dialed calls, per-member ring time, exclusion time after a member fails to answer, maximum queue length, and pilot number/name as caller ID. Intercom calls and SIP-forked lines never hunt. | [MOM], [FL21], [BTC] |
| MLHG distribution algorithms | Order in which members ring. | **Linear** (default), **Circular**, **Uniform (Round Robin)**, **Uniform (Longest Idle)** (idle time counts all calls) and **Ring All**. | [G4-MLHG], [FL21], [BTC] |
| MLHG queueing / exit from queue | Callers wait when all members are busy. | The caller can press 0 to exit to voicemail or another number. Queued calls can time out. Unavailable call forwarding on the pilot handles the case when all members are logged out. | [BTC], [FC-ACD] |
| MADN (Multiple Appearance Directory Number) / Sim-Ring group / shared line | One number appears and rings on several phones. | Up to **1,000 per BG**. The call-limit algorithm is set by the operator. "Shared Line Appearance" is marketed. Lines can be shared across phones. | [MOM], [FL19], [ALS] |
| Call Pickup Group | Answer a colleague's ringing phone. | *11 for group pickup (you cannot choose which call when several are ringing). Groups are created, renamed and moved by the BG Admin. | [SPK], [DPW], [FL21] |
| Directed Call Pickup | Answer a specific extension's call. | [SPK]: *97 (no barge-in). [DPW]: *12 + extension. Yealink Directed Pickup key. | [SPK], [DPW], [YLK] |
| Call Park / Retrieve | Hold a call in an orbit for anyone to retrieve. | Codes vary by operator: [SPK] *68 park / *88 retrieve; [DPW] *53 park / *54 + orbit; [FC-CP] *14 + orbit. "Enhanced Call Park" keys target a specific orbit. Without a target, the server picks the first free orbit. The BLF LED flashes slowly for a parked call. | [SPK], [DPW], [FC-CP], [YLK] |
| Busy Lamp Field / Enhanced Monitored Extension | Phone keys showing colleagues' status. | LED states: idle (green), ringing (fast-flash red), busy or DND (red), parked (slow-flash red). The key can dial or pick up. | [YLK], [FL21], [FC-CP], [DPW] |
| Intercom / push-to-talk | Auto-answer voice to a colleague. | Phone-based Intercom/PTT keys to a preconfigured extension (Yealink). CFS "Intercom Code Ranges" define internal dialing. A dedicated auto-answer intercom star code was not confirmed **(inferred: mostly phone-side)**. | [YLK], [MOM] |
| Paging (multicast) | Broadcast audio to phone speakers. | Done on the phones over multicast (Polycom group paging, Cisco paging, address range 224.0.0.114-250). Single site only and produces no CDRs. Not a CFS server feature. | [ALS] |
| Supervisor monitor / whisper / barge (hunt group) | Listen to, coach or join agent calls. | *47 Hunt Group Monitor, *48 Whisper, *49 Barge-in ([SPK]). In Premium ACD, the supervisor can switch between Monitor, Whisper and Barge-In during the call. | [SPK], [FC-ACD] |
| Easy Attendant (basic auto attendant) | Simple IVR menu. | One menu, or business-hours plus after-hours menus. Actions: play announcement, transfer to phone or voicemail, dial by extension, dial by name. Business hours set by dragging on a weekly calendar. Special Days and public holidays. | [NOR], [ALS] |
| Premium Attendant (multi-level auto attendant) | Full IVR tree with schedules. | Expandable menus with submenus ("Go to Menu", "Return to Previous Menu"). Actions include transfer to phone or voicemail, dial-by-extension or name, voicemail-by-extension or name, self-care by extension, transfer to operator, intercept mailbox, replay, and hang up. Timeouts and error handling. Record announcements by browser, upload or phone with a PIN. The Service Status panel shows menu errors. Activation is blocked if the config is invalid. | [NOR], [G4-PA], [ALS] |
| Legacy auto attendant (menu tree) | Older EAS attendant. | Announcement IDs 100/101/102 (day, after-hours, holiday). Menus 10/11/12. Keys 0-9, * and #. Actions: Transfer, Menu, Menu-Back, Announce-Return, Announce-Release, Release, Directory. The "Layout Diagram" report shows menu usage counts. | [FL19] |
| Schedules / holidays / night service | Different routing by time of day. | Weekly schedule plus Special Days in Premium/Easy Attendant and Incoming Call Manager. Holidays override business hours. A standalone manual "night service" toggle key was not found **(inferred: done through the attendant schedule or Call Manager rules)**. | [NOR], [FL19], [MOM] |
| Dial-by-name directory | Callers spell a name. | In Easy and Premium Attendant (class-of-service controlled). Names are recorded per extension. "Directory Matching Method" setting. | [NOR], [FL19] |
| Music on Hold (N-Series MOH) | Audio for held callers. | Upload WAV or MP3. Per-line mappings with initial and follow-up resources. Actions: Repeat, Play Once, Repeat-Initial Interrupted, Repeat-Follow-up Interrupted. Start point (Start or Random). Gain -3 to +3. Admin phone access for recording. Storage is capped by plan. | [ALS], [FL19], [FL21] |
| Short codes (group abbreviated dialing) | Company-wide speed dials. | Up to **1,000** named codes and ranges (V9.5.30+). Bulk CSV import/export. Service access codes can start with * or #. | [MOM], [FL21] |
| Account codes | Codes entered for billing or tracking of call types. | Mandatory or optional, validated or not. Length 1-15. Lockout after 1-100 bad attempts. Per call type (international, local, premium, national, mobile, operator, carrier-dialed, within-BG, and so on). Per-line overrides. Emergency and toll-free calls are exempt. | [MOM], [ALS], [PSTN] |
| Call Service Groups | Templates of settings shared by lines. | V9.5.40+. Shared calling party number, unconditional and unavailable forwarding defaults, and call barring. A user override wins. | [MOM] |
| Operator / attendant number | The "0" destination. | Internal Operator Number at BG level, overridable per department. Used by the attendant "zero-out" and voicemail. | [FL21], [BTC] |
| Receptionist / attendant console (Voice Operator Panel) | PC switchboard for a receptionist. | Windows softphone or tethered to a desk phone. Drag-and-drop transfers, BLF-style presence, colour-coded call priority, call timers, recording, call stats. Directory from the BG, CommPortal, Outlook, LDAP and CSV. XMPP presence. Multi-language. Partner product (Joher). | [VOP] |
| Executive / assistant (boss-admin) | An assistant screens and handles a boss's calls. | No native boss-admin feature found in the docs opened. Typical approaches are shared lines (MADN), BLF and Voice Operator Panel **(inferred gap)**. | (none found) |
| Special intercept announcements / trunk routing | Routing for PBX trunks and DIDs. | Trunk Groups, Trunking Destinations and Trunk Routing Policies (priority and weight), SIP trunks and PRI to customer PBXs. | [MOM], [PSTN] |
| Internal vs external caller ID presentation | Different ID internally and externally. | "Caller ID presentation: internal and external". Distinctive ringing for internal vs external calls. | [PSTN] |
| Shared Call Appearance (SIP BLA) | Bridged line across phones. | Implemented through MADN and line-key locking on phones. RFC 7463-style bridged line was not confirmed **(inferred)**. | [YLK], [ALS] |

## C. Voicemail and messaging

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Voicemail (EAS) | Mailbox per line. | Access by *98 ([DPW]) or *62 (Voice Mail Activation, [SPK]). Auto play, PIN skip/fast login, mailbox lock, urgent and private flags. Multiple concurrent languages. | [MSG], [DPW], [SPK], [MOM] |
| Greetings | What callers hear. | Personal, System with name, System with number, System. Situational greetings: busy, after hours, same-BG caller, extended absence (can block messages). Temporary greeting override. | [MOM], [ALW-B] |
| Unified messaging | Voice and fax in one store, reachable by phone, web and email. | Outlook and Lotus Notes integration. Voicemail delivered to email with action links (login, mark read, delete). | [MSG], [MOM] |
| Voicemail to email / auto-forward | Get messages by email. | Autoforward voicemail and fax. Notification style: details+message, message only, or details only. | [MOM], [ALW19] |
| Voicemail transcription | Speech-to-text of messages. | Added in 2010 with Nuance. Optional per user. Delivered by SMS or email or shown in CommPortal and MaX UC. | [GNW-STT], [MOM], [MAXCL] |
| Visual voicemail | Browse messages in an app. | CommPortal Messages screen, MaX UC Voicemail tab, MCT Teams tab (playback speed, download). | [MOM], [G4-D], [MCT] |
| Video mail | Video messages. | Video messaging toggle in Message Settings. MaX UC plays voice and video mail. | [MOM], [MAXCL] |
| Deleted folder / restore | Recover deleted messages. | Shown if the CoS keeps a trash folder. | [MOM] |
| Notifications (MWI, email, pager, outdial) | Alerts on new messages. | MWI to chosen numbers. Email to several addresses. One pager (numeric or alpha). Outdial with schedule, delay, retries. Temporary override schedule. | [MOM] |
| Group mailboxes / distribution lists | Shared and family mailboxes, broadcast lists. | Group mailboxes (primary manages secondary), nested distribution lists, mailbox-to-mailbox messaging, sub-mailboxes, return receipts, direct deposit. | [MSG], [MOM] |
| Restricted subscriber messaging | Limit forwarding outside the company. | Blocks voicemail forwarding outside the BG. | [FL21] |
| Fax to email (inbound fax mailbox) | Receive faxes as email or in the portal. | Dedicated fax number. TIFF viewer. Fax forwarding to email or a fax machine. Faxes screen in CommPortal and MaX UC Mobile. | [MSG], [MOM], [G4-M] |
| Email to fax (outbound) | Send fax from email. | Not documented in the opened sources **(inferred: not native, done through partners)**. | (none) |
| Instant messaging / chat / group chat | IM between users. | MaX UC IM with emoji, files and group chat, synced across devices. XMPP via the Accession Messaging Service. Requires the IM-enabled version. | [G4-D], [G4-M], [NSP] |
| SMS / MMS | Business texting. | MaX UC SMS **requires a third-party SMPP provider**. No native 10DLC texting found. | [MAXCL] |
| "My Mobile" / Fuse My Mailbox | Mobile voicemail integration. | Text notifications, mobile call-forwarding setup, mobile voicemail. | [MOM] |

## D. Clients and mobility

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| CommPortal web portal | Browser self-care. | Call Manager, Messages, Contacts (up to 1,000, CSV import/export, groups), Call Lists, Settings, Phone Configurator, Groups (MLHG login). WebRTC browser calling (older browsers needed the Flash plug-in v10+). | [MOM] |
| CommPortal Assistant | Windows desktop helper. | Taskbar calling, incoming call popups, hourly Outlook contact sync, voicemail status. | [MOM], [MSG], [ALW19] |
| MaX UC Desktop (formerly Accession Communicator) | Softphone for Windows and Mac. | HD voice and video, hold, transfer, merge/3-way, conference manager, call recording from the call window, IM/group chat, presence (custom status up to 100 chars, Outlook "In a Meeting"), contacts from Outlook/Mac/CommPortal/directory, CRM lookup, visual voicemail with transcription. Windows 10/11, macOS 10.15+. | [G4-D], [MAXCL] |
| MaX UC Mobile | iOS and Android app. | VoIP over Wi-Fi or data, "switch to cellular", call pull, chat, voicemail and fax tabs, Call Manager (Available / DND / Forward all) synced across devices. | [G4-M], [MAXCL] |
| Native dialer / business identity | Use the phone's dialer with the business number. | The later MaX UC direction was a native dialer overlay, multiple identities, separation of business and personal identity, and onboarding by SMS, email or QR code. | [MAXDS], [MAXCL] |
| Call push / pull between devices | Move an active call. | "Single-button to push (switch) and pull active calls from twinned devices". "Call Available to Pull" banner. Twinning works with SIP, MGCP, GR-303 or SIP BLC desk lines. | [MAXCL], [G4-M] |
| Presence | See availability. | Online, Busy, DND, custom status. Automatic Away, In a call, In a Meeting and Offline. XMPP. | [G4-D], [VOP] |
| Fixed-mobile convergence | Desk number on mobile. | MaX UC twinning and Call Jump. Mobile Control Point (Rhino) is for **mobile operators** (Teams Operator Connect Mobile), not small telcos. | [MAXCL], [MCP], [DPW] |
| Hot desking | Log into any phone as yourself. | Not found in opened sources **(inferred: not a standard CFS feature)**. | (none) |
| Click-to-dial / browser and Outlook | Dial from a PC. | CommPortal, CommPortal Assistant, Outlook. MaX UC accepts tel: links. | [MSG], [MCT] |
| Desk phone apps | Portal features on the phone screen. | CommPortal Phone Applications on Yealink (guide exists). | [YLK-SOL] |

## E. Conferencing and collaboration

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Three-way / ad hoc conference | Join calls together. | Three-way calling. Merge in MaX UC. Phone Conf key. | [PSTN], [G4-D] |
| Meet-me audio bridge | Dial-in conference room with codes. | Historic UC9000 Conference Server (2007): reservation-less meet-me, up to 500 per call, web control, lock, roll call, mute, recording. [DPW] shows in-conference moderator DTMF commands (1-9, 01 greeting, * then 1 to leave). Whether current EAS deployments still offer it is operator-specific **(inferred)**. | [UC9000], [DPW] |
| Accession Meeting / MaX Meeting (video, web) | Video meetings and webinars. | **Powered by Zoom** (added Feb 2016, 50 attendees). Rooms grew to 4-200 participants and webinars to 10,000 attendees (2017). Screen and app sharing, remote control, whiteboard, recording, Outlook scheduling, Q&A, registration. FirstLight sold a 100-participant tier (2020). Licensed per user ("MaX Meeting Licenses" in BG Admin). | [MS-2016], [MS-2017], [SADDLE], [TC-FL], [MAXCL], [MOM] |
| Accession Rooms | Room video kits. | Certified off-the-shelf A/V equipment (2017). | [MS-2017] |

## F. Contact center

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Integrated ACD (iACD) basic | Queueing on a hunt group with supervisor stats. | Built on the MLHG. Supervisor Dashboard (Summary, Queues, Agents, Settings, Reports). Wallboard view. Queue stats refresh every 30 seconds. CSV downloads. | [FC-ACD], [ALS], [MOM] |
| Premium ACD | Full agent states and supervisor tools. | Agent states: Available, Wrap-up, Logged Out, Line Not Ready, DND, In a call, plus up to **30 custom unavailable reasons** per BG. Wrap-up timer. Up to **30 disposition codes** per queue (can be mandatory). Monitor, whisper and barge. ACD Report Scheduler (one-off to yearly, emailed). | [FC-ACD], [MOM] |
| Agent login/logout | Join or leave queues. | CommPortal, a phone access code, or the supervisor logs agents in or out. Simultaneous multi-queue login is optional. | [FC-ACD], [BTC] |
| Queue announcements | Position or comfort messages. | Queue status announcements "currently not supported" (FirstComm guide). The 2007 ACD release offered queue MOH/messages. | [FC-ACD], [ACD07] |
| Agent desktop / CRM / omnichannel | Agent tools beyond phones. | Not native. Partners such as Xima CCaaS integrate through SIP virtual handsets and the CommPortal API. | [XIMA] |
| Callback, skills routing, WFM | Advanced CC features. | Not found in Metaswitch docs **(inferred gap; done through partners)**. Alianza Fusion has an "iACD" edition. | [ALZ-CORE] |

## G. Dialing control and carrier/regulatory

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| External call limits / concurrency | Caps on simultaneous calls. | Per BG and department: incoming, outgoing or combined limits (Not Permitted / Unlimited / Limited). Trunk group call limits. | [ALS], [MOM] |
| Outgoing call barring / class of service | Block call types. | Toll restriction. Call barring per line or Call Service Group. "Outgoing Call Blocking" sold as a company-wide feature. | [PSTN], [MOM], [TRU] |
| Account codes | Forced codes per call type. | See section B. | [MOM] |
| Authorization codes / PIN override | Code to bypass restrictions. | Not found **(inferred: account codes used instead)**. | (none) |
| Carrier selection (PIC) | Choose long-distance carriers. | Local (PIC2), long distance (PIC1) and international (PIC3) per BG. | [ALS] |
| STIR/SHAKEN | Caller ID signing and verification. | MetaSphere QCall: signing and verification over HTTPS, SP-KMS and STI-CR, SIP proxy mode, up to 50,000 TPS, active-active geo-redundant. A hosted version (Call Guardian Authentication Hub with TNS) launched 9 Apr 2019. | [QCALL], [TNS] |
| Robocall analytics / blocking | Spam treatment. | TNS Call Guardian analytics (1B+ call events/day) applies validation treatment and universal blocking of illegal robocalls. Telemarketer Call Screening (legacy). | [TNS], [PSTN] |
| E911 | Emergency calling. | 911 dialing exempt from account codes. MaX UC prompts the user to update the registered location if it can't be determined, and warns that the operator "may not be able to identify where you are calling from". Kari's Law direct dial and notification, and RAY BAUM'S dispatchable location, were not documented in opened pages **(inferred: via operator ALI/partner)**. | [G4-D], [G4-M], [ALS] |
| Caller ID per group/line | Set the outbound number. | Calling Party Number per Trunk Group or Call Service Group. Pilot number as caller ID for MLHG. | [MOM], [BTC] |
| CNAM | Name display. | Calling Name Delivery (CLASS). See A. | [PSTN] |

## H. Recording, analytics and compliance

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Call recording (platform) | Record calls. | The BG Admin "Call Recording" section covers intra-Business Group recording and warning tones ([MOM]). MaX UC desktop records from the call window. Voice Operator Panel records. | [MOM], [G4-D], [VOP] |
| Partner recording (CallCabinet) | Cloud recording with AI. | Metaswitch-certified. NNI connection to the CallCabinet cloud (SIPREC for on-prem). Transcription, sentiment, PCI redaction, GDPR/HIPAA/MiFID compliance. | [CCAB] |
| Call Reports / Call Analytics | Business call reporting. | Licensed. Account Statistics, Call Duration Summary, Call Log, Frequent Caller / Frequently Called, Location Analysis, Long Ringing Time, Missed Calls Summary and Detail. Download-only permission level. | [MOM] |
| Call logs (CDR export) | Raw call records. | CSV by date range (up to 30 days, [ALS]) and department. Types: Originating, Terminating, Intra-BG. | [FL19], [ALS] |
| ACD reports | Queue and agent metrics. | Waiting time, abandon rate, alerting time. Scheduled emailed reports. | [ALS], [FC-ACD] |
| Network assurance / analytics (operator) | Operator-side troubleshooting. | Service Assurance Server (call traces, robocall traceback). ServiceIQ. | [QCALL], [ALZ-CORE] |
| AI transcription / summaries | AI on calls. | Only voicemail speech-to-text is native. Alianza "Intelligent Communications Fabric" AI layer is targeted for 2026. | [NSP], [FIERCE-25] |

## I. Integrations and APIs

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| Microsoft Teams Direct Routing | Use the operator's PSTN in Teams. | Perimeta SBC is a certified Direct Routing SBC, on-prem or in Azure. 50+ operators by Feb 2021. | [MS-TEAMS] |
| MaX UC Connector for Teams (MCT) | Use the hosted PBX line inside Teams. | A Teams app. Click-to-dial (rings your phone first) or direct MaX UC calling (desktop v3.01+). CommPortal, BG and Teams contacts. Call history. Voicemail tab with transcription. Call Manager status (BCM/ECM). Azure-hosted and brandable. | [MCT], [MAXDS] |
| Teams Operator Connect Mobile | Teams on the mobile native dialer. | Mobile Control Point on Rhino, for mobile operators. | [MCP] |
| Outlook | Contacts, calendar, click-to-dial. | Two-way Outlook sync. Outlook presence ("In a Meeting"). Accession Meeting scheduling. | [MSG], [G4-D], [SADDLE] |
| CRM | Screen pop and lookup. | MaX UC "UC trigger" CRM lookup (products not named). The Voice Operator Panel has CRM and email integration. | [MAXCL], [G4-D], [VOP] |
| LDAP / directory | Corporate directory. | The Voice Operator Panel supports LDAP. MaX UC uses the BG corporate directory. | [VOP], [G4-D] |
| Provisioning APIs (operator) | OSS/BSS automation. | MetaSphere EAS / CommPortal Web Services (Sh-style ShPull/ShUpdate) used by billing systems (IDI) for lines, BGs, number blocks, managed devices and features. The "ShadowConfig" SOAP data model is used by integrators **(name inferred; not seen in opened pages)**. | [IDI] |
| CommPortal API (JSON) | Third-party apps acting as a subscriber. | Used by Xima (CommPortal login URL, version, subscriber number and EAS password). | [XIMA] |
| Developer ecosystem | Public APIs and webhooks. | No public developer portal. APIs gated by license and partner status. No webhooks, live call control or mobile SDK, according to a competitor (NetSapiens) analysis. | [NSP] |
| SSO / SAML | Single sign-on. | Not found **(inferred gap)**. | (none) |

## J. Administration, provisioning and platform

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| BG Admin portal (CommPortal) | Customer admin. | Lines (Users, Attendants, Trunking Users, Group Access), Phones, Departments, Hunt and Sim-Ring and Pickup groups, Short/Account codes, Extensions, Call Reports, Call Recording, MOH, Auto Attendant, MaX Meeting licenses. Root vs department admins. Admin can log in as a user. | [MOM], [ALS] |
| Line reset / unlock | Re-use a seat. | Reset deletes all data and makes new credentials. Unlock after lockout. | [MOM], [FL21] |
| Password/PIN policy | Security. | Expiry, lockout and validity set by Class of Service. | [MOM] |
| Operator portal: MetaView Web | Service provider provisioning. | Create subscribers and BGs, MLHGs, PRIs, MGCP/SIP bindings. SIP device config through the SIP Provisioning Server. CSR "view as subscriber". | [MVW] |
| Multi-tenant / reseller hierarchy | Delegated management. | Delegated Management Groups limit resellers to their own subscribers. User classes: Global Supervisor, Global CSR, Delegated Group Supervisor, Delegated Group CSR, Phone Reseller. | [MVW] |
| Phone auto-provisioning / Phone Configurator | Zero-touch phone setup. | MetaView SIP Provisioning Server plus the CommPortal Phone Configurator. Endpoint Pack firmware (Yealink T2x-T5x, CP, W-series DECT, VP59, and others). Polycom, Cisco and Joher endpoints. DHCP opt 66 or Yealink RPS. MAC or digest auth. Phone profiles by type, inherited by sub-departments. Scheduled reboots 2-6 AM. | [YLK], [YLK-SOL], [ALS], [FL21], [VOP] |
| Bulk CSV | Mass changes. | Short codes CSV import/export. Lines list CSV download. Contacts CSV. | [MOM] |
| HA / deployment | Resilience. | Clustered CFS. Virtualized on COTS or private cloud (VMware/OpenStack). QCall active-active geo-redundant. Alianza Fusion adds Alianza-managed HA/DR. | [ALZ-CFS], [QCALL], [FIERCE-25] |
| Self-subscribe services | Users add features. | "Add Services" in CommPortal (not for BG lines). | [MOM] |
| White-label / branding | Operator brand. | Branded CommPortal, MaX UC (fully branded clients), MCT tailored branding, Voice Operator Panel branding package. | [MAXDS], [MCT], [VOP] |
| Billing integration | Rating and OSS. | Through third-party billing (IDI), CFS customer-info fields, service suspend. | [IDI] |
| Analog / TDM / legacy access | Non-SIP lines. | GR-303, MGCP/NCS, ISDN PRI, T1 CAS, analog ATA. A strength for rural ILEC POTS replacement. | [PSTN], [MVW] |

## K. Vertical / specialty

| Feature | Plain explanation | Metaswitch details | Source |
|---|---|---|---|
| IPTV caller ID screen pop | Caller ID on the TV. | Through IPTV middleware. | [PSTN] |
| Wake-up / reminder calls | Scheduled calls. | EAS and CFS reminders (see A). Hospitality PMS integration not found **(inferred gap)**. | [MOM] |
| Teen line / family line | Residential multi-person. | Distinctive ring per number. Family/communal mailboxes. | [PSTN], [MSG] |
| Paging and door phones | Overhead and entry. | Phone-side multicast paging only. Door phones as SIP endpoints **(inferred)**. | [ALS] |
| Mass notification / education / healthcare | Specialty. | Not found **(inferred gap)**. | (none) |

---

## Metaswitch distinctive strengths and weaknesses

**Strengths**
1. **A single carrier-grade Class 5 platform for both POTS and hosted PBX.** The same CFS serves analog/GR-303/MGCP residential lines, SIP trunks, PRI and hosted business. That is why rural ILECs and cable MSOs standardized on it.
2. **A very deep CLASS / residential feature set** with standard star codes (*69, *57, *60/*80, *61/*81, RACF, teen line, hot line, reminders).
3. **Mature Business Group model at very large scale.** Up to 40,000 lines and 4,000 departments per BG, five MLHG algorithms, MADN, account codes with lockout, department call limits, and delegated reseller management in MetaView.
4. **Strong unified messaging heritage.** Voice and fax store, group mailboxes, live screening, transcription since 2010, and Outlook sync.
5. **Robust carrier-side regulatory tooling.** QCall STIR/SHAKEN (50k TPS, hosted option with TNS), and the Perimeta SBC certified for Teams Direct Routing.
6. **White-label everything.** CommPortal, MaX UC, MCT and the operator console are all brandable, and the operator keeps the customer relationship.
7. **Now owned by a voice-focused company (Alianza) that publicly commits to multi-year support**, with a hybrid migration path (Fusion).

**Weaknesses**
1. **Ownership churn and roadmap uncertainty.** Microsoft (2020), then the MaX UC EOL notice and layoffs (2024), then Alianza (2025). Alianza steers operators toward Fusion/One cloud. The MaX UC client future is the biggest open question.
2. **Contact center is thin.** iACD/Premium ACD covers agent states, wrap-up, dispositions and monitor/whisper/barge, but has no queue position announcements (per FirstComm), callback, skills routing, omnichannel or WFM. Partners (Xima) fill the gap.
3. **Collaboration is outsourced.** Meetings were powered by Zoom. IM runs on XMPP. SMS needs a third-party SMPP provider. There is no native business texting or team messaging comparable to modern UCaaS.
4. **Missing modern PBX features** in the opened docs: native executive/assistant, hot desking, a night-service toggle key, server-side paging, email-to-fax, SSO.
5. **Closed developer story.** No public API portal or webhooks. APIs are license- and partner-gated (competitor claim). Provisioning is SOAP/Sh-style through MetaView/EAS.
6. **Inconsistent feature codes across operators.** Each operator defines its own codes (call park is *68, *53 or *14 depending on the carrier), so documentation is fragmented.
7. **The UI and admin experience show their age.** Flash dependency in older CommPortal releases. Many settings (new MLHGs, MADNs, number blocks, external call limits) are read-only to customers and need an operator ticket.

---

## Sources (opened)

- [FIERCE-24] https://www.fierce-network.com/cloud/exclusive-alianza-buys-metaswitch-microsoft-deal-years-making
- [FIERCE-25] https://www.fierce-network.com/cloud/alianzas-metaswitch-assets-arent-going-anywhere
- [ALZ-CLOSE] https://www.alianza.com/whats-new/alianza-completes-acquisition-of-metaswitch-from-microsoft/
- [ALZ-CORE] https://www.alianza.com/products/alianza-core/ (redirect from https://info.alianza.com/metaswitch-products)
- [ALZ-CFS] https://www.alianza.com/products/metasphere-cfs-eas/
- [ALZ-MAX] https://www.alianza.com/products/max-uc/
- [ALZ-EOL] https://www.alianza.com/blog/navigating-the-end-of-metaswitch-and-determining-the-best-path-forward/
- [ALZ-MAXEOL] https://www.alianza.com/blog/threat-level-rising-microsoft-to-sunset-maxuc/
- [ECG] https://www.ecg.co/blog/alianza-metaswitch-future
- [ECG-CORE] https://www.ecg.co/technologies/metaswitch-alianza-core
- [ACRO] https://acrobits.net/blog/tech/alianza-acquired-metaswitch-what-operators-need-to-know/
- [ACRO2] https://acrobits.net/blog/tech/maxuc-eol-3-paths-for-csps/
- [NSP] https://www.netsapiens.com/metaswitch-innovation-gap-compare/ (competitor marketing)
- [UCT] https://uctoday.com/big-uc-news-from-mitel-alianza-metaswitch-microsoft-and-zoom
- [WIKI] https://en.wikipedia.org/wiki/Metaswitch
- [SPK] https://business.sparklight.com/support/downloads/7671/Metaswitch%20Star%20Code%20v2.pdf
- [MOM] https://info.momentumtelecom.com/rs/476-ZWP-927/images/CNG%20MaX%20CommPortal%20UG.pdf
- [PSTN] https://info.metaswitch.com/hs-fs/hub/415294/file-1797470435-pdf/PDFs/Metaswitch-Metasphere-PSTN-Emulation-Services.pdf
- [MSG] https://info.metaswitch.com/hs-fs/hub/415294/file-1793957173-pdf/PDFs/Metaswitch-Metasphere-Messaging.pdf
- [MVW] https://info.metaswitch.com/hs-fs/hub/415294/file-1797386956-pdf/PDFs/Metaswitch-Metaview-Web.pdf
- [MAXDS] https://info.metaswitch.com/hubfs/pdfs/metaswitch-datasheet-max-uc.pdf
- [MAXCL] https://info.metaswitch.com/hubfs/pdfs/metaswitch-datasheet-max-uc-client.pdf
- [QCALL] https://info.metaswitch.com/hubfs/PDFs/metaswitch-datasheet-metasphere-qcall.pdf
- [VOP] https://info.metaswitch.com/hubfs/PDFs/metaswitch-datasheet-voice-operator-panel.pdf
- [TNS] https://www.metaswitch.com/about/press-releases/tns-and-metaswitch-announce-immediate-availability-of-hosted-robocall-blocking-service-based-on-stir-shaken
- [MS-TEAMS] https://www.metaswitch.com/about/press-releases/metaswitch-announces-more-than-fifty-operator-customers-now-delivering-direct-routing-for-microsoft-teams-with-perimeta-sbc
- [MS-2017] https://www.metaswitch.com/about/press-releases/metaswitch-accession-continues-its-ascent-further-enhancing-ucc-scalability-cost-efficiency-and-user-experience
- [MS-2016] https://www.metaswitch.com/the-switch/metaswitch-adds-web-and-video-conferencing-to-accession-unified-communications-suite
- [UC9000] https://www.metaswitch.com/about/press-releases/metaswitch-unveils-uc9000-conference-server-to-streamline-conference-call-set-up-management-and-control
- [MCP] https://www.metaswitch.com/knowledge-center/datasheets/mobile-control-point-datasheet and https://metaswitch.com/solutions/mobile-control-point
- [ACD07] https://convergedigest.com/metaswitch-enhances-automated-call/
- [GNW-STT] https://www.globenewswire.com/news-release/2010/06/22/1325696/0/en/Metaswitch-Enhances-Unified-Messaging-Portfolio-With-Speech-to-Text.html?print=1
- [NOR] https://norvado.com/wp-content/uploads/2021/06/Easy-and-Premium-Attendant-Guides.pdf
- [G4-PA] https://www.grid4.com/?p=2842
- [G4-MLHG] https://www.grid4.com/?p=2834
- [G4-D] https://www.grid4.com/wp-content/uploads/2023/05/MaX-UC-Desktop-User-Guide.pdf
- [G4-M] https://www.grid4.com/wp-content/uploads/2023/05/MaX-UC-Mobile-User-Guide.pdf
- [BTC] https://btcbroadband.com/multi-line-hunt-groups-setup.pdf
- [FL19] https://www.firstlight.net/wp-content/uploads/2019/08/CommPortal-Admin-User-Guide.pdf
- [FL21] https://www.firstlight.net/wp-content/uploads/2021/05/13-CommPortal-Admin-Guide.pdf
- [FC-ACD] https://www.firstcomm.com/wp-content/uploads/2019/12/Integrated-ACD-Admin-Guide.pdf
- [FC-CP] https://www.firstcomm.com/wp-content/uploads/2021/01/User-Guide-CommPortal.pdf
- [ALS] https://support.allstream.com/wp-content/uploads/2023/01/USER-GUIDE-Hosted-Voice-Service-Admin.pdf
- [DPW] https://kb.depauw.edu/wp-content/uploads/2017/01/HPBX-End-User-Guide-2.1.pdf
- [ALW19] https://www.allwest.com/wp-content/uploads/2022/12/MetaSwitch-CommPortal-User-Training_update-2019.pdf
- [ALW-B] https://blog.allwest.com/three-call-settings-in-commportal-that-you-may-not-know-about
- [MCT] https://saddlebackcomm.com/wp-content/uploads/2023/04/QRG_MCT_Unbranded.pdf
- [SADDLE] https://saddlebackcomm.com/press-release/saddleback-integrates-advanced-collaboration-tools-with-cloud-uc-solutions/
- [TC-FL] https://www.telecompetitor.com/firstlight-launches-two-new-cloud-based-offerings/
- [YLK] https://www.yealink.com/upfiles/products/meta/Yealink-Metaswitch-Configuring-Guide.pdf
- [YLK-SOL] https://www.yealink.com/en/solution-detail/metaswitch
- [IDI] https://help.idibilling.com/docs/provisioning-metaswitch-specifications-and-actions
- [XIMA] https://guide.xima.cloud/docs/metaswitch-target-platform
- [CCAB] https://www.callcabinet.com/?p=10004
- [TRU] https://www.truvista.net/images/truvista/pdf/voice/business/ip_pbx.pdf (generic hosted PBX list; Metaswitch not named, used only as corroboration)
- Opened but not cited because they are not Metaswitch-specific or did not confirm the platform: efis.psc.mo.gov Document 31032 (Chariton Valley, no platform named), atlantech.net Hosted_License_Types, gpcom.com UC-Phone-Feature-Codes, r1tel.com star-codes, dobson.net call recording QSG, popp.com call recording guide, tpx.com ?p=11025, northland.net Meet-Me manual, nojitter.com/node/17216. Not retrievable (blocked): docplayer "Metaswitch Hosted IP PBX Feature Guide V7.2" and mcg.squarespace.com "Hosted PBX End User Guide V9.6.10".
