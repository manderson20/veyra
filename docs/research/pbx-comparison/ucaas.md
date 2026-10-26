# Hosted / cloud UCaaS phone systems: feature research (as of Oct 2026)

Scope: RingCentral RingEX (RC), Microsoft Teams Phone (Teams), Zoom Phone (Zoom), Cisco Webex Calling incl. carrier BroadWorks / Webex Wholesale (Webex), 8x8 X Series / 8x8 Work (8x8), GoTo Connect (GoTo), Dialpad (Dialpad), Vonage Business Communications (Vonage), Nextiva (Nextiva), NetSapiens / Crexendo NetSapiens Platform (NS).

Conventions:
- Source keys `[Sn]` refer to the numbered list in **Sources** at the end. Every URL there was opened during this research.
- `(inferred)` = the platform attribution or detail was not confirmed on a page I opened. It is based on general product knowledge or indirect evidence. Verify it before relying on it.
- Leaving a platform out of the "Which have it" column means I did not find evidence for it. It does **not** prove the platform lacks the feature. Long-standing PBX basics (hold, transfer, forwarding, voicemail) are near-universal and are marked "all" where that is reasonable.
- Pricing comes mostly from third-party 2026 pricing roundups. Many are written by competitors (CloudTalk, Ringly, Grasshopper), so treat the numbers as ballpark figures only.

---

## Platform summaries

**RingCentral RingEX (RC).** RingEX (formerly RingCentral MVP) is RingCentral's UCaaS bundle: phone, SMS, fax, team messaging and video. It suits SMBs through enterprise, and it has the most "SMB-polished" AI add-ons. The current tiers are **Core about $20/$30**, **Advanced about $25/$35** and **Ultra** (about $35/$45, inferred), shown as annual/monthly prices per user per month. RingCentral now also sells "AI Customer Engagement" bundles that include the **AI Receptionist (AIR)** [S9][S13]. AIR costs $39/month as a RingEX add-on (100 minutes included, then about $0.50/min) or $49 standalone. More than 11,800 businesses used it as of May 2026 [S11]. Licensing is per named user, plus add-ons: Call Queues Booster $35, Business SMS Booster $25, Conversational Intelligence from $60/user. The contact center (RingCX) is licensed separately per agent ($65–$145) [S9]. The legacy Essentials/Standard/Premium/Ultimate tier sheet [S10] still shows which features sit at which level. For example, hot desking, SSO, multi-site, and monitor/whisper/barge are in the upper tiers.

**Microsoft Teams Phone (Teams).** Teams Phone is a cloud PBX add-on to Microsoft 365/Teams. It suits organizations already on M365, including schools via A3/A5 and the GCC/GCC High/DoD government clouds. **Teams Phone Standard is about $10/user/month** and is included in E5/A5. PSTN is bought separately: a Microsoft Calling Plan (about $8–15), Operator Connect, Direct Routing via your own SBC, or Teams Phone Mobile [S7][S1]. **Resource Account licenses** (free) are needed for auto attendants and call queues. **Teams Premium** (about $10) is needed for the Queues app, which adds supervisor monitor/whisper/barge and real-time queue stats [S2]. Copilot (an M365 Copilot license) adds AI call recap and Q&A [S4]. Licensing is per user, with a separate PSTN entitlement. The ecosystem includes certified SIP phones, Teams Rooms, and contact center integrations.

**Zoom Phone (Zoom).** Zoom Phone is a cloud PBX inside Zoom Workplace. It suits SMB through enterprise customers, especially existing Zoom Meetings shops. Prices per user per month (annual billing) are **US/CA Metered $10.50**, **Unlimited $16**, **Pro Plus bundle $20.50** and **Business Plus $24.50** [S16]. There is also a Zoom Phone "Pro" license with no DID, used for BYOC, and a "Global Select" plan covering about 40+ countries [S19]. The **Power Pack / Customer Engagement Pack** add-on (about $25) adds wallboards, the call handling panel, Team SMS and VIP delegation [S16][S14][S17]. AI Companion (summaries, voicemail prioritization) is included on paid plans. The **Zoom Virtual Agent** AI receptionist for Phone was announced in August 2025 [S18][S15]. Zoom also offers Local Survivability via a Zoom Node [S14].

**Cisco Webex Calling / BroadWorks (Webex).** Webex Calling is Cisco's multi-tenant cloud calling service. It is built on the **BroadWorks** feature set and sold direct, through partners, and wholesale to carriers ("Webex Wholesale RTM"). Carriers also run BroadWorks on-premises as their own hosted PBX, which is the direct Metaswitch/NetSapiens competitor for telcos. The BroadWorks lineage brings the classic telco feature list: executive/assistant, hoteling, remote office, Office Anywhere, sequential/simultaneous ring, selective acceptance/rejection, and intercept [S23]. Pricing: Calling Professional is about **$17/user/month** with Suite, or around $14.50–$23 standalone. Common Area and Workspace licenses are cheaper, and there is a **no-cost hot-desk-only license** [S25][S26][S22]. Wholesale packages are Common Area, Standard, Enhanced, Webex Calling, **Customer Assist** (queue/supervisor tools), and Suite. They are billed per user per month, aimed at end customers of 500 users or fewer [S24]. The 2026 AI features are **AI Receptionist** (GA June 2026; $100 per 250-minute bundle per instance) [S28], plus AI Assistant in calls, the Translator Agent, and AI Agent Studio [S27].

**8x8 X Series / 8x8 Work (8x8).** 8x8's UCaaS and CCaaS share one platform ("8x8 Platform for CX"), aimed at mid-market and enterprise. **X2 is about $24–28** and **X4 is about $44–57** per user per month. X6–X8 are contact center tiers at roughly $85–$140+ per agent [S30]. Pricing is now mostly by quote. X4 adds the Frontdesk receptionist console, monitor/whisper/barge, and supervisor analytics. Hot desking needs a "Lobby" add-on license [S29][S31]. In July 2026 8x8 announced 8x8 Resolve (emergency/incident alerting to frontline workers), AI Routing, AI Studio (agent builder) and a Synthflow voice-AI integration [S32].

**GoTo Connect (GoTo).** GoTo Connect is the former Jive cloud PBX, sold by GoTo (formerly LogMeIn). It targets SMB and mid-market and is strong with its visual dial-plan editor and multi-site setups. Plans are **Phone System about $26**, **Connect CX about $34** and **Contact Center about $80** per user per month [S34]. Teams integration, Attendant Console, Business Continuity and reporting are add-ons [S34]. The **AI Receptionist** launched in March 2025 (quote-based, per-minute or 3,000-minute bundles) [S36]. GoTo also offers AI call summary, sentiment/topic detection, and an admin AI ("GoPilot") [S35].

**Dialpad (Dialpad).** Dialpad is an AI-native cloud phone and contact center with its own speech recognition. It suits SMB/mid-market sales and support teams. Plans are **Connect Standard $15**, **Connect Pro $25** and Enterprise (by quote). Sell runs $39–79 and Support $89–149 per user per month [S37]. Real-time transcripts and **AI Recaps** are included even on Connect [S38]. Licensing is per user. The **Dialpad AI Agent (Resolve)** is priced per conversation through AI agent credits [S37].

**Vonage Business Communications (Vonage).** Vonage Business Communications (VBC) is Vonage's SMB UCaaS. Vonage is owned by Ericsson, and its contact center product is sold separately as VCC. The tiers are **Mobile, Premium and Advanced**. The getvoip listing shows about $12.59–$26.59 per user per month for 10 users on annual billing [S40]. The fitsmallbusiness listing shows $19.99, $29.99 and $39.99 with a 1-year contract [S41]. Many features are a-la-carte add-ons ($4.99–$49.99/month), including call queue, paging group, call recording, voicemail transcription and CRM integrations [S41][S40]. The **AI Virtual Assistant** (conversational IVR) is quote-based [S40].

**Nextiva (Nextiva).** Nextiva is a US SMB/mid-market UCaaS/CX platform. It is historically BroadWorks-based (inferred). It has moved toward a "unified customer experience" platform with the **XBert AI agent**. Plans are **Core $15**, **Engage $25**, **Scale/Power Suite CX $75** per user per month, and the contact center starts at $75/agent. "AI plans" (unlimited calling plus XBert) start at **$99/month** [S45][S44]. Nextiva offers HIPAA voice/fax with a BAA and an embedded Microsoft Teams dialer [S46].

**NetSapiens (NS).** NetSapiens is a white-label, multi-tenant, carrier-grade UCaaS software platform, owned by Crexendo since 2022. It is licensed to service providers (telcos, MSPs, ITSPs), who resell it under their own brand. It competes with BroadWorks and Metaswitch for small telcos. Its licensing is distinctive: "Never Pay Per Seat Again." Providers buy outright or subscribe, and **call center features are included in the core license** [S47]. End-user prices are set by each reseller. The platform provides SNAPmobile (mobile, web and desktop apps), SNAP.HD video, SNAPanalytics, the SNAPbuilder phone-key designer, and the **CAIRO AI Receptionist**. AI services are pluggable from Deepgram, AWS, Google, Azure and IBM [S47][S48][S53]. Providers also get an "iNSight" monitoring tier [S47].

---

## A. Per-user calling features

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Do Not Disturb (DND) | Stops your phone ringing and sends callers to voicemail. | All | Zoom/Teams tie DND to presence status; 8x8 suppresses notifications when DND is set [S29]; NS has DND in answering rules | [S23][S29][S48][S33] |
| Call forwarding (always/busy/no answer/unreachable) | Sends calls elsewhere under conditions you choose. | All | NS "forward when offline"; BroadWorks "Business Continuity (CFNR)" forwards when the device is unregistered | [S23][S48][S1][S14] |
| Selective call forwarding / acceptance / rejection | Applies rules by caller, time or number to decide which calls ring, forward or get rejected. | Webex, NS (allowed/blocked numbers), Teams (presence-based routing), Zoom (inferred) | BroadWorks has separate Selective Accept, Selective Reject and Selective Forward services | [S23][S48][S1] |
| Simultaneous ring | Rings your desk phone, apps and cell phone at the same time. | RC, Teams, Zoom, Webex, 8x8 (inferred), GoTo, Dialpad, Vonage (inferred), Nextiva (inferred), NS | Teams and NS support *delayed* simultaneous ring | [S1][S23][S33][S38][S48] |
| Sequential ring / find-me-follow-me | Tries your devices or numbers one after another. | Webex, GoTo ("Find Me/Follow Me"), RC (inferred), Zoom (inferred), NS (linear answering rules) | | [S23][S33] |
| Remote office / Office Anywhere | Lets you use any phone (home or cell) as if it were your office extension, including outbound caller ID. | Webex | BroadWorks "Remote Office" and "Office Anywhere" | [S23] |
| Anonymous call rejection | Blocks callers who hide their caller ID. | Webex, NS | | [S23][S48] |
| Priority / distinctive ring | Uses a different ringtone for certain callers, forwarded calls, or alternate numbers. | Webex (priority alert, alternate numbers with distinctive ring), Teams (distinctive ring for forwarded/delegated calls) | | [S23][S1] |
| Call waiting | Lets you receive a second call while on one. | All | Webex allows up to 4 calls; Teams "Busy on Busy" policy can turn it off | [S23][S1][S33] |
| Busy-on-busy | Rejects or redirects a new call when you are already on a call. | Teams, NS (call waiting toggle) (inferred) | Admin-controlled policy in Teams | [S1] |
| Per-call / permanent caller-ID blocking | Hides your number on outbound calls. | Webex, NS, Vonage ("block caller ID") | | [S23][S48][S41] |
| Call return / last-number redial | Calls back the last caller or redials the last number. | Webex, GoTo | | [S23][S33] |
| Speed dial | Short codes or keys for frequent numbers. | Webex (100), GoTo, NS (SNAPbuilder keys), Zoom (Assistant) | | [S23][S33][S49][S17] |
| Three-way / N-way calling | Merges calls into a small conference. | All | Webex N-way up to 6 parties; NS N-way | [S23][S48][S29] |
| Hold / transfer (blind, attended, to voicemail) | Basic call handling, including sending a call straight into someone's voicemail. | All | RC and NS transfer directly to voicemail [S8][S48]; Teams "transfer to voicemail mid-call" | [S8][S1][S14][S48] |
| Call screening / announce | Asks callers to state their name before you accept. | Vonage (call screening, call announce), NS, GoTo, Webex (selective screening with Mutare, Sept 2026) | Webex screening can apply to reception desks and queues | [S41][S48][S33][S22] |
| Personal block list | Lets users block specific numbers themselves. | Teams, Zoom, 8x8, Vonage, NS, GoTo | Teams blocking requires the Phone license | [S1][S14][S29][S41][S48] |
| Caller ID name (CNAM) display and directory lookup | Shows the caller's name, enriched from internal directories and contacts. | Teams (directory photo/title), Webex (caller name resolution from org contacts, Sept 2026), RC, NS (CNAM add-on) | Webex uses AI caller-name resolution | [S1][S22][S8][S48] |
| Multiple numbers per user / multi-line | Gives one person several numbers or lines (for example a private line). | Teams (Multi-line, Private Line), Webex (alternate numbers, multiple line appearance), Zoom (shared lines), NS (alternate numbers) | Teams Private Line is inbound-only and hidden from the directory | [S1][S23][S48] |
| Outbound caller-ID selection | Lets you choose which number shows when you call out (personal, department, main). | RC, Zoom, Dialpad, GoTo ("Dynamic Caller ID", "Caller ID swap"), NS, Teams (Shared Calling / resource account) | | [S8][S17][S38][S33][S48][S3] |
| Voice message reply / reply-with-text | Sends an automated text-to-speech or SMS reply when you can't answer. | RC, 8x8 (end call with predefined text) | | [S8][S29] |
| Push-to-talk / walkie-talkie | Instant one-to-one or group voice without dialing. | Zoom, Webex, RC (Frontline add-on $5/license) | | [S15][S23][S8] |
| Unassigned-number routing | Plays an announcement or redirects calls to numbers not assigned to anyone. | Teams, Webex (intercept user/group) | | [S1][S23] |
| Video calling (point-to-point) | One-to-one video calls from the phone client. | Teams, Zoom, Webex, RC, 8x8, NS | | [S1][S23][S48] |
| Time tracking / client codes per call | Tags calls to clients for billing by call duration. | Zoom, NS (account codes) | Useful for law and accounting firms | [S14][S48] |

## B. Business group features

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Auto attendant / IVR | A menu that answers ("press 1 for…") and routes calls. | All | Multi-level menus; RC has a visual IVR editor; NS supports dial-by-name, multi-language, and speech recognition for menus; Zoom offers follow-the-sun routing | [S1][S8][S14][S48][S33] |
| Visual call-flow / dial-plan editor | Lets you design routing by drag-and-drop instead of forms. | GoTo, RC (IVR editor), NS (inferred, via reseller portals) | GoTo's is a signature feature | [S33][S8] |
| Hunt / ring groups | Rings a group of phones together or in order. | All | Teams "Call Groups" (personal); Dialpad "Departments" with longest-idle, round-robin and fixed-order routing [S38]; NS ring-all, linear hunt and linear cascade | [S1][S38][S48][S29][S33] |
| Call queues (basic ACD) | Holds callers with music and hands them to the next free agent. | All (Vonage as an add-on) | RC "Call Queues Booster" add-on; Teams allows 200 agents per queue | [S1][S8][S41][S48][S2] |
| Queue callback (keep your place) | Offers callers a callback instead of waiting on hold. | Teams (since late 2024), 8x8 (queued and web callback, CC tiers), GoTo (Contact Center plan), Dialpad (Support), NS (overflow "Call Back"), Nextiva (Contact Center), RC (RingCX) (inferred) | Teams triggers on wait time, number of callers waiting, or the caller/agent ratio | [S6][S29][S34][S38][S48][S46] |
| Queue overflow / thresholds | Sends callers elsewhere when the wait or the queue gets too long. | Teams, Zoom, NS, Dialpad | NS settings: maximum expected wait, maximum queue length, agent ring timeout | [S14][S48][S38] |
| Call park and retrieve | Parks a call in a "slot" so anyone can pick it up from another phone. | All | Teams parks with a code; Vonage has *103/*104 plus a "Visual Call Park" dashboard; RC parks in public or private locations; NS has Parktrieve plus static park BLF; Webex park groups with authentication | [S1][S42][S8][S48][S23][S14] |
| Call pickup (group / directed) | Answers a colleague's ringing phone from yours. | Webex (directed, and directed with barge), NS (directed, group, site, domain), GoTo, Teams (group pickup on common area phones) | | [S23][S48][S33][S4] |
| Intercom | Talks directly through a colleague's speakerphone. | RC, GoTo, NS, Webex (inferred) | | [S8][S33][S48] |
| Paging (phone and overhead) | Broadcasts an announcement to a group of phones or overhead speakers. | RC, GoTo, Webex (group paging), NS (handset and overhead), 8x8 (Polycom only), Vonage (paging group add-on) | Teams has no native group paging (inferred; typically done with third-party devices) | [S8][S33][S23][S48][S29][S41] |
| Busy lamp field (BLF) | Desk phone keys that light up to show colleagues' line status. | Webex, 8x8 ("Power keys"), GoTo, NS (also queue-status and day/night-mode BLF), Zoom (inferred), RC (inferred) | NS SNAPbuilder lets users design their own phone keys | [S23][S29][S33][S48][S49] |
| Shared call appearance / shared line | One number appears on several phones, and anyone can answer or pick up from hold. | RC, Zoom (shared lines and shared line groups), Webex, GoTo, NS, Teams (delegation / shared line appearance), Vonage (secondary line appearance add-on) | Webex Standard package omits SCA [S24] | [S8][S14][S23][S33][S48][S1][S40] |
| Executive–assistant (boss/admin) | An assistant screens, answers and places calls for an executive. | Webex (Executive/Executive assistant), Teams (call delegation), Zoom (delegation up to 15 delegates, Zoom Assistant), RC (heads-up display / delegation), Dialpad (inferred) | Zoom offers VIP delegation and business-hours override [S17] | [S23][S1][S17][S8] |
| Barge-in / whisper / silent monitor / takeover | Lets a supervisor listen, coach privately, join or take over a call. | RC (upper tiers), Teams (Queues app with Premium), Zoom, Webex (Customer Assist), 8x8 (X4+), GoTo (Contact Center), Dialpad (Support/Sell), NS, Vonage (VCC only) | NS includes it in the core license | [S10][S2][S14][S24][S29][S34][S38][S48][S41] |
| Night service / time-of-day / holiday routing | Routes calls differently after hours and on holidays. | All | NS "Time Frames" with a phone-key toggle; Dialpad holiday hours; Zoom global routing | [S48][S49][S38][S14] |
| Manual call-flow toggle (day/night key) | A button or code that flips the system into "closed" or "emergency" mode. | NS (Timeframe Toggle key, day/night BLF), Webex (inferred, BroadWorks "Night service"), RC (inferred) | Handy for schools on snow days | [S49][S48] |
| Music / message on hold | Plays custom audio while callers wait. | All | Teams supports streaming audio | [S1][S8][S29][S33] |
| Dial-by-name directory | Lets callers spell a name to reach someone. | GoTo, NS, Teams (inferred), Webex (inferred) | | [S33][S48] |
| Attendant / receptionist console | A desktop screen for front-desk staff with drag-and-drop transfers and presence of everyone. | 8x8 (Frontdesk, X4+), Webex (Attendant Console add-on), GoTo (Attendant Console add-on), Zoom (Call Handling Panel in CE Pack), NS (attendant console via partners), Teams (third-party) | | [S29][S24][S34][S14][S30] |
| Multi-site extension dialing | Lets staff dial short extensions across buildings or sites. | RC (up to 8-digit extensions with site codes), Webex (variable-length), GoTo (multi-site), Dialpad (multi-office) | | [S10][S23][S33][S37] |
| Hot desking / hoteling | Lets a user log into any shared phone and get their own extension. | RC (Premium/Ultimate tiers), Webex (hoteling host/guest; free hot-desk license), 8x8 (Lobby add-on), GoTo, Zoom (appliances), NS, Teams (common area / hot-desk on Teams phones) (inferred) | Webex 2026: "Webex profiles" bundle lines and keys for hot-desk users | [S10][S22][S23][S31][S33][S48] |
| Common-area / lobby phone licensing | A cheap license for hallway, classroom, lobby or elevator phones. | Teams (common area phones; shared device license), Webex (Common Area Calling, Workspace), Zoom (common area phones), 8x8 (Lobby license) | Very relevant to schools (classroom phones) | [S1][S4][S24][S17][S31] |
| Hotline / ring-down phone | Picking up the handset automatically dials a set number. | Teams (pre-configured hotlines), Webex (inferred, BroadWorks "Automatic Hold/Retrieve, Hotline") | | [S4] |
| Shared voicemail / group mailbox | A voicemail box shared by a team or queue. | RC, Zoom (shared line groups), Teams (shared voicemail for call queues), NS (voicemail distribution lists) | | [S8][S14][S48] |
| Shared phone number for many users (Shared Calling) | Many users make and receive calls using one main number, with no DID each. | Teams (Shared Calling), Zoom (Pro license without DID), Dialpad (Departments), NS | Lowers number costs for schools and small offices | [S3][S19][S38] |
| Federated calling across tenants | Calls other organizations on the same platform directly over IP. | Teams, Zoom (inferred) | | [S1] |

## C. Voicemail and messaging

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Voicemail with custom greetings | Basic voicemail. | All | Teams out-of-office greetings; Webex "voicemail protection" stops lockouts | [S1][S22] |
| Voicemail to email | Sends voicemails to email as an attachment. | All | Teams stores voicemail in the Exchange mailbox | [S1][S8][S38][S48] |
| Visual voicemail | Lists voicemails in the app to play in any order. | RC, Webex, GoTo, Vonage (Advanced plan), Zoom, 8x8, NS (SNAPmobile) | | [S10][S23][S33][S41][S50] |
| Voicemail transcription | Converts voicemail to text. | All (Vonage as an add-on) | NS uses Google/Deepgram engines | [S8][S16][S29][S38][S41][S44][S47] |
| AI voicemail prioritization / to-tasks | AI ranks voicemails by urgency and pulls out tasks. | Zoom (ZoomMate / AI Companion) | | [S15] |
| Voicemail drop | Leaves a pre-recorded message on a prospect's voicemail with one click. | Dialpad (Reach Booster) | Sales-oriented | [S38] |
| Internet fax (fax-to-email / email-to-fax) | Sends and receives faxes without a fax machine. | RC (Advanced+), Zoom (50 pages to unlimited), Webex (inbound fax to email; T.38), 8x8, GoTo, Dialpad (add-on), Vonage (US fax number add-on), Nextiva (incl. HIPAA fax), NS (Faxback/Pangea add-on) | | [S9][S15][S23][S29][S33][S38][S41][S46][S48] |
| Business SMS / MMS | Texts customers from a business number. | RC, Zoom, Teams (Calling Plan US/CA only), GoTo, Dialpad, Vonage, Nextiva, NS, 8x8 (CC tiers; UC inferred), Webex (Text Queues 2026) | Message quotas vary (RC Core 25, Advanced 100; Nextiva 100–500) | [S1][S9][S15][S33][S38][S41][S44][S48][S22] |
| 10DLC / TCR registration support | Registers your business texting campaign so carriers don't block your messages (a US requirement). | RC (required; in-portal TCR) and effectively all US SMS providers (inferred) | | [S12] |
| Team / shared SMS inbox | Several staff answer texts to one shared number. | Zoom (Team SMS, CE Pack), RC (Business SMS Booster / shared inbox with AIR), Webex (Text Queues with shared inbox, June 2026), NS (SMS queuing), Vonage (Business number inbox) | | [S14][S11][S22][S48][S41] |
| AI summaries of SMS threads | AI summarizes long text conversations. | Zoom | | [S15] |
| Team chat / IM | Instant messaging between staff. | All | Teams and Zoom are full chat platforms; 8x8 has threaded messaging | [S29][S8][S48] |
| WhatsApp / social messaging channels | Handles WhatsApp, Facebook and Instagram messages alongside calls. | GoTo (Connect CX), RC (AIR via WhatsApp), 8x8 (CC), Nextiva, Vonage (Facebook) | | [S34][S11][S29][S45][S41] |
| AI message drafting / translation | AI writes or translates chat replies. | RC (AI Assistant), Webex (AI Assistant), GoTo (AI Messaging Assistant) | | [S13][S24][S35] |
| Protected voicemail | Restricted-access voicemail that can't be forwarded. | Teams | | [S4] |

## D. Clients and mobility

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Desktop softphone app | Lets you make and receive calls on a PC or Mac. | All | 8x8 is Citrix-certified; Teams supports VDI | [S29][S2] |
| Mobile app (iOS/Android) | Your business extension on your cell phone. | All | NS SNAPmobile can place calls over the cellular voice path where data is weak | [S50][S8] |
| Web / browser client | Calls from a browser with no install. | RC, Teams, 8x8, NS (SNAPmobile Web / WebPhone), Zoom (web app), Dialpad, GoTo (inferred) | | [S29][S48][S16] |
| Call flip / pull / move between devices | Moves a live call from desk phone to mobile (or back) without hanging up. | RC (Call Flip), Teams (transfer to another device), 8x8 (Flip calls), GoTo (Call Flip), Vonage (Call Flip), NS (Move Call key, switch phones) | | [S8][S1][S29][S33][S41][S49][S50] |
| Elevate call to video meeting | Turns a phone call into a video meeting in one click. | Zoom, RC, Webex (inferred), Teams (inferred) | | [S14][S8] |
| Presence | Shows whether colleagues are available, busy or on a call. | All | Teams presence-based routing; NS "unified presence" | [S1][S8][S14][S48] |
| Click-to-dial / browser extension | Click any phone number on a web page or CRM to call it. | 8x8 (Chrome dialer, highlight-to-dial), Zoom, RC, Vonage, Webex (call logs with click to dial) | | [S29][S41][S23] |
| Single number reach / mobility | Rings your cell phone as part of your business line and keeps your business caller ID when calling out. | Webex (Mobility), RC, NS (native dialer with no app; eSIM dual-number), Teams (Teams Phone Mobile, inferred) | NS global eSIM puts two numbers on one device | [S23][S47] |
| Native-dialer / eSIM business number | A business number on the phone's built-in dialer through a carrier eSIM. | NS | | [S47] |
| Desk phone breadth / BYOD phones | Supports many third-party SIP phones. | RC, Zoom (Poly, Yealink, Mitel), Webex (Cisco plus third-party; virtual lines on third-party phones 2026), 8x8 (Poly, Cisco, Yealink), NS (400+ endpoints), Dialpad, Vonage | Teams requires Teams-certified phones or the SIP Gateway | [S8][S15][S22][S31][S47][S41] |
| Analog / ATA devices | Connects fax machines, door phones and elevator phones via adapters. | Teams (SIP Gateway with AudioCodes/Cisco/Poly ATAs), Webex, NS (inferred), RC (inferred) | | [S4] |
| Wireless / DECT and frontline devices | Wireless handsets for staff on the move. | Webex (Cisco 9821 wireless phone, 2026), Teams (shared Android devices), RC (Frontline walkie-talkie) | | [S22][S4][S8] |
| Driving mode / CarPlay / Siri | Hands-free use while driving. | 8x8 (driving mode in meetings), Vonage (Siri integration) | | [S29][S41] |
| Call quality indicator | An in-app sign that your network is poor. | 8x8, Zoom (quality dashboards) | | [S29][S14] |
| Noise suppression / voice isolation | Removes background noise or other voices. | Teams (voice isolation), RC (RingSense noise reduction) | | [S4][S8] |

## E. Conferencing and collaboration

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Audio conference bridge | A dial-in conference number with PINs. | RC (up to 1,000), Vonage ($14.99 add-on, 30 participants), NS (dedicated or owned bridges with leader PIN), Zoom, Teams, 8x8, Nextiva, GoTo | | [S8][S41][S48] |
| Video meetings | Full video conferencing. | RC, Teams, Zoom, Webex, 8x8 (500 / 10k), GoTo (250), Dialpad, Vonage, Nextiva (250), NS (SNAP.HD / Video AI Studio) | | [S10][S29][S34][S46][S53] |
| Screen share | Shares your screen during a call or meeting. | All with video | | [S29][S41] |
| AI meeting summaries / notes | AI writes meeting notes and action items. | RC, Teams (Copilot), Zoom, Webex, 8x8 (post-meeting insights), GoTo, Dialpad, Nextiva (inferred), NS (Video AI Studio "AI companion") | | [S8][S24][S29][S34][S53] |
| Webinars / live streaming | Large broadcast events. | Zoom (add-on), 8x8 (live streaming), NS (YouTube streaming) | | [S14][S29][S53] |
| Whiteboards / document sharing | Collaborative canvases and file sharing. | RC, Vonage, Zoom (Miro), Nextiva (Cospace) | | [S10][S41][S33][S46] |

## F. Contact center

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Agent states / queue login-logout | Agents sign into and out of queues and set statuses (available, wrap-up). | Teams (opt in/out via Queues app), NS (custom statuses, queue login/logout keys), Dialpad, 8x8, Zoom, Webex (Customer Assist), GoTo | | [S2][S48][S49][S51][S38] |
| Wrap-up time | Gives agents breathing time between calls. | NS, Dialpad (Support) | | [S48][S38] |
| Real-time wallboards / dashboards | A live display of calls waiting, wait times and agent states. | Zoom (CE Pack), Teams (Queues app), 8x8, Nextiva, NS (SNAPanalytics wallboards), RC (real-time analytics), Dialpad, GoTo, Webex (Customer Assist) | | [S14][S2][S29][S46][S48][S10][S38] |
| Historical queue reporting | Reports on calls answered, abandoned, average wait and so on. | All (tiered) | Teams keeps 45 days in the Queues app; NS has cradle-to-grave reporting | [S2][S48][S52] |
| Skills-based routing | Sends callers to the agent with the right skill or language. | 8x8 (CC), Dialpad (Support), Nextiva (CC), RC (RingCX), GoTo (CC, inferred) | 8x8 AI auto-builds skills from transcripts (2026) | [S29][S38][S45][S32] |
| Omnichannel (chat, email, social) | One agent desk for voice, chat, email and social. | 8x8 (X7/X8), Dialpad (Support), Nextiva, RC (RingCX), GoTo (Connect CX/CC), Vonage (VCC), Webex (Webex CC; Text Queues in Calling) | | [S29][S38][S45][S34][S22] |
| Outbound / power / predictive dialer | Automatically dials lists of numbers for agents. | Zoom (Auto Dialer), Dialpad (Power Dialer), 8x8 (preview/predictive AI dialer), GoTo (CC auto-dialer), Nextiva (inferred) | | [S15][S38][S29][S34] |
| Screen pop / call pop | Shows the caller's CRM record when the phone rings. | Nextiva (Call Pop with sentiment/CSAT), Zoom (Salesforce), Webex (Customer Assist), Vonage (VCC), 8x8 | | [S46][S14][S24][S40] |
| Post-call surveys / CSAT | Automated surveys after a call. | 8x8 (CC), Vonage (VCC), Nextiva (CSAT/NPS), Dialpad (AI CSAT predicted with no survey) | Dialpad infers CSAT from the transcript | [S29][S40][S45][S38] |
| Workforce management (WFM) | Forecasting and agent scheduling. | Dialpad (Support Premium), 8x8 (add-on), Nextiva, Vonage (VCC), RC (RingCX) (inferred) | | [S37][S29][S45][S40][S32] |
| Quality management / AI scorecards | Scores calls against criteria, increasingly by AI. | Dialpad (AI Scorecards, Playbooks), 8x8 (QM, Conversation IQ), RC (ACE), Vonage (Conversation Analyzer, VCC), GoTo (AI QM, inferred) | | [S38][S29][S9][S43] |
| Real-time agent assist / live coach | AI prompts agents during a call with answers or battle cards. | Dialpad (Live Coach), Nextiva (Agent Assist / Autopilot), Webex (Suggested Responses, Q3 2026), Zoom (real-time answers), 8x8 (inferred) | | [S38][S45][S27][S15] |
| Queue priority / VIP routing | Lets important callers skip ahead. | Dialpad, Zoom (VIP delegation), NS (queue priority) | | [S38][S17][S48] |
| Call dispositions | Agents tag the outcome of each call. | NS, Dialpad | | [S48][S51][S38] |
| SMS / text queues | Routes incoming texts to agents like calls. | NS (SMS queuing), Webex (Text Queues), Zoom (Team SMS) | | [S48][S22][S14] |
| "Lite" CC inside UCaaS | Queue-agent and supervisor tools without buying a full contact center. | Webex (Customer Assist), Zoom (CE Pack), Teams (Queues app / Premium), RC (Call Queues Booster), NS (included in core) | Good fit for school front offices and town halls | [S24][S14][S2][S9][S47] |
| Contact center integrations (third-party) | Plugs in Five9, Twilio Flex, Dynamics 365 and others. | Zoom (Five9, Twilio Flex), Teams (Teams Phone extensibility / D365), NS (Xima CCaaS for SNAPmobile) | | [S14][S1][S51] |

## G. Dialing control and carrier / regulatory

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Class of service / call restrictions | Controls who can call international, premium or long-distance numbers. | Teams (dial plans, calling policies), Zoom (calling permissions), NS (dial permissions, extension forbid list), Webex (inferred, outgoing calling plans), RC (inferred) | | [S1][S15][S48] |
| Account codes | Users enter a code to tag calls for billing. | NS, Zoom (client codes) | | [S48][S14] |
| Authorization codes / PINs | A PIN is required to make certain calls. | NS, Webex (inferred) | | [S48] |
| E911 basic (registered address) | Sends a registered address to 911. | All | | [S1][S8][S14][S29][S33][S48] |
| Dynamic / nomadic E911 (RAY BAUM'S dispatchable location) | Detects the user's current location (network, Wi-Fi, IP) and sends it to 911. | Teams (dynamic emergency calling), Zoom (Nomadic E911), RC (nomadic location), NS (Enhanced E911, re-prompts WebPhone users on IP change), Webex (RedSky / Intrado ERS) | Webex added Intrado ERS in July 2026 | [S3][S21][S8][S52][S22] |
| Kari's Law internal notification | Alerts security or the front office when someone dials 911. | Teams (event notifications), Zoom (safety-team chat and voice alerts; digital-signage alerting), NS (automated actions) | Critical for schools and municipalities | [S1][S20][S52] |
| Emergency calling while logged out / locked | 911 still works on a logged-out hot-desk phone or a locked phone. | 8x8 (uses the physical location of the hot-desk phone), Zoom (IP phone screen lock keeps 911) | | [S31][S20] |
| STIR/SHAKEN attestation | Signs outbound calls so your caller ID is trusted. | RC, Dialpad (verified check mark on inbound), NS, and likely all US providers (inferred) | | [S8][S39][S48] |
| Inbound spam / robocall labeling and blocking | Flags "spam likely" calls or blocks them automatically. | Teams (spam likely label), Zoom (spam detection, route to voicemail or block), RC (AI/ML robocall blocking with traceback) | Webex adds Pindrop deepfake/synthetic voice detection (2026) | [S5][S20][S8][S27] |
| Deepfake / synthetic voice detection | Detects AI-cloned voices used for fraud. | Webex (with Pindrop) | Emerging | [S27] |
| Number porting | Brings your existing numbers over. | All | | [S8][S14][S29][S33] |
| Toll-free / vanity / international numbers | Toll-free and out-of-country numbers. | All (RC numbers in 110 countries; Zoom PSTN in 50+ countries) | | [S8][S19][S33] |
| BYOC / Direct Routing (bring your own carrier) | Keeps your current SIP carrier but uses the cloud PBX. | Teams (Direct Routing / Operator Connect), Zoom (BYOC, Provider Exchange), RC (BYOC), Webex (Local Gateway), GoTo (inferred) | Lets schools keep e-Rate or consortium trunks (inferred) | [S1][S14][S8] |
| Toll-fraud protection | Detects and blocks fraudulent call patterns. | NS (call limits, reject log, IPAware IP blocking, dictionary-attack prevention), RC (inferred) | | [S48][S47] |
| Local presence dialing | Shows a local area-code number to the person you are calling. | Dialpad (Reach Booster) | | [S38] |
| Caller ID per user / group / department | Sets which number shows for each user or group. | All | | [S8][S38][S48][S33] |

## H. Recording, analytics and compliance

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| On-demand call recording | A user presses record during a call. | All (Vonage Advanced or add-on; RC Core) | | [S9][S41][S38] |
| Automatic / policy call recording | Records all or selected calls automatically. | RC (Advanced+), Zoom, Webex (selective recording by direction/source, 2026), 8x8, Dialpad (Sell; Departments on Pro), NS, GoTo, Teams (compliance recording via certified partners, inferred) | | [S9][S14][S22][S29][S38][S48] |
| Recording pause / redaction (PCI) | Pauses or removes card numbers from recordings. | NS (mid-call recording redaction), Dialpad (PII redaction), Webex (pause recordings), 8x8 (Secure Pay), Zoom (PCIPal) | | [S48][S37][S22][S29][S15] |
| Recording announcement controls | Chooses who hears the "this call is recorded" tone. | Webex (Aug 2026) | | [S22] |
| Recording retention tiers | Sets how long recordings are kept. | 8x8 (30 days on X2 vs 130 days on X4), Dialpad (1, 3 or 7 years), RC (Ultra unlimited) | | [S29][S38][S10] |
| CDR / call logs | Itemized call history for every call. | All | NS CDR export via portal; 8x8 unreturned-calls report | [S48][S29] |
| Reporting dashboards / analytics | Usage reports and charts. | All | RC Business Analytics Essentials and Pro; Nextiva voice analytics; Zoom advanced analytics; NS SNAPanalytics custom dashboards | [S9][S44][S14][S48] |
| Cradle-to-grave call tracing | Follows one call through every transfer and hop. | NS, 8x8 (graphical call-flow reports, CC) | | [S52][S29] |
| Call-quality (MOS) monitoring | Reports on jitter, packet loss and voice quality. | RC (QoS reports), Zoom (quality dashboards), 8x8 (call quality report), NS (QoS monitoring, iNSight), Webex (AI Canvas with ThousandEyes/Meraki) | | [S10][S14][S29][S48][S27] |
| Device status reports and alerts | Alerts when phones go offline. | RC (Ultra), 8x8 | | [S10][S29] |
| Live call transcription / captions | On-screen captions during calls. | Dialpad (all plans), Webex (Sept 2025), RC (RingSense), Nextiva, Teams (inferred), Zoom (inferred) | | [S38][S22][S8][S45] |
| AI post-call summary and action items | AI writes a summary of every call. | Dialpad (AI Recap), Zoom (AI Companion), RC (AI Assistant), Webex (AI Assistant), Teams (Copilot), GoTo, Nextiva, NS (inferred, via AI vendors) | Webex shares AI summaries with the next person on transfer | [S38][S15][S9][S27][S4][S35][S45] |
| In-call AI Q&A ("ask AI") | Lets you ask AI questions about the call while it is happening. | Webex (Ask AI), Zoom (real-time answers), Teams (Copilot) | | [S22][S15][S4] |
| Caller intent preview | AI predicts why someone is calling before you answer. | Webex (Sept 2026) | | [S22][S27] |
| Sentiment analysis | AI scores how positive or negative the caller is. | Dialpad (live), GoTo, RC (RingSense / ACE), Nextiva, NS (speech analytics add-on), Vonage (VCC), Webex (Q3 2026) | | [S38][S35][S8][S45][S48][S43][S27] |
| Topic / keyword detection | AI flags topics or keywords mentioned in calls. | GoTo (topic flags), RC (RingSense keywords), Webex (topic analytics), Dialpad (Custom Moments) | | [S35][S8][S27][S38] |
| Conversation intelligence for sales | Deal and call scoring and coaching. | RC (ACE / RingSense for Sales), Zoom (Revenue Accelerator), Dialpad (Sell), 8x8 (Pulse) | | [S9][S15][S37][S32] |
| Compliance certifications (HIPAA, FedRAMP and others) | Third-party security and compliance attestations. | RC (HIPAA, HITRUST, PCI), 8x8 (HIPAA, FISMA, ISO 27001), Nextiva (HIPAA with BAA), Webex (FedRAMP), Teams (GCC High / DoD) | | [S13][S29][S46][S27][S1] |
| Archiving / DLP export | Pushes communications to archivers (Smarsh and others). | RC (Archiver; Smarsh integration), Zoom (archival/DLP APIs), 8x8 | | [S8][S10][S15] |
| Audit trail | Logs who changed what in the admin portal. | RC, NS (inferred) | | [S8] |

## I. Integrations and APIs

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| CRM integration (Salesforce, HubSpot, Zendesk and others) | Logs calls and offers click-to-call in your CRM. | All (tier-dependent) | Vonage $4.99/month per integration; RC Advanced+; Dialpad Pro+ | [S9][S14][S29][S38][S41][S45] |
| Microsoft Teams calling integration | Uses this provider's phone service from inside Teams. | RC (no Teams Phone license needed), Zoom, Webex, 8x8 (Voice for MS Teams), GoTo (add-on), Nextiva (embedded dialer), NS (AI voice services in Teams), Dialpad (inferred), Vonage (inferred) | Lets M365 schools avoid Teams Phone licenses | [S8][S15][S23][S29][S34][S46][S47] |
| Google Workspace / Microsoft 365 / Outlook | Calendar, contacts and presence sync. | RC, 8x8, GoTo, Zoom, Nextiva | | [S8][S29][S33][S45] |
| Slack integration | Places calls from Slack. | Zoom, 8x8, RC (inferred) | | [S14][S29] |
| Education vertical integrations (Canvas and others) | Connects to the school's learning management system. | RC (Canvas) | | [S10] |
| Healthcare EHR integrations | Connects to Epic, ModMed and similar systems. | Nextiva | | [S45] |
| E-commerce / scheduling for AI agents | Lets the AI agent check orders or book appointments. | RC AIR (Shopify, Calendly, WhatsApp), GoTo AIR (CRM sync), 8x8 AI Studio (11 connectors) | | [S11][S36][S32] |
| REST APIs / SDKs | Programmatic control and custom apps. | All | RC 500+ APIs; NS API-first CRUD on every object | [S8][S48][S15] |
| Webhooks / event subscriptions | Pushes call events to your systems. | RC, Zoom, Dialpad, NS (all inferred; not verified this round) | | (inferred) |
| SSO (SAML / OIDC) | Sign in with Entra ID, Okta or Google. | RC (Advanced/Premium+), Zoom (Business Plus), 8x8, Dialpad (Enterprise), GoTo, NS (incl. Apple SSO), Teams (native Entra) | | [S10][S16][S29][S37][S33][S48] |
| Directory sync (AD / LDAP / SCIM) | Imports users automatically from the directory. | 8x8 (AD authentication), Teams (native), RC / Zoom (inferred SCIM) | | [S29] |
| App marketplace | A store of third-party add-ons. | RC (330+ integrations), Vonage (App Center), 8x8 (App Store, 2026), NS (400+ integrations) | | [S13][S41][S32][S47] |

## J. Administration, provisioning and platform

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| End-user self-service portal | Users change their own forwarding, greetings and settings. | All | Webex user web portal; NS answering rules in the portal | [S23][S48] |
| Delegated / scoped admin | Lets local leads manage their own queues or sites. | Teams (Queues app authorized users), NS (site manager scope, reseller and domain scopes), RC (custom roles) | | [S2][S48][S13] |
| AI admin assistant | Natural-language administration and troubleshooting. | GoTo (Admin GoPilot), Webex (AI Canvas) | | [S35][S27] |
| Multi-site management | Manages several buildings or sites centrally. | RC, GoTo, Dialpad (Pro), 8x8, NS (sites) | | [S10][S33][S37][S48] |
| Zero-touch phone provisioning | Phones configure themselves when plugged in. | GoTo, Zoom, Webex, NS (geography-based, mass resync), 8x8, RC | | [S33][S14][S48] |
| Bulk import / bulk edit | Changes many users at once (CSV or templates). | Zoom (templates, CSV), NS (bulk edit), Teams (PowerShell) | | [S20][S48][S3] |
| Survivability / local failover | Keeps calling working if the internet or cloud goes down. | Zoom (Local Survivability via Zoom Node), Webex (site survivability), GoTo (Business Continuity add-on), RC (inferred) | | [S14][S27][S34] |
| Geo-redundancy / 99.999% SLA | Multiple data centers with uptime guarantees. | RC, Zoom, 8x8 (35 regions), GoTo, Vonage, Webex, NS (geo-distributed HA) | | [S8][S15][S29][S41][S27][S54] |
| Data residency options | Keeps data in your country. | Webex (US, CA, EU, AU, SA, IN; JP/UK coming), 8x8 (inferred) | | [S27] |
| Multi-tenancy and white-label reseller hierarchy | One platform runs many customers under a reseller brand. | NS (core design), Webex (Wholesale / BroadWorks), 8x8 / RC (partner programs; RC white-label through carriers, inferred) | NS reseller-managed branding without NMS access (v42) | [S47][S24][S52] |
| Masquerade / support impersonation | Admins log in as a user to troubleshoot. | NS | | [S48] |
| SIP trace / diagnostics | Packet-level call debugging. | NS, 8x8 (network diagnostics) | | [S48][S29] |
| MFA / password security | Strong sign-in protection. | All (NS: MFA, reCAPTCHA, forced reset) | | [S48] |
| Encryption (TLS / SRTP / E2E) | Encrypts signaling and voice. | All (RC TLS+SRTP; 8x8 optional FIPS 140-2; GoTo end-to-end) | | [S8][S29][S33] |
| Information barriers / ethical walls | Blocks certain groups from communicating. | Zoom (Business Plus) | | [S15] |
| Hardware rental / purchase | Phones leased from the provider. | RC, GoTo, Vonage | | [S10][S33][S41] |
| Licensing model | How you pay. | Per user: RC, Teams, Zoom, Webex, 8x8, GoTo, Dialpad, Vonage, Nextiva. Per instance: NS (no per-seat fees) | AI receptionists are usually metered by minutes or conversations | [S47][S28][S37] |

## K. Vertical / specialty

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Education fit (classroom and common area phones) | Cheap shared-device licenses plus LMS integration. | Teams (A-SKUs, common area), Webex (Common Area / Workspace), RC (Canvas), Zoom | (inferred mapping to education) | [S1][S24][S10] |
| Emergency / mass notification | Alerts groups of people (lockdown, critical incident). | 8x8 (Resolve, July 2026), Zoom (safety-team 911 alerts and digital signage), Teams (911 notifications) | Third-party tools like Singlewire are common (inferred) | [S32][S20][S1] |
| Door phones / elevator phones | Connects door intercoms and elevator phones. | Teams (SIP Gateway ATAs for door openers and elevators), Webex (Common Area), NS / RC (SIP devices, inferred) | | [S4][S24] |
| Healthcare (HIPAA voice/fax, EHR) | Compliant voice and fax for clinics. | Nextiva (BAA, HIPAA fax, Epic), RC (HIPAA), 8x8 (HIPAA), Zoom (healthcare) | | [S46][S45][S13][S29][S15] |
| Hospitality (PMS, wake-up calls) | Hotel features. | Webex / BroadWorks and NS (inferred; not verified this round) | Generally weak in mainstream UCaaS | |
| Frontline / retail walkie-talkie | Push-to-talk for frontline staff. | RC (Frontline Workers), Zoom (PTT), Webex (PTT) | | [S8][S15][S23] |
| Secure payments in call | Takes card payments via IVR without agents hearing the numbers. | 8x8 (Secure Pay), Zoom (PCIPal), Nextiva (IVR card collection) | | [S29][S15][S46] |
| Real-time speech translation | Translates calls between languages live. | Webex (Translator Agent, Q3 2026), RC (live in-app translation, 18 languages) | Useful for multilingual school families and city services | [S27][S8] |
| Multi-language IVR | Phone menus in several languages. | RC, NS, Nextiva (120+ languages with conversational AI) | | [S8][S48][S46] |

## AI agents / receptionist (cross-cutting, the biggest 2024–2026 gap vs. Asterisk)

| Feature | Plain explanation | Which have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| AI receptionist (front-door voice agent) | A natural-language AI answers the main line, answers FAQs from a knowledge base, and routes or books. | RC (AIR, $39–49/mo + $0.50/min), Zoom (Virtual Agent for Phone, Aug 2025), Webex (AI Receptionist GA June 2026, $100/250 min), GoTo (AI Receptionist, Mar 2025), Nextiva (XBert), Dialpad (AI Agent / Resolve), Vonage (AI Virtual Assistant, quote), NS (CAIRO AI Receptionist), 8x8 (ICA voice / AI Studio) | Languages: RC 10, Zoom 6, GoTo 10+; NS lets providers choose the AI engine | [S11][S18][S28][S36][S45][S37][S40][S47][S29] |
| AI agent in queues (overflow) | AI answers when agents are busy or after hours. | RC (AIR in call queues, 2026), NS (after-hours/overflow), Nextiva | | [S11][S47][S45] |
| AI agent builder (custom multi-step agents) | Build your own voice or digital AI agents that act in back-end systems. | Webex (AI Agent Studio, H2 2026), 8x8 (AI Studio), Dialpad (Resolve multi-agent), Nextiva (AI Employee) | | [S27][S32][S37][S45] |
| Speech-recognition IVR (non-generative) | "Say the department name" menus. | NS (speech-to-text IVR), 8x8 (Intelligent IVR), Nextiva (conversational IVR) | | [S48][S29][S46] |

---

## Features that appear distinctive or emerging (2024–2026)

1. **The AI receptionist is now table stakes.** Every vendor here except Teams offers a GA AI front-desk agent. Teams relies on Copilot Studio and partners (inferred). RC reports 11,800+ paying AIR customers. Pricing is converging on metered minutes: RC ~$0.39–0.50/min effective; Webex $100 per 250 min, about $0.40/min. Expect recurring per-minute costs and knowledge-base upkeep. [S11][S28]
2. **Calls are getting AI context.** Examples: Webex "Caller Intent" before answer, AI summaries handed over on transfer, AI caller-name resolution, and in-call "Ask AI" [S22][S27]. Zoom adds voicemail prioritization and voicemail-to-task [S15].
3. **Real-time speech translation.** Webex Translator Agent (Q3 2026) and RC live translation [S27][S8]. This is potentially valuable for schools and municipalities serving non-English speakers.
4. **Text and SMS queues with shared inboxes.** Webex Text Queues (June 2026), Zoom Team SMS, NS SMS queues, and RC Business SMS Booster [S22][S14][S48][S9]. Texting is being treated like calls: queued, assigned and reported.
5. **Lightweight contact center inside UCaaS.** Webex Customer Assist, Zoom CE Pack, Teams Queues app (Premium), and RC Call Queues Booster [S24][S14][S2][S9]. NS includes this at no extra cost [S47]. These are the features a school front office or city hall actually uses: wallboards, monitor/whisper and callback.
6. **Queue callback in Teams (late 2024).** This closes a long-standing gap [S6].
7. **Deepfake/voice-fraud detection.** Webex with Pindrop (2026) [S27]. Spam labeling (Teams, Zoom, RC) is now standard [S5][S20][S8].
8. **Hot-desk modernisation.** Webex gives free hot-desk-only licenses and bundles hot-desk profiles that carry lines, BLFs and park keys (2025–2026) [S22]. 8x8 and RC charge for it (Lobby license; Premium tier) [S31][S10].
9. **Survivability and resilience as product features.** Zoom Local Survivability (Zoom Node), Webex site survivability, and GoTo Business Continuity [S14][S27][S34]. This is relevant to schools worried about internet outages and 911.
10. **Emergency workflow beyond 911 routing.** 8x8 Resolve incident alerting (July 2026) [S32], Zoom safety-team alerts and signage [S20], and NS WebPhone location re-prompts on IP change [S52].
11. **AI-assisted administration.** GoTo Admin GoPilot and Webex AI Canvas, which correlates call quality with network telemetry [S35][S27].
12. **Licensing innovation on the carrier side.** NetSapiens has no per-seat licensing, includes call center in core, and lets providers bring their own AI engine [S47]. This contrasts with BroadWorks/Webex Wholesale per-user utility billing [S24].
13. **Shared Calling / no-DID licenses.** Teams Shared Calling and Zoom Pro (no DID) cut per-user number costs for large groups of staff who rarely receive direct calls (for example teachers) [S3][S19].

### Likely gaps for a self-hosted Asterisk PBX (inferred analysis)
Asterisk can do most of categories A, B and C with configuration (often via FreePBX). It usually lacks the following, or needs third-party work:
- AI receptionist, AI summaries, live transcription, sentiment and caller intent (all need external STT/LLM integration).
- Polished mobile apps with push notifications and call flip.
- Dynamic/nomadic E911 with a carrier-validated dispatchable location.
- Native spam labeling and STIR/SHAKEN (these depend on the trunk carrier).
- Supervisor wallboards and Queues-app-style delegated administration.
- Shared SMS inboxes and 10DLC campaign management.
- Teams calling integration (needs an SBC or Direct Routing).
- Quality dashboards (MOS).
- Archiving/DLP connectors, SSO/SCIM, and FedRAMP or HIPAA attestations.
- Survivability and geo-redundancy without a do-it-yourself HA design.

---

## Sources (all opened)

- [S1] Microsoft Learn: Here's what you get with Teams Phone. https://learn.microsoft.com/da-dk/microsoftteams/here-s-what-you-get-with-phone-system
- [S2] Microsoft Learn: Manage the Queues app. https://learn.microsoft.com/en-us/microsoftteams/manage-queues-app
- [S3] Microsoft Learn: Shared Calling example scenario. https://learn.microsoft.com/en-us/microsoftteams/shared-calling-scenario
- [S4] UC Today: New Teams Phone announcements include Copilot features (Nov 2023). https://www.uctoday.com/unified-communications/new-teams-phone-announcements-include-copilot-features/
- [S5] BleepingComputer: Microsoft Teams will alert users of incoming spam calls. https://www.bleepingcomputer.com/news/microsoft/microsoft-teams-will-alert-users-of-incoming-spam-calls/
- [S6] Practical365: Teams call queue and call back feature. https://practical365.com/teams-call-queue-and-call-back-feature/
- [S7] A Guide to Cloud: Teams Phone Standard licensing. https://www.aguidetocloud.com/licensing/teams-phone-standard/
- [S8] RingCentral datasheet: All about RingCentral Phone. https://assets.ringcentral.com/us/datasheet/all-about-ringcentral-phone.pdf
- [S9] CloudTalk: RingCentral pricing (2026). https://www.cloudtalk.io/blog/ringcentral-pricing/
- [S10] RingCentral plan-pricing tier sheet (legacy tier names). https://www.ringcentral.com/shared/content/dc/plan-pricing-v5.html
- [S11] RingCentral press release, May 7 2026 (AIR). https://www.ringcentral.com/whyringcentral/company/pressreleases/ringcentral-brings-always-on-ai-to-the-front-lines-of-customer-engagement.html
- [S12] RingCentral partner support: TCR registration. https://partnersupport.ringcentral.com/frontier/tcr-registration.html
- [S13] RingCentral Plans & Pricing. https://www.ringcentral.com/office/plansandpricing.html
- [S14] Zoom: All VoIP phone features. https://www.zoom.com/en/products/voip-phone/features/
- [S15] Zoom Phone product page. https://www.zoom.com/en/products/voip-phone/
- [S16] CloudTalk: Zoom Phone pricing (2026). https://www.cloudtalk.io/blog/zoom-phone-pricing/
- [S17] Zoom Library: Call Delegation and Zoom Assistant. https://library.zoom.com/zoom-workplace/zoom-phone/expert-insights/call-delegation-and-zoom-assistant
- [S18] TechRadar: Zoom's new AI agent (Virtual Agent for Phone). https://www.techradar.com/pro/zooms-new-ai-agent-might-mean-you-never-need-a-human-receptionist-ever-again
- [S19] Zoom Phone global coverage. https://www.zoom.com/en/products/voip-phone/features/global-coverage/
- [S20] Zoom blog: Roundup of Zoom Phone updates (Oct 2020: spam blocking, nomadic E911 signage). https://www.zoom.com/en/blog/a-roundup-of-the-latest-zoom-phone-updates-planned-enhancements
- [S21] Zoom blog: hot desking, call recording, E911 location mapping on Zoom Phone appliances. https://www.zoom.com/ja/blog/access-hot-desking-call-recording-e911-location-mapping-in-zoom-phone-appliance/ (also opened: https://library.zoom.com/zoom-workplace/zoom-phone/expert-insights/emergency-services-best-practices, which is an overview/TOC only)
- [S22] Webex Help: What's new in Webex Calling. https://help.webex.com/en-us/article/i0q0ym
- [S23] Webex Help: Wholesale Route-to-Market Calling Features (BroadWorks feature list). https://help.webex.com/article/nsyoaiy
- [S24] Cisco: Webex Wholesale RTM data sheet. https://www.cisco.com/c/en/us/products/collateral/unified-communications/flex-plan-hub/webex-wholesale-rtm.html
- [S25] Atonement Licensing: Cisco Webex pricing (dated content, 2022–2024). https://atonementlicensing.com/blog/cisco-webex-pricing-2026/
- [S26] Costbench: Webex plans & pricing. https://costbench.com/software/communication/webex/
- [S27] Webex blog: Cisco Live 2026, advancing Cisco Calling. https://blog.webex.com/collaboration/cisco-live-2026-advancing-cisco-calling-with-ai-hybrid-flexibility-resilience/
- [S28] Webex blog: AI Receptionist for Webex Calling GA. https://blog.webex.com/collaboration/ai-receptionist-for-webex-calling-is-now-generally-available/
- [S29] KCOM: 8x8 X Series feature matrix (UK public sector). https://www.kcom.com/home/media/oehjnpz5/kc_6432-8x8-x-series-feature-matrix-uk-public-sector-edition.pdf
- [S30] Ringly: 8x8 pricing 2026. https://www.ringly.io/blog/8x8-pricing
- [S31] 8x8 Help: Hot Desk FAQ. https://help.8x8.com/docs/hot-desk-faq
- [S32] 8x8 newsroom: 8x8 extends AI across entire organization (July 30, 2026). https://www.8x8.com/newsroom/8x8-extends-ai-across-entire-organization-bringing-enterprise
- [S33] GoTo Connect data sheet. https://review.goto.com/-/media/pdfs/data-sheet/ds-goto-connect.pdf
- [S34] CloudTalk: GoTo Connect pricing 2026. https://www.cloudtalk.io/blog/goto-connect-pricing/
- [S35] GoTo: Practical AI. https://www.goto.com/connect/solutions/practical-ai
- [S36] CloudTalk: GoTo Connect AI Receptionist review. https://www.cloudtalk.io/blog/goto-connect-ai-receptionist-review
- [S37] Dialpad pricing. https://www.dialpad.com/au/pricing
- [S38] Dialpad Help: Dialpad feature comparison. https://help.dialpad.com/docs/dialpad-feature-comparison.md
- [S39] Dialpad Help: STIR/SHAKEN for Dialpad users. https://help.dialpad.com/docs/stirshaken-for-dialpad-users.md
- [S40] GetVoIP: Vonage Business pricing. https://getvoip.com/blog/vonage-business-pricing/
- [S41] FitSmallBusiness: Vonage Business Communications review. https://fitsmallbusiness.com/vonage-business-communications-review
- [S42] Vonage: Call Park feature. https://www.vonage.com/unified-communications/features/call-park/
- [S43] Vonage: Conversation Analyzer. https://www.vonage.com/resources/articles/conversation-analyzer/
- [S44] Grasshopper: Nextiva pricing in 2026. https://grasshopper.com/blog/nextiva-pricing-in-2026
- [S45] Nextiva homepage (XBert, plans). https://nextiva.com/?amp=1
- [S46] Nextiva Business Phone Overview, advanced products & features (D&H PDF). https://dandh.ca:443/media/pdf/pages/cloud/vendor/nextiva/Nextiva-Business-Phone-Overview-Advanced-products-and-Features.pdf
- [S47] NetSapiens SNAPsolution page. https://netsapiens.com/snapsolution/
- [S48] Momentum: Cloud PBX Features QRG (NetSapiens feature list). https://university.gomomentum.com/wp-content/uploads/2025/02/Tutorial-Cloud-PBX-Features-QRG.pdf
- [S49] Crexendo: VIP Portal SNAPbuilder features. https://cxdo.helpjuice.com/en_US/vip-portal/vip-portal-list-of-available-features-for-snapbuilder
- [S50] FirstLight: SNAPmobile End User Guide iOS. https://www.firstlight.net/wp-content/uploads/2025/10/SNAPmobile-End-User-Guide-iOS.pdf
- [S51] FirstLight: Call Center on SNAPMobile Web. https://www.firstlight.net/wp-content/uploads/2026/05/Call-Center-SNAPMobile-Web.pdf
- [S52] Viirtue: 4 best features in NetSapiens v42. https://blog.viirtue.com/4-best-features-in-netsapiens-v42
- [S53] Barchart/press: Crexendo announces v44.2 release with AI innovations (Jan 2025). https://www.barchart.com/story/news/30621024/crexendo-announces-v442-release-with-ai-innovations-propelling-the-future-of-communication
- [S54] Clarity Voice: NetSapiens features (platform overview). https://portal.clarityvoice.com/portal/netsapiens-features.html
- Also opened, but little useful content: https://catalog.appdirect.com/en-us/apps/360501/vonage-business-communications/features ; https://www.directionsonmicrosoft.com/roadmaps/ref/teams-phone-roadmap/ (paywalled)
