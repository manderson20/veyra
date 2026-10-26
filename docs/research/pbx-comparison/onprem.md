# Self-hosted / on-premises PBX platforms: feature survey (as of Oct 2026)

Scope: 3CX v20, FusionPBX (FreeSWITCH), Wazo Platform, VitalPBX, Yeastar P-Series, Grandstream UCM6300/UCM family, Issabel, Cisco Unified Communications Manager (CUCM), Avaya IP Office (IPO), Mitel MiVoice Business / MX-ONE (brief). Kamailio and OpenSIPS appear only as a note. FreePBX is excluded because it is covered elsewhere.

**Abbreviations:** 3CX, Fusion, Wazo, Vital, Yeastar, GS-UCM, Issabel, CUCM, IPO, Mitel.

**Evidence markers**
- **[Sn]** points to the numbered source list at the end. I opened every page listed there.
- **(inf.)** marks an inferred or unverified claim. It comes from general product knowledge, from a component the product is built on (Issabel is built on Elastix/FreePBX/Asterisk), or from a doc title seen in search results that I could not render. Treat (inf.) items as "probably, verify before relying on it".
- A platform is left out of a row when I found no evidence for it, which does not mean it lacks the feature.

---

## 1. Platform profiles

**3CX v20 (3CX Ltd.).** 3CX is a software PBX for Windows/Linux (Debian). It can run on premises, in a private cloud (VMware/Hyper-V/KVM) or as "3CX Hosted" [S2][S4]. It is licensed per **simultaneous calls (SC)**, not per user, with an annual licence. 2026 editions are **BASIC, PRO and AI** (the AI edition was formerly "Enterprise", renamed "Enterprise / AI" in Nov 2025 with roughly a 15% rise) [S6]. A free 4SC/"SMB" tier also appears on the features page [S2].
- Official USD annual list prices for 8SC: BASIC $300, PRO $395, AI $575.
- For 32SC: $915 / $1,215 / $1,620.
- For 128SC: $3,715 / $4,950 / $5,940.
- 3CX hosting is an add-on of $295–$1,995/yr [S1].
- Extension caps per SC are enforced at about 5 extensions per SC up to 24SC, rising to 8 per SC at 256SC+ (for example 8SC = 40 extensions) [S3]; this matches the "Extension Fair Usage" policy [S7].

Typical customers are SMBs and mid-market firms with 10–1,000 users that are sold through resellers, plus hotels (3CX has a built-in hotel module). 3CX is the most feature-rich of the low-cost options, especially for omnichannel chat, CRM, video and AI.

**FusionPBX.** FusionPBX is an open-source, multi-tenant web GUI and application layer on top of **FreeSWITCH**. It is popular with ITSPs and MSPs who host many tenants [S8][S10]. The software is free. Its licence is in the repo's licenses file; it is generally known to be MPL 1.1 (inf.). The project earns money from paid "Member" accounts (training videos, extra docs, monthly continuing-education sessions with the developers) and paid admin/advanced classes; no prices are published [S9]. Version 5.3 added TTS and transcription for recordings and greetings, a rewritten Queues feature, and a "Messages" (SMS) app plus SMS "Providers" [S9]. FusionPBX has no first-party branded mobile app [S9]; operators pair it with third-party softphones (inf.). Typical customers are hosted-PBX providers, MSPs and technically capable self-hosters.

**Wazo Platform (Wazo Communication Inc., Quebec).** Wazo is an API-first, open-source (GPLv3-style) "programmable IP communication" stack [S11]. It is built from Asterisk, Kamailio and RTPEngine, with Python microservices (calld, confd, agentd, auth, webhookd, websocketd), RabbitMQ and PostgreSQL behind REST/WebSocket/webhook APIs. It descends from XiVO. The software is free; Wazo Inc. offers commercial services and support but publishes no prices [S16]. Recent dated releases are 25.01–25.07 (to May 2025) [S15]. The release sidebar lists 26.01–26.10, which shows releases continued through 2026, but I could not read their contents [S15]. Typical customers are carriers, ISVs and integrators building their own UC or contact-center products. It is not a turnkey SMB PBX, and it needs DevOps skills [S16].

**VitalPBX.** VitalPBX is a commercial Asterisk-based PBX distribution on Debian with a modern GUI. Plans [S17]:
- **Community:** free; 12 extensions, unlimited calls, 2 VitXi WebRTC clients, provisioning for 20 devices.
- **Enterprise:** $100/month; unlimited extensions, Sonata Switchboard/Billing/Recording, 50 VitXi clients, unlimited provisioning.
- **Call Center:** $200/month; adds Sonata Dialer and Stats.
- **Multi-Tenant:** $250/month.
- **VitalPBX One:** priced by extension count; monthly, annual or one-time (one-time licences pay 25% for a major upgrade).

Paid plans have **no per-user fees** [S17]. The 2025–2026 releases add AI Voice Agents (OpenAI Realtime), an AI Wizard, AI call analysis/transcription and voicemail transcription [S19][S20]. Typical customers are SMBs, call centres, and MSPs/carriers using the multi-tenant edition, mainly in the Americas.

**Yeastar P-Series (Xiamen Yeastar).** The P-Series ships in four forms:
- Appliance Edition: P520/P550/P560/P570 hardware with modular FXS/FXO/BRI/GSM/4G/E1-T1 interfaces, up to 500 users and 120 calls on the P570 [S21].
- Software Edition: self-hosted, up to 1,000 concurrent calls [S22].
- Cloud Edition and Yeastar Hosted [S22].

It is licensed by **subscription plan** (Standard, Enterprise or Ultimate) sized by extension count. Reseller examples: Software Edition Enterprise Plan with 100 extensions at $699, and Ultimate Plan with 100 extensions at $899 per year [S28][S29]. Some features are plan-gated:
- Remote archiving needs Enterprise.
- The Hotel module is an add-on on the Appliance and needs Enterprise+ on Software/Cloud.
- The outbound dialer is a Software Edition add-on [S21].

Typical customers are SMBs and mid-market firms (5–1,000+ users), hotels and multi-branch companies. Yeastar is a close functional peer of 3CX, with stronger hardware options.

**Grandstream UCM (UCM6300, UCM6300A "Audio", CloudUCM, SoftwareUCM).**
- UCM6300 hardware: up to 3,000 users and 450 calls, with video meetings of 300 participants and 9 video feeds.
- UCM6300A: up to 1,500 users and 200 calls, with no video.
- SoftwareUCM: up to 5,000 users and 1,000 calls, multi-tenant.
- CloudUCM: up to 200 users and 64 calls [S30].

The business model is a **one-time appliance purchase with no per-user licence**. For example, a UCM6304 (4 FXS, 4 FXO, 2,000 users, 300 calls) lists at about $680 [S35]. The **Wave** desktop/mobile/web client and the meeting platform are free [S35]. Remote access through **UCM RemoteConnect (UCMRC)** is an annual cloud plan [S32]:
- Basic: free; 10 remote users, 2 calls, 20-minute call limit.
- SOHO: $125/yr; 20 users.
- Plus, Pro and Business tiers.
- Enterprise: 400 users, 64 calls.

Typical customers are SMBs, schools, hotels and branch offices that want a low-cost appliance. Grandstream has strong hospitality/PMS features and a free management cloud (GDMS).

**Issabel.** Issabel is the community GPL fork of open-source Elastix, created after 3CX bought Elastix and closed it. It bundles Asterisk, a FreePBX-derived GUI, HylaFAX fax, Openfire IM and Postfix [S36]. The current line is 5.0, installed on Rocky Linux 8.9 [S36][S37]. The PBX is free. The commercial **Issabel Contact Center** add-on is licensed per agent as "Voice Agent" or "Omnichannel Agent" (WhatsApp, Telegram, webchat, SMS). It starts at 10 agents on premises or 5 agents plus 1 supervisor in Issabel Cloud; prices are on the vendor site [S39]. Typical customers are SMBs and call centres, especially in Latin America and Spanish-speaking markets.

**Cisco Unified Communications Manager (CUCM / "UCM") 15.** CUCM is Cisco's enterprise call-control cluster. Voicemail runs on Unity Connection and IM/presence on IM&P (inf.). Branch survivability uses SRST/E-SRST routers, and remote access uses Expressway MRA [S40][S41][S43]. Since v12 it uses **Smart Licensing only**, ordered via **Collaboration Flex 3.0** (A-Flex-3, A-Flex-3-EDU and FedRAMP variants) as an Enterprise Agreement or Named User subscription. User types are Knowledge Worker or Professional/Enhanced/Access [S40]. Pricing is quote-only through partners; there is an EDU-specific SKU [S40]. Typical customers are large enterprises, universities, K-12 districts, government and healthcare, often with Cisco networking already in place. It has the deepest enterprise feature set and is the most complex and costly to run.

**Avaya IP Office (IPO).** IPO is an SMB/mid-market hybrid PBX. It runs on IP500 V2 appliances (TDM cards for analog, digital, PRI) or on Linux "Server Edition/Select" with up to 3,000 users and 150 sites [S44]. Licensing comes in two forms:
- Legacy perpetual editions: Basic, Essential and Preferred, plus user profiles Office Worker, Teleworker, Mobile Worker, Power User and Receptionist [S44][S45][S47].
- Subscription mode: per-user per-month Telephony, Telephony Plus or UC User, plus application subscriptions for Receptionist Console, Call Reporter, Contact Center Select, Media Manager and 3rd-party CTI [S46]. There is **no grace period on expiry** [S46].

Avaya does not publish prices. ITQlick estimates about $15–30 per user per month [S50]. Release 12.3 went GA on 30 Apr 2026 [S49]. Typical customers are SMBs and multi-site mid-market firms (schools, municipalities, healthcare clinics) with a long installed base of digital/analog handsets.

**Mitel MiVoice Business (MiVB) and MX-ONE (brief).**
- **MiVB** (current doc release 10.6 [S52]) is Mitel's mid-market IP PBX. It runs on the SMB/EX controller, on industry-standard servers, virtualized, or in AWS/Azure. It offers perpetual (CapEx) or monthly subscription licensing [S53]. Clients are MiCollab for UC/mobile and MiContact Center Business [S51][S53]. Built-in hospitality includes a PMS interface (FIAS, Hilton PEP) [S54].
- **MX-ONE** scales from 500 to 500,000 users, with N+1 clustering, site survivability, multi-tenancy, REST APIs, Teams direct routing via the Mitel SBC, built-in 911/999/112 notification and Mitel Revolution mass notification. It is perpetual or subscription [S55].

Typical customers are government, healthcare, education, hospitality and large multi-site enterprises.

**Note on Kamailio / OpenSIPS.** Both descend from SIP Express Router (SER) and are GPL SIP proxies/registrars/routers [S56], not PBXs. They have no voicemail, IVR, queues or end-user features. Their job is the **edge and scaling layer**: registrar, load balancer or dispatcher, SBC-like topology hiding, least-cost routing, presence, and NAT traversal with RTPEngine. Wazo embeds Kamailio [S11]. A platform for schools and municipalities might put Kamailio in front of Asterisk to get multi-node HA, multi-site registration and DoS protection (inf.).

---

## 2. Feature tables by taxonomy category

### A. Per-user calling features

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Do Not Disturb (DND) | Stops calls ringing your phone and sends them to voicemail or busy. | 3CX, Fusion, Wazo, Vital, Yeastar, GS-UCM, Issabel, CUCM, IPO, Mitel | GS-UCM, Grandstream and Mitel sync DND with the hotel PMS. 3CX uses "presence profiles" (Available/Away/DND/Lunch/Business trip) that each carry different forwarding rules (inf.). | [S8][S18][S21][S30][S41][S33] |
| Call forwarding (all/busy/no-answer) | Sends your calls elsewhere unconditionally, when you're busy, or when you don't answer. | All 10 | Vital and Fusion add "unreachable" (phone not registered). GS-UCM 1.0.29 added per-extension "Call Policy" number-handling rules. | [S18][S8][S21][S30][S33][S41] |
| Find-me / follow-me (sequential ring) | Tries your desk, then your mobile, then others in order. | Fusion, Vital, GS-UCM, Issabel (inf.), 3CX (inf.), Yeastar (inf.) | Vital includes it in the User Portal. | [S8][S18][S30] |
| Simultaneous ring / single number reach | Rings several devices at once so one number reaches you anywhere. | Vital ("One Number Reach"), Yeastar (Linkus "one number"), Mitel (up to 8 devices), IPO (mobile twinning), CUCM (Unified Mobility / SNR), 3CX (inf.) | IPO has "fallback twinning" for when the desk phone is unreachable (doc title seen). Mitel MiVB rings up to 8 devices per number. | [S18][S21][S53][S41] |
| Remote office / "extend and connect" | Lets a user's calls be handled on any external phone (home or hotel) while the PBX controls them. | CUCM (Extend and Connect), IPO (Power User "turn home phone into office phone"), Mitel (Teleworker) | CUCM 15 added "Borderless CTI" for Extend and Connect over MRA without VPN. | [S40][S41][S44][S53] |
| Call waiting | Beeps you when a second call arrives during a call. | All 10 | | [S8][S18][S21][S30] |
| Call screening | Asks unknown callers to say their name before you accept. | Vital, Issabel (inf.), Fusion (inf.) | | [S18] |
| Blocklist / allowlist (personal & system) | Rejects calls from specific numbers or only allows listed ones. | Fusion (Call Block), Vital, Yeastar, GS-UCM, Wazo, 3CX (inf.) | Wazo 25.06–25.07 added a personal end-user blocklist API. GS-UCM has a "Don't Call Me" list with query timeout. | [S8][S18][S21][S30][S15][S33] |
| Anonymous call rejection | Rejects callers who hide their caller ID. | Vital (via blacklist/CID routing) (inf.), Fusion (inf.), GS-UCM (inf.) | Usually done with a CID-based inbound route rather than a named feature. | (inf.) |
| Distinctive / priority ring | Uses different ring tones for internal, external or VIP calls. | CUCM (custom phone rings), Vital (inf.), Yeastar (inf.), 3CX (inf.) | CUCM "Custom Phone Rings and Backgrounds". | [S41] |
| Caller ID display / CNAM lookup | Shows the caller's number and name, optionally looked up from a CRM or directory. | All 10 | Vital "caller name lookup". 3CX matches against CRM records. GS-UCM 1.0.29 shows caller name in the CDR. | [S18][S4][S33] |
| Per-call caller-ID blocking / privacy | Hides your number on one call. | CUCM (Privacy, Call Display Restrictions), Fusion (Caller ID), Vital, IPO (inf.) | | [S41][S8] |
| Speed dial | Short codes or buttons for frequently dialled numbers. | 3CX (inf.), Fusion (inf.), Vital, Yeastar, GS-UCM, CUCM, IPO (inf.), Mitel (inf.) | CUCM adds "Abbreviated Dial". Vital supports bulk import/export of speed dials. | [S18][S21][S30][S41] |
| Hotline / PLAR (auto-dial on off-hook) | Lifting the handset automatically dials a fixed number. | CUCM (Hotline, Private Line Automatic Ringdown), Vital (inf.), GS-UCM (inf.) | Useful for lobby, elevator and emergency phones. | [S41] |
| Three-way / ad hoc conference | Adds a third person to a call from the phone. | All 10 | CUCM "Ad Hoc Conferencing". IPO ad hoc ports range from 64 (Basic) to 512 (Select). | [S18][S41][S44] |
| Hold, blind and attended transfer | Puts callers on hold or passes them to someone else. | All 10 | CUCM has "Hold Reversion" (re-alert after a hold timeout) and "External Call Transfer Restrictions". | [S8][S41] |
| Callback on busy / camp-on | The system calls you back when a busy extension frees up. | CUCM (Call Back), Vital ("callback"), GS-UCM ("call-back") | | [S41][S18][S30] |
| Last-number redial / call return | Redials the last call made or received. | All 10 (inf.) | Usually a phone feature or feature code. | (inf.) |
| Malicious call identification / trace | Flags a harassing call so the carrier and logs capture it. | CUCM (Malicious Call ID) | Rare on SMB platforms. | [S41] |
| Personal IVR / personal assistant | Gives a user a mini auto-attendant ("press 1 for my mobile"). | Vital (personal IVR / personal assistant IVR), 3CX AI (AI Personal Assistant) | 3CX AI PA is an AI agent answering on the user's behalf. | [S18][S2] |
| Dictation / personal notes recording | Records voice memos through the PBX. | Vital | | [S18] |
| Video calling (endpoint-to-endpoint) | Video between video phones or softphones. | 3CX (inf.), Vital, Yeastar (Linkus), GS-UCM (Wave, up to 1080p), CUCM, Mitel (MiCollab) (inf.), Wazo | | [S18][S21][S30][S41][S11] |
| Multiple devices per user | One user owns desk, softphone and mobile registrations at once. | Vital, 3CX (inf.), Yeastar, GS-UCM, CUCM, IPO (inf.), Mitel | | [S18][S21][S53] |
| Phone lock | Locks a phone with a PIN so others can't make calls from it. | Vital | | [S18] |
| Wake-up / reminder calls (user-set) | The phone rings at a set time with a reminder. | Vital, 3CX (BASIC+), GS-UCM, Yeastar (hotel), Mitel (hotel) | Mitel guests can set up to 3 wake-ups per day via voicemail since 10.1. | [S18][S7][S33][S54] |
| Scheduled call / call-me-at | The system places a call at a scheduled time. | GS-UCM (SoftwareUCM "scheduled call") | | [S30] |

### B. Business group features

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Ring / hunt groups | One number rings a group of phones. | All 10 | Strategies: ring-all, linear, round-robin, least-recent and others. CUCM is "Accessing Hunt Groups" (hunt log in/out). | [S8][S18][S2][S21][S30][S41] |
| Auto attendant / multi-level IVR | "Press 1 for sales…" menus. | All 10 | GS-UCM up to 5 IVR layers, multilingual. IPO auto-attendants scale from 9 (Basic) to 500 (Select). GS-UCM 1.0.29 added an IVR webhook for call events and control. | [S2][S30][S44][S33][S41] |
| AI receptionist / AI voice agent | An AI answers calls in natural language and routes or takes actions. | 3CX (AI edition), Yeastar, Vital (AI Voice Agents) | Yeastar 2026 adds MCP-server skills, "send SMS" skill and CDR logging of tool calls. Vital uses OpenAI Realtime with dynamic transfer announcements. Mitel Workflow Studio has a GenAI auto attendant. | [S2][S27][S19][S53] |
| Visual call flow designer | Drag-and-drop builder for routing logic. | 3CX (PRO+), Yeastar | Vital has "dynamic routing" and "dynamic destination" add-ons. | [S2][S3][S21][S18] |
| Call processing scripts / custom dialplan | Programmable routing logic beyond the GUI. | 3CX (PRO+ scripts), Fusion (Dialplan Manager), Vital (custom context/application), Wazo (REST + dialplan subroutines), CUCM (External Call Control) | | [S2][S8][S18][S12][S41] |
| Call park / directed park | Parks a call in a slot so anyone can pick it up. | All 10 | CUCM "Call Park and Directed Call Park". | [S8][S18][S2][S41] |
| Call pickup (group / directed) | Answers a colleague's ringing phone. | All 10 | Wazo has directed and group pickup. Vital has "remote call pickup". | [S13][S18][S41] |
| Intercom | Calls a phone that auto-answers on speaker. | 3CX, Vital, GS-UCM, CUCM (dedicated intercom lines), Yeastar (inf.), IPO (inf.), Mitel (inf.) | CUCM intercom uses separate intercom partitions and DNs with whisper. | [S2][S18][S30][S41] |
| Overhead / multicast paging | Broadcasts a voice announcement to a group of phones or speakers. | 3CX, Fusion, Vital ("Paging PRO" add-on), Wazo, Yeastar, GS-UCM, CUCM (Paging, via InformaCast), IPO (inf.), Mitel (inf.) | GS-UCM has 2-way, 1-way, private and multicast paging plus live multicast broadcast with background music (1.0.29). IPO R12.3 lets admins set a minimum page volume on J100 phones. | [S2][S8][S13][S18][S30][S33][S41][S49] |
| Busy Lamp Field (BLF) | Lights on a phone show whether colleagues are busy. | All 10 | CUCM "BLF Presence". | [S2][S18][S21][S30][S41] |
| Shared line / shared call appearance (SCA) | The same line appears on several phones and everyone sees its state. | CUCM, GS-UCM (SCA), IPO (bridged appearance) (inf.), Mitel (multicall/key lines) (inf.), Yeastar (inf.), Vital (inf.) | CUCM shared lines with barge and privacy are a classic enterprise feature. SCA support is uneven on Asterisk systems. | [S30][S41] |
| Boss / secretary (executive-assistant) | An assistant screens and handles the executive's calls. | 3CX (PRO+; AI version in AI ed.), Vital (with whitelist), Wazo (boss-secretary filter), Yeastar, CUCM (Manager Assistant), IPO (inf.) | 3CX AI edition has an "AI Boss-Secretary". | [S2][S18][S13][S21][S41] |
| Barge-in / listen-in / whisper | A supervisor joins, silently monitors or coaches a live call. | 3CX (PRO+), Fusion (Barge/Eavesdrop/Intercept), Vital (call spy, whisper), Yeastar (inf.), GS-UCM (inf.), CUCM (Barge, Silent Monitoring), IPO (inf.), Mitel (inf.) | | [S3][S8][S18][S41] |
| Night service / day-night toggle | One key or code switches routing to after-hours mode. | Fusion (Call Flows day/night), Vital (Night Modes, call flow control), 3CX (inf.), Yeastar (inf.), GS-UCM (inf.), IPO (inf.) | | [S8][S18] |
| Time conditions / business hours and holidays | Routes calls differently by schedule and holidays. | All 10 | Vital has per-time-condition timezone. Wazo "Schedules". | [S8][S13][S18][S21][S30] |
| Music on hold | Audio callers hear while on hold. | All 10 | Vital can stream MOH from an internet source. GS-UCM 1.0.29 added a MOH privilege. | [S18][S8][S13][S33] |
| Dial-by-name directory | Callers spell a name to reach an extension. | Fusion (*411), Yeastar, IPO (Essential+), Vital (inf.), 3CX (inf.), Issabel (inf.) | | [S8][S21][S44] |
| Operator / attendant console (switchboard) | A receptionist screen to see and route all calls. | 3CX (switchboard, PRO+), Fusion (Operator Panel), Vital (Sonata Switchboard), Wazo (switchboard), Yeastar (operator panel in Linkus), GS-UCM (operator panel), IPO (SoftConsole, Receptionist licence), Mitel (MiVoice Business Console), CUCM (third-party/Cisco Attendant Console) (inf.) | IPO allows 4 to 75 receptionists by edition. | [S3][S8][S17][S13][S21][S30][S44][S46][S52] |
| Announcements / announcement center | Pre-recorded messages played to callers or groups. | Fusion, Vital, GS-UCM (Announcement Center) | | [S8][S18][S30] |
| Voicemail broadcast / group voicemail | Leaves one message to many mailboxes. | Vital, Yeastar, GS-UCM (voicemail groups up to 150 members) | | [S18][S21][S33] |
| DISA | Callers dial in, enter a PIN, then get a dial tone to call out. | Fusion, Vital, GS-UCM | | [S8][S18][S30] |
| Multi-site extension dialing / PBX networking | Short-code dialing between offices on separate systems. | Yeastar (multi-site unified numbering), IPO (32 to 150 networked sites; SCN, inf.), CUCM (clusters, ILS/enterprise groups), Mitel (clustering), GS-UCM (peer trunks) (inf.), 3CX (bridges) (inf.), Vital (inf.) | | [S22][S44][S41][S52] |
| Enterprise groups / directory groups | Shared contact groups across the organisation. | CUCM (Enterprise Groups), 3CX (phone directory), Vital (phone books) | | [S41][S2][S18] |
| Call queuing on a plain PBX (no CC licence) | Holds callers in line when a line or hunt group is busy. | CUCM ("Call Queuing" for hunt pilots), all others via queues | | [S41] |

### C. Voicemail and messaging

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Voicemail | Callers leave recorded messages. | All 10 | CUCM uses Cisco Unity Connection (inf.). IPO uses embedded voicemail or Voicemail Pro (Preferred+). | [S8][S18][S44][S47] |
| Voicemail to email | Messages are emailed as audio attachments. | All 10 | Vital supports MP3 attachments, multiple email settings, and emails without audio. | [S8][S18][S20][S21] |
| Visual voicemail | See and play messages in an app or portal. | Vital, Yeastar (Linkus), GS-UCM (Wave), 3CX (apps) (inf.), IPO (Office Worker), CUCM (Jabber/Webex app) (inf.) | | [S18][S44] |
| Voicemail transcription | Messages are turned into text. | 3CX (PRO via Grok/Google/OpenAI; AI ed. on-board), Fusion (5.3+), Vital (Enterprise+), Yeastar, Mitel (inf.) | 3CX AI edition can transcribe on a local server, with no cloud needed. | [S2][S9][S20][S21] |
| Unified messaging (Exchange/IMAP store) | Voicemail sits in the email inbox as the single store. | IPO (Exchange, UMS web services), CUCM/Unity Connection (inf.), Mitel (inf.) | IPO TTS can read email aloud to mobile users. | [S44][S45] |
| Message waiting indicator / stutter dial tone | Lamp or stutter tone when you have voicemail. | All 10 | CUCM "Audible Message Waiting Indicator". Vital stutter tone. | [S18][S41] |
| Fax server / fax to email | Receives faxes as PDFs by email. | 3CX (integrated fax server), Fusion (Fax Server), Vital (virtual faxes add-on), Wazo, Yeastar (T.38, fax to email), GS-UCM (T.38), Issabel (HylaFAX), IPO (inf.) | Issabel bundles HylaFAX. | [S2][S8][S18][S13][S21][S30][S36] |
| SMS / MMS | Business text messaging on the company number. | 3CX (all editions), Fusion (Messages app, 5.3+), Yeastar (omnichannel), Issabel CC (Omnichannel Agent) | Needs a carrier with an SMS API. | [S3][S4][S9][S21][S38] |
| WhatsApp Business | Answers WhatsApp messages in the PBX client. | 3CX, Yeastar, GS-UCM (CloudUCM/SoftwareUCM), Issabel CC | Needs a Meta-verified business account and Cloud API number [S39]. | [S4][S6][S21][S30][S38] |
| Facebook / Instagram Messenger | Social DMs routed to agents. | 3CX (FB/IG), Yeastar (FB) | | [S4][S7][S21] |
| Telegram | Telegram channel in the inbox. | GS-UCM, Issabel CC | | [S30][S38] |
| Website live chat widget | Chat bubble on the website that reaches staff and can turn into a call. | 3CX (WordPress/Drupal/Joomla plugins; chat-to-voice/video), Yeastar (Live Chat with standalone URL), GS-UCM (live chat, SOHO+ UCMRC), Issabel CC (webchat), IPO (via Contact Center Select, Preferred+) | 3CX has chat queues and chat reports (satisfaction, response time). | [S4][S27][S30][S32][S38][S44] |
| Team chat / IM | Internal 1:1 and group chat. | 3CX, Yeastar (Linkus), GS-UCM (Wave; E2E-encrypted group chat, file share), Vital (Communicator), Issabel (Openfire), Wazo, CUCM (IM&P/Webex app), IPO (Workplace/one-X), Mitel (MiCollab) | GS-UCM Enterprise UCMRC adds a Cloud IM service. | [S4][S21][S30][S17][S36][S11][S40][S44][S53] |
| Chatbots on messaging channels | Automated bot replies on chat channels. | Issabel CC (unlimited bots; OpenAI/Anthropic/Groq/Deepseek), 3CX (AI agents) (inf.) | | [S38][S6] |
| Dictation to email / TTS of email | Email read out by phone. | IPO (TTS email reading) | | [S45] |

### D. Clients and mobility

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Desktop softphone (own brand) | PC/Mac calling app. | 3CX (Windows app), Yeastar (Linkus Desktop), GS-UCM (Wave), Vital (Communicator), CUCM (Webex App/Jabber), IPO (Workplace), Mitel (MiCollab) | Fusion, Wazo and Issabel rely on third-party or SDK clients (inf.). | [S2][S26][S30][S17][S40][S44][S53] |
| Mobile app (iOS/Android) | Business-extension calling on a smartphone with push notifications. | 3CX, Yeastar (Linkus Mobile), GS-UCM (Wave, free), Vital ("VitalPBX Connect"; 2 included), CUCM (Webex App), IPO (Workplace), Mitel (MiCollab), Wazo (SDK/push) | CUCM 15 adds iOS Local Push over local Wi-Fi. | [S2][S21][S30][S17][S40][S44][S53][S12] |
| Web client (WebRTC) | Calling from a browser with no install. | 3CX, Yeastar (Linkus Web), GS-UCM (Wave web), Vital (VitXi), Fusion (WebRTC), Wazo | Vital: 2 VitXi on Community, 50 on Enterprise. | [S2][S21][S30][S17][S8][S11] |
| Browser extension / click-to-dial | Click a phone number on a web page to call it. | 3CX (click to call), Yeastar (Linkus Chrome extension), GS-UCM (Chrome extension), CUCM (WebDialer) | | [S4][S21][S30][S41] |
| Presence | Shows colleagues as available, busy, away or in a meeting. | 3CX, Yeastar, GS-UCM, Vital (portal), CUCM (IM&P), IPO (Office Worker+), Mitel (MiCollab) | IPO offers federated presence. | [S21][S18][S44][S53] |
| Hot desking | Log in to any shared desk phone and it becomes your extension. | 3CX (PRO+), Fusion, Vital, Yeastar (*84 / *084 or BLF keys; leaves queues on logout), Mitel (any Mitel phone, office or home), IPO (inf.: hot-desking is referenced in the IPO emergency doc), GS-UCM (inf.) | Yeastar 2026 adds an emergency caller ID for hot-desk phones. | [S3][S8][S18][S25][S27][S53][S48] |
| Extension mobility (enterprise hot desking) | Your full phone profile (lines, speed dials, buttons) follows you to any phone, even across clusters. | CUCM (Extension Mobility, Cross-Cluster EMCC, Roaming) | The CUCM-grade version keeps the whole device profile, not just the extension. | [S41] |
| Device mobility | Phones moving between sites automatically pick up local gateways and settings. | CUCM | CUCM 15 extends it to the Webex App on VDI. | [S40][S41] |
| Teleworker / remote phones without VPN | Office phones at home work through a built-in SBC or proxy. | 3CX (built-in SBC), Yeastar (Remote Access Service / Remote SIP), GS-UCM (UCMRC NAT traversal), CUCM (Expressway MRA), IPO (Teleworker profile), Mitel (Teleworker) | GS-UCMRC Basic is free but limits calls to 20 minutes. | [S2][S21][S32][S41][S45][S53] |
| Call move / pull between devices | Moves a live call from desk phone to mobile. | CUCM (Unified Mobility "desk pickup") (inf.), 3CX (inf.), Yeastar (inf.), Mitel (inf.) | | (inf.) |
| Headset integration | Answer and hang up from headset buttons in the app. | 3CX (all editions), CUCM (headset management/services) | | [S2][S41] |
| User self-service portal | Users manage forwarding, voicemail and recordings online. | Vital, 3CX (web client), Yeastar (Linkus Web), GS-UCM, CUCM (Self Care Portal), IPO (one-X Portal, Preferred+), Fusion (inf.) | | [S18][S41][S44] |
| Location awareness for clients | Detects whether a softphone is on the corporate network (e.g. by SSID). | CUCM (Location Awareness) | | [S41][S42] |
| Client SDK | Embed calling in your own app. | Wazo, Yeastar (Linkus SDK), GS-UCM (Collaboration SDK, UCMRC Business+) | | [S12][S21][S32] |

### E. Conferencing and collaboration

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Audio conference bridge / meet-me rooms | Dial-in conference rooms with PINs. | All 10 | IPO meet-me ports range from 0 (Basic/Essential) to 512 (Select). GS-UCM6300A: 9 rooms, 150 parties. Fusion has a "Conference Center". | [S8][S18][S30][S41][S44] |
| Built-in video meetings | Browser video meetings hosted on the PBX or vendor cloud. | 3CX (up to 250 participants; webinars), GS-UCM (25 rooms, 300 participants, 9 video feeds on UCM6300), Yeastar (browser video conferencing, Ultimate plan), Vital (unlimited users, screen share, secure rooms), Mitel (MiCollab), IPO (Workplace/Spaces, Preferred+), CUCM (Conference Now / CMS) (inf. for CMS) | 3CX meetings are included in the licence, with no per-user fees. | [S4][S7][S30][S28][S18][S53][S44][S41] |
| Screen sharing | Share your screen during a meeting. | 3CX (plus PDF sharing and remote desktop), GS-UCM, Yeastar, Vital, CUCM (BFCP presentation sharing) | | [S4][S30][S28][S18][S41] |
| Whiteboard, polls, surveys | Collaboration tools inside meetings. | 3CX (polls, whiteboard), GS-UCM (polls, surveys, multiplayer whiteboard) | | [S4][S30] |
| Meeting recording and reports | Records meetings and produces post-meeting summaries. | 3CX (inf.), GS-UCM (recording, post-meeting reports, host download) | | [S30][S33] |
| Room scheduling / meeting assistant | Books meeting rooms and runs scheduled meetings. | GS-UCM | | [S30] |
| Conference Now / ad hoc to meet-me | Instant personal conference number. | CUCM | | [S41] |
| Team spaces / persistent workspaces | Persistent project rooms with chat, files and calls. | Mitel (MiCollab/MiTeam), IPO (Avaya Spaces), CUCM (Webex App) | | [S53][S44] |

### F. Contact center

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| ACD call queues | Holds callers in line and hands them to the next free agent. | 3CX (PRO+), Fusion (Call Center), Wazo, Vital, Yeastar, GS-UCM, Issabel, CUCM (call queuing; full CC via UCCX, inf.), IPO (inf.), Mitel (MiContact Center) | GS-UCM allows per-queue prompt language and "premium code" priority. Vital has queue VIP and queue priorities. | [S3][S8][S14][S18][S21][S30][S38][S41][S51][S33] |
| Agent login/logout and states | Agents sign in and out and set pause or wrap-up. | 3CX, Fusion, Wazo, Vital, Yeastar, GS-UCM, Issabel CC, CUCM (hunt login) | Yeastar removes hot-desk users from queues on logout. | [S14][S18][S25][S41] |
| Skills-based routing | Sends calls to agents with the right skill (e.g. Spanish). | 3CX (AI ed.), Wazo, Yeastar | | [S3][S14][S21] |
| Queue callback | Callers keep their place and get called back. | 3CX (PRO+), Vital (queue callback add-on), Yeastar | | [S2][S18][S21] |
| Wallboard | Big-screen live stats (waiting calls, SLA). | 3CX (PRO+), Yeastar, Vital (Sonata Stats) (inf.) | | [S3][S21] |
| SLA alerts / monitoring | Alerts when wait time breaches a target. | 3CX (PRO+), Yeastar | | [S3][S21] |
| Supervisor tools (spy, whisper, barge) | Supervisors coach and monitor agents. | 3CX, Fusion, Vital, Wazo (supervisor workstation), Issabel CC, CUCM | | [S3][S8][S18][S14][S38][S41] |
| Agent greeting | Plays a pre-recorded agent intro automatically. | CUCM | | [S41] |
| Outbound dialer (preview/progressive/power/predictive) | The system dials lists of numbers for agents. | Vital (Sonata Dialer, Call Center plan), Yeastar (Software Edition add-on: power, progressive, agentless), Issabel CC (manual, preview, progressive; **no predictive**) | | [S17][S21][S38] |
| Omnichannel inbox | Voice, chat, SMS and social in one agent queue. | 3CX, Yeastar, Issabel CC (Omnichannel Agent), IPO (ACCS: voice, web chat, email, fax), Mitel (omnichannel CC) | | [S4][S21][S39][S44][S53] |
| Queue / agent reports | Historical stats per queue and agent. | 3CX, Fusion (inf.), Vital (Sonata Stats, IVR stats), Wazo, Yeastar, GS-UCM (queue CDR for "chairmen"), Issabel (Asternic stats), IPO (Historical Call Reporter subscription) | | [S3][S17][S14][S21][S33][S37][S46] |
| Screen pop / CRM pop | Opens the caller's record when the phone rings. | 3CX, Yeastar (Linkus), Wazo, Mitel (inf.) | | [S4][S14] |
| Call center add-on licensing | How contact-center features are paid for. | 3CX (edition-gated), Vital ($200/month Call Center plan), Issabel (per-agent block of 10), IPO (ACCS subscription), CUCM (UCCX, separate licence) (inf.) | | [S3][S17][S39][S46] |
| Workforce management (WFM) | Agent forecasting and scheduling. | None of the SMB platforms natively. Mitel and Cisco via separate CC suites (inf.) | | (inf.) |

### G. Dialing control, carrier and regulatory

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Class of service / call restrictions | Limits who can dial international or premium numbers. | Vital (class of services, dial restriction rules), CUCM (partitions/CSS) (inf.), IPO (call barring), GS-UCM (privilege levels) (inf.), Yeastar (inf.), 3CX (inf.) | | [S18][S48] |
| Account codes / client matter codes | Tags calls to a client or project for billing. | Vital (customer account codes), CUCM (CMC) | | [S18][S41] |
| Forced authorization codes / PINs | Requires a PIN to make certain calls. | Vital (PIN sets, authorization codes), CUCM (FAC) | | [S18][S41] |
| Direct 911 dialing (Kari's Law) | 911 works with no "9" prefix and bypasses barring. | CUCM (auto-checks for a 911 pattern in US time zones), GS-UCM (claims full compliance), IPO ("Dial Emergency" bypasses barring, works from locked/logged-off phones), Yeastar (emergency numbers), 3CX (inf.) | | [S40][S42][S31][S48][S23] |
| On-site 911 notification | Alerts the front office or security when someone dials 911. | Yeastar (email, mobile call or extension call with announcement), GS-UCM (notification calls to selected members, admin email, auto-record and email the recording), IPO (alarm via SNMP/syslog/email even if the call fails), Mitel (built-in in MX-ONE), CUCM (**not native**; needs Cisco Emergency Responder, RedSky or Intrado) | Key for schools: GS-UCM and Yeastar do this natively; CUCM needs an add-on. | [S24][S31][S48][S55][S42] |
| Dispatchable location / ELIN (RAY BAUM'S) | Sends the caller's building, floor or room to the 911 centre. | Yeastar (ERL→ELIN per building, floor or room), GS-UCM (ELIN by subnet or per extension, up to 50), IPO (location per extension or IP range), CUCM (CER switch-port/subnet tracking; RedSky), Mitel (Intrado/RedSky deployment guides), 3CX (Geolocation-by-Reference URL via Bandwidth/Voxtelesys, US only) | 3CX and CUCM can pass location for remote softphones; most others rely on ELIN caller ID. | [S23][S31][S33][S48][S42][S52][S5] |
| PSAP callback routing | 911 centre callbacks reach the original phone or security desk. | Yeastar, GS-UCM, CUCM (CER) | | [S23][S31][S42] |
| Emergency call preemption | Drops an existing call if all trunks are busy so 911 gets through. | GS-UCM ("Disable Hunt on Busy" off) | GS-UCM also has 3 urgency levels and up to 5 trunks per emergency number. | [S31] |
| 988 dialing | Native 988 suicide-lifeline short code. | CUCM (14 SU2+, 15) | | [S40][S42] |
| Toll-fraud / intrusion protection | Blocks hacking and SIP brute force. | 3CX (anti-hacking), Vital (Fail2ban, firewall, geo firewall), Yeastar (auto/static defense, global anti-hacking IP blocklist, outbound frequency limits), GS-UCM (Fail2ban, Geo-IP ACL, SYN flood defense), Fusion (inf.), CUCM (call throttling) | GS-UCM 1.0.29 has concurrent-call thresholds with alerts. | [S4][S18][S21][S26][S33][S41] |
| Caller ID per user/group / CID modifiers | Sets outbound caller ID per extension, route or department. | Vital (CID modifiers), Yeastar (AutoCLIP, CID routing), Wazo (CallerID), Fusion (Caller ID), CUCM (External Phone Number Mask) | | [S18][S21][S13][S8][S40] |
| Least cost routing | Picks the cheapest trunk for each call. | Vital, GS-UCM (1.0.29) | | [S18][S33] |
| Call duration limits / concurrent-call caps | Caps call length or simultaneous calls. | Vital, GS-UCM | | [S18][S33] |
| STIR/SHAKEN | Carrier-side caller authentication. | Handled by the SIP carrier for all; no PBX-native feature found | | (inf.) |
| Separate calling vs billing number | Sends a different billing number from the displayed number. | CUCM | | [S41] |
| Multilevel precedence and preemption | Military/government call priority. | CUCM (MLPP, AS-SIP) | | [S41] |

### H. Recording, analytics and compliance

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Call recording | Records calls automatically or on demand. | All 10 | 3CX: unlimited from PRO, start/stop rights in AI. Wazo 25.02–25.04: on-demand recording for queues and ring groups, pause/resume API, recording announcement. IPO: Media Manager archiving. CUCM: built-in forking to third-party recorders. | [S3][S15][S18][S46][S41] |
| Remote archiving of recordings | Ships recordings to FTP, SFTP, S3 or GCS. | Yeastar (Enterprise plan), GS-UCM (NAS; GDMS video storage) | | [S21][S33] |
| CDR / call logs | A record of every call. | All 10 | Vital adds a CEL events report. GS-UCM 1.0.29 adds LinkedID in AMI CDR events. | [S8][S18][S13][S33] |
| Call accounting / billing | Costs calls per extension or department. | Vital (Sonata Billing), Yeastar (call accounting, custom rates), GS-UCM (carrier rates, billing units) | | [S17][S21][S33] |
| Reporting dashboards | Graphical reports of calls, queues and agents. | 3CX, Yeastar, Vital, IPO (Call Reporter), Issabel (Asternic) | 3CX AI dashboards cover sentiment, summaries and agent performance. | [S4][S21][S46][S37] |
| Real-time switchboard / monitoring | Live view of all calls in progress. | 3CX (switchboard), Vital (Sonata Switchboard), Fusion (Operator Panel) | | [S3][S17][S8] |
| AI call transcription | Turns recorded calls into text. | 3CX (AI ed.; on-board server at 16SC+ or Google/OpenAI), Yeastar (auto-rules by call type, feature code to pause), Vital (Call Analysis), Wazo (via external STT; none built in) | 3CX speaker diarization. | [S2][S27][S19][S12] |
| AI summaries and sentiment | Auto-summaries and mood scoring per call. | 3CX (AI ed.), Yeastar (summaries), Vital (call analysis) | | [S2][S22][S19] |
| Remote DB for BI (Grafana/Power BI) | Exports data to an external database for BI tools. | 3CX (Enterprise Plus / AI) | | [S7] |
| SNMP monitoring | Integrates with network monitoring. | Yeastar, GS-UCM (call/system OIDs), IPO (alarms), CUCM (RTMT) (inf.) | | [S21][S33][S48] |
| Voice quality tools | MOS and voice-quality troubleshooting. | Mitel (voice quality troubleshooting guide), CUCM (RTMT) (inf.) | | [S52] |

### I. Integrations and APIs

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| CRM integration | Links calls to customer records in the CRM. | 3CX (Salesforce, HubSpot, Dynamics, Zoho and others; PRO+), Yeastar (Zoho, Salesforce, HubSpot, Bitrix24, Odoo, Dynamics; Enterprise+), GS-UCM SoftwareUCM (Salesforce, SugarCRM, Vtiger, Zoho, ACT!, Odoo), Vital (omnichannel CRM add-on), Mitel (Workflow Studio: Salesforce) | 3CX auto-creates contacts and journals calls and chats. | [S4][S21][S29][S30][S17][S53] |
| Helpdesk integration | Logs calls in ticketing systems. | Yeastar (Zendesk, Zoho Desk) | | [S21] |
| Microsoft Teams | Use PBX calling inside Teams. | 3CX (Direct Routing, AI ed.), Yeastar (embedded Linkus in Teams, no Teams Phone licence needed), GS-UCM (TeamMate), CUCM (Webex Calling for Teams), MX-ONE (certified Direct Routing via Mitel SBC), IPO (inf.) | | [S3][S26][S30][S40][S55] |
| Microsoft 365 / Outlook | Contact sync, click-to-call from Outlook, calendar presence. | 3CX (user sync on BASIC; full on PRO+), Yeastar (Outlook, Entra ID), GS-UCM (Outlook, O365, Entra ID SSO) | | [S2][S26][S33] |
| Google Workspace | Contact and user sync and SSO. | 3CX (sync BASIC; full PRO+), Yeastar (SSO + sync), Mitel (Workflow Studio) | | [S2][S21][S53] |
| SSO (SAML/OIDC/Entra) | Log in with company credentials. | Yeastar (Entra ID, Google), GS-UCM (Entra ID), IPO (Workplace SSO, R12.3), CUCM (inf.) | | [S21][S33][S49] |
| LDAP / Active Directory sync | Pulls users and contacts from the directory. | Yeastar, GS-UCM, CUCM (LDAP auto-provisioning and write-back), IPO (Server Edition+ AD), Vital (phonebook) (inf.) | | [S21][S33][S40][S44] |
| REST API | Program configuration and calls. | 3CX (Xapi / Call API, AI ed.), Wazo (complete OpenAPI REST), Vital (API v2), Yeastar (config, call control, events), GS-UCM (API/SDK, per-user API permissions), MX-ONE (REST), CUCM (AXL/JTAPI) (inf.) | Wazo is the most API-complete. | [S2][S11][S18][S21][S30][S33][S55] |
| Webhooks / event streams | Pushes call events to other systems. | Wazo (webhookd, websocketd), GS-UCM (IVR webhook), Yeastar (event notifications) | | [S11][S33][S21] |
| AMI / CTI | Low-level control for third-party CTI apps. | Vital (Asterisk Manager users), GS-UCM (AMI), IPO (3rd-party CTI subscription: DevLink, TAPI), CUCM (JTAPI/TAPI) (inf.) | | [S18][S33][S46] |
| Hotel PMS | Links to hotel management software. | 3CX (Micros-Fidelio, Protel, roomMaster), Yeastar (Oracle Opera), GS-UCM (Oracle OPERA IFC8, char pmslink, HSC, IDS, Mitel PMS, local PMS), Mitel (FIAS, Hilton PEP) | | [S4][S21][S33][S30][S54] |
| AI / MCP integration | Connects the AI receptionist to external tools and data. | Yeastar (MCP server skills, 2026), Vital (OpenAI), Issabel CC (multiple LLM providers) | | [S27][S19][S38] |
| Low-code workflow automation | Automates tasks beyond calls (visitor registration, scheduling). | Mitel (Workflow Studio: Jira, Slack and others) | | [S53] |
| Cloud-connected management | Vendor cloud manages on-prem boxes. | GS-UCM (GDMS, free), CUCM (Webex Cloud-Connected UC) | | [S30][S40] |

### J. Administration, provisioning and platform

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Web admin portal | Browser-based management. | All 10 | | [S8][S18][S21][S30] |
| Multi-tenancy | One system hosts several separate organisations. | Fusion (core feature), Vital (Multi-Tenant plan $250/month), 3CX ("multi-company" on BASIC+), Yeastar (service-provider), GS-UCM (SoftwareUCM, CloudUCM), CUCM (logical partitioning, inf.), MX-ONE | Useful for a county hosting schools and departments as tenants. | [S8][S17][S3][S22][S30][S55] |
| Phone auto-provisioning | Plug in a phone and it configures itself. | All 10 | Yeastar: 500+ phones from 14+ brands. GS-UCM ZeroConfig is Grandstream-centric. Vital: Endpoint Manager. | [S22][S30][S18][S8] |
| Bulk import/export | Spreadsheet loading of users and devices. | Vital, Yeastar, GS-UCM (XLSX), CUCM (BAT), 3CX (inf.) | | [S18][S21][S33][S40] |
| Backup and restore | Scheduled configuration backups. | All 10 | | [S18][S21][S33] |
| High availability / failover | A standby server takes over if the primary fails. | 3CX (AI ed. failover + standby licence), Fusion (scalable and redundant), Vital (HA add-on), Yeastar (hot standby; needs an extra server), IPO Select (duplex server), CUCM (clustering), Mitel (resiliency, clustering), MX-ONE (1+1, N+1) | Rare as a built-in in Asterisk SMB products. | [S3][S8][S18][S21][S44][S52][S55] |
| Branch survivability (SRST-style) | Branch phones keep working locally if the WAN to HQ fails. | CUCM (SRST/E-SRST on ISR/Catalyst 8000 routers, up to 2,500 phones), MX-ONE (site survivability), IPO (resilience/backup, inf.), Mitel MiVB (resilient controllers, inf.) | No Asterisk SMB platform in this set has a packaged SRST equivalent (inf.). | [S43][S55][S52] |
| Disaster recovery / geo-redundancy | A system at another site takes over. | Yeastar (DR), Vital (disaster recovery), MX-ONE (geographic DR), CUCM (inf.) | | [S21][S18][S55] |
| Security: MFA for admins and users | Second factor at login. | Yeastar (2FA for admin and Linkus), CUCM (certificate MFA for RTMT), GS-UCM (inf.) | | [S26][S40] |
| Encryption (TLS/SRTP) | Encrypts signalling and media. | All 10 | CUCM is FIPS 140 verified. | [S18][S21][S30][S40] |
| Built-in SBC / NAT traversal | Remote phones connect safely without VPN. | 3CX, GS-UCM (CloudUCM built-in SBC; UCMRC), Yeastar (Remote SIP), CUCM (Expressway, separate) | | [S2][S30][S21] |
| Analog FXS/FXO ports | Connects analog phones, fax, door stations and POTS lines. | Yeastar (modules on P550/P560/P570), GS-UCM (UCM6300 FXS/FXO, lifeline), Vital/Issabel/Fusion (via DAHDI or gateways), IPO (IP500 V2 cards, inf.), CUCM (VG410 gateways in BAT), Mitel (inf.) | | [S21][S35][S18][S40] |
| PRI / E1/T1 / BRI | Connects legacy digital trunks. | Yeastar (EX30 E1/T1; BRI), Vital (DAHDI PRI/R2/BRI), GS-UCM (inf.: not in the sales kit), CUCM (ISR gateways, inf.), IPO (inf.), Mitel (inf.) | | [S21][S18] |
| GSM / 4G trunks | Mobile network as a backup trunk. | Yeastar (GSM/3G/4G modules), Vital (GSM signalling) | | [S21][S18] |
| Virtualisation support | Runs as a VM. | 3CX, Vital, Mitel (VMware, Hyper-V, Nutanix, Proxmox), MX-ONE (plus KVM, AHV), CUCM, IPO Server Ed. (inf.), Fusion (inf.) | | [S2][S18][S53][S55] |
| Online updates / auto-upgrade | Patches applied from the GUI. | 3CX (automatic updates), Yeastar, GS-UCM (scheduled auto-upgrade), IPO (inf.) | | [S4][S21][S33] |
| Central multi-site management | One console for many systems or sites. | Yeastar (site templates), GS-UCM (GDMS), IPO Server Ed./Select (centralised web admin), CUCM, MX-ONE (hundreds of sites) | | [S22][S30][S44][S55] |
| White-labelling / branding | Reseller branding of the GUI and apps. | Fusion (rebranding), Vital (Branding add-on), Yeastar (white-label), GS-UCM (custom logo, UCMRC Business+), 3CX (custom phone logo in AI ed.), CUCM (branding customisation) | | [S8][S18][S22][S32][S2][S41] |
| Subscription vs perpetual licensing | How the software is paid for. | 3CX annual per-SC; Yeastar annual plan; Vital monthly/annual/one-time; GS-UCM one-time hardware plus optional UCMRC; IPO perpetual or subscription; CUCM Flex subscription; Mitel perpetual or subscription; Fusion/Wazo/Issabel free (GPL/OSS) | IPO subscriptions stop immediately on expiry. | [S1][S28][S17][S35][S46][S40][S53] |
| Global anti-hacking blocklist | A vendor-shared list of bad IPs. | Yeastar | | [S26] |

### K. Vertical / specialty

| Feature | Plain explanation | Which platforms have it | Notable variations / sub-features | Source |
|---|---|---|---|---|
| Hotel / hospitality module | Check-in/out, room phones, guest names, call billing. | 3CX (all editions incl. BASIC, from 16SC), Yeastar (Hotel module: front-desk panel, housekeeping), GS-UCM (Local PMS and many PMS links), Mitel (PMS, VIP, maid ID), Vital (wake-up only) | 3CX blocks external calls from vacant rooms and turns guest WhatsApp/FB chats into calls. | [S7][S4][S21][S33][S34][S54] |
| Room status / housekeeping codes | Cleaners update room state from the room phone. | 3CX, Yeastar, GS-UCM (Housekeeper privilege), Mitel (Dirty/Inspect/Clean, Maid ID) | | [S4][S21][S33][S54] |
| Minibar posting | Posts minibar charges by phone code. | GS-UCM (OPERA, per-item tax), Grandstream-integrated PMS | | [S33][S34] |
| Guest wake-up calls | Automated wake-ups set by guest or front desk. | 3CX, Yeastar, GS-UCM (via IVR; for checked-out rooms too), Mitel, Vital | | [S4][S21][S33][S54][S18] |
| Youth hostel / dial-up code mode | Hostel-style shared-room billing. | GS-UCM (pending) | | [S33] |
| Door phone / video intercom integration | Door stations ring phones and show video, with door-open keys. | Yeastar (door-station video preview in Linkus), GS-UCM (GDS door systems via GDMS video, inf.), 3CX (inf.), IPO (door relay, inf.: forum topic "Open office door"), Vital ("domotic" add-on) | | [S26][S18] |
| Mass notification / emergency broadcast | Lockdown or alert messages to all phones and speakers. | MX-ONE (Mitel Revolution integration), CUCM (Paging via InformaCast, inf.), GS-UCM (multicast live broadcast), Vital (Paging PRO) | Important for schools: only Mitel and Cisco have packaged mass-notification partners. | [S55][S41][S33][S18] |
| Education licensing | Discounted SKUs for schools. | CUCM (A-Flex-3-EDU) | | [S40] |
| Healthcare / nurse call | Nurse-call and DECT integrations. | Mitel (SIP-DECT, healthcare vertical) (inf.), CUCM (inf.) | | [S53] |
| Government / FedRAMP | Compliance SKUs. | CUCM (A-Flex-3-FEDRAMP, FIPS), MX-ONE (data sovereignty) | | [S40][S55] |
| Visitor registration / appointment workflows | Automates front-desk processes. | Mitel (Workflow Studio) | | [S53] |

Row count: A 25, B 24, C 15, D 14, E 8, F 14, G 15, H 11, I 15, J 22, K 11 = **174 rows**.

---

## 3. Distinctive features worth noting (gaps an Asterisk school/municipal/SMB PBX may lack)

1. **Omnichannel inbox with website live chat, WhatsApp, FB/IG and SMS, plus chat-to-call escalation.** 3CX includes this even in BASIC [S3][S4], and it is standard in Yeastar [S21]. Issabel sells it as "Omnichannel Agent" [S39]. Expect to need a carrier SMS API and Meta Cloud API registration [S39].
2. **AI receptionist and AI agents.** 3CX AI edition, Yeastar (2026 adds MCP tool calling, an SMS skill and CDR logging of tool calls [S27]) and VitalPBX (OpenAI Realtime voice agents with contextual transfer announcements [S19]) all ship this. Turnkey AI call summaries, sentiment and transcription with on-box options (3CX on-board transcription server) [S2] are now an SMB baseline.
3. **Native 911 on-site notification plus ELIN/dispatchable location.**
   - GS-UCM calls selected staff with a prompt, emails admins, auto-records and emails the recording, picks the ELIN by subnet, and can preempt a busy trunk [S31][S33].
   - Yeastar calls an extension or mobile or sends email, maps ERLs to ELINs, and routes PSAP callbacks to security [S23][S24].
   - IPO raises an alarm on dial even if the call fails [S48].
   - CUCM needs Cisco Emergency Responder or RedSky for notification [S42].

   This matters a lot for schools and municipal buildings.
4. **Free bundled apps and meetings.** GS-UCM includes the Wave app and video meetings up to 300 participants at no licence cost [S30][S35]. 3CX meetings go up to 250 participants with webinars, polls and whiteboard [S4].
5. **Hotel/PMS integration out of the box.** GS-UCM has OPERA IFC8, minibar, housekeeper roles and wake-up via IVR [S33]. 3CX supports Fidelio, Protel and roomMaster [S4]. Mitel supports FIAS and Hilton PEP [S54]. These features double as dorm/residence-hall features for colleges.
6. **CUCM enterprise mobility.** Extension Mobility, including cross-cluster and roaming, carries a full profile to any phone [S41]. Device Mobility and Extend and Connect add to this. Expressway MRA gives VPN-less phones [S41][S40].
7. **Branch survivability.** CUCM SRST lets a branch router keep up to 2,500 phones calling locally during a WAN outage [S43]. MX-ONE offers site survivability and N+1 [S55]. For multi-building districts and towns, this is the biggest architectural gap in single-box Asterisk designs.
8. **Shared lines, intercom lines and PLAR/hotline phones.** CUCM's SCA, intercom DNs and PLAR [S41] suit front offices, nurse stations and lobby or elevator phones.
9. **Microsoft Teams without Teams Phone licences.** Yeastar embeds Linkus in Teams [S26]. 3CX AI edition and MX-ONE do certified Direct Routing [S3][S55].
10. **Hot desking with queue awareness.** Yeastar logs agents out of queues automatically and sets an emergency caller ID per hot-desk phone [S25][S27]. Mitel lets users log into any phone, including at home [S53].
11. **Packaged contact-center tiers.** These include wallboards, SLA alerts, skills routing, callback, an outbound dialer and switchboard. 3CX PRO/AI, VitalPBX's $200 Call Center plan and Yeastar all package them [S3][S17][S21].
12. **Vendor cloud remote access.** UCMRC [S32] and Yeastar Remote Access Service [S21] give remote users access without port-forwarding.
13. **Mass notification integration.** MX-ONE works with Mitel Revolution, and Cisco with InformaCast (inf.) [S55]. This covers lockdown alerts to phones, speakers and desktops.
14. **Licensing contrasts to price against.**
    - 3CX bills per simultaneous call, with enforced extension caps of about 5 per SC [S1][S3].
    - Vital Enterprise is a flat $100/month with unlimited extensions [S17].
    - GS-UCM is a one-time appliance (about $680 for the UCM6304) [S35].
    - Yeastar Ultimate costs about $899 per year for 100 extensions [S28].
    - IPO subscriptions stop the instant they expire [S46].

---

## 4. Sources (all opened)

- [S1] 3CX price list. https://www.3cx.com/ordering/pricing/pricelist/
- [S2] 3CX edition feature comparison. https://www.3cx.com/ordering/pricing/features/
- [S3] Ahoy Telecom, 3CX licensing: Basic, Pro, AI. https://www.ahoytel.com/services/3cx-licensing/
- [S4] 3CX Communications System deck (Jul 2025). https://www.3cx.com/wp-content/uploads/2025/07/3CX-Communications-System.pptx.pdf
- [S5] 3CX Dynamic E911 with Geolocation. https://www.3cx.com/docs/manual/e911-geolocation/
- [S6] 3CX blog, pricing update Enterprise/AI (Nov 2025). https://www.3cx.com/blog/news/pricing-update-enterprise-ai/
- [S7] The Telecom Spot, 3CX Basic vs Pro vs ENT/AI vs Enterprise Plus 2026. https://www.thetelecomspot.com/blogs/news/3cx-basic-vs-pro-vs-ent-ai-vs-enterprise-plus-key-differences-2026
- [S8] FusionPBX features. https://docs.fusionpbx.com/en/latest/features/features.html
- [S9] FusionPBX home. https://fusionpbx.com
- [S10] FusionPBX README mirror. https://gitea.com/viperasi/fusionpbx
- [S11] Wazo Platform home. https://wazo-platform.org
- [S12] Wazo use cases. https://beta.wazo-platform.org/use-cases
- [S13] Wazo administration docs. https://wazo.readthedocs.io/en/latest/administration/administration.html
- [S14] Wazo contact center docs. https://wazo-platform.org/uc-doc/contact_center/
- [S15] Wazo release notes. https://beta.wazo-platform.org/release-notes/page/3
- [S16] FitGap, Wazo profile. https://us.fitgap.com/products/wazo
- [S17] VitalPBX plans and pricing. https://vitalpbx.com/pbx-plans-and-pricing-vitalpbx-system/
- [S18] VitalPBX full features list (Feb 2025). https://vitalpbx.com/wp-content/uploads/2025/02/VITALPBX-FULL-FEATURES-LIST-FEBRUARY-2025.pdf
- [S19] VitalPBX 4.5.3 R3 (Apr 2026). https://vitalpbx.com/?p=46455
- [S20] VitalPBX 4.5.0 R7 (Apr 2025). https://vitalpbx.com/blog/vitalpbx-4-5-0-r7-release/
- [S21] Yeastar P-Series IP PBX (Appliance). https://www.yeastar.com/p-series-ip-pbx/
- [S22] Yeastar P-Series Software Edition. https://www.yeastar.com/enterprise-phone-system/
- [S23] Yeastar Emergency Calling Overview. https://help.yeastar.com/en/p-series-software-edition/administrator-guide/emergency-calling-overview.html
- [S24] Yeastar Add an Emergency Notification Contact. https://help.yeastar.com/en/p-series-software-edition/administrator-guide/add-an-emergency-notification-contact.html
- [S25] Yeastar Hot Desking Overview. https://help.yeastar.com/en/p-series-software-edition/administrator-guide/hot-desking-overview.html
- [S26] Yeastar SE 83.10.0.30 release notes (May 2023). https://help.yeastar.com/en/p-series-software-edition/release-notes/v83.10.0.30.html
- [S27] Yeastar SE 83.24.0.30 release notes (GA Aug 2026). https://help.yeastar.com/en/p-series-software-edition/release-notes/v83.24.0.30.html
- [S28] VoIP Supply, Yeastar Ultimate Plan 100 ext. https://www.voipsupply.com/yeastar-p-series-ultimate-plan-100-extensions-up-package-p-se-up
- [S29] IP Phone Warehouse, Yeastar Enterprise Plan 100 ext. https://www.ipphone-warehouse.com/yeastar-enterprise-plan-initial-package-100-extensions-p-se-ep-initial/
- [S30] Grandstream UCM sales kit Q1 2025. https://www.grandstream.com/hubfs/Partner_Marketing_Kit/IPPBX%20Solutions/Sales%20Kit/ucm-sales-kit-q1-2025.pdf
- [S31] Grandstream UCM Emergency Calls Guide. https://documentationdev.grandstream.com/wp-content/uploads/2021/10/UCM_Emergency_Calls_Guide.pdf
- [S32] The Telecom Spot, UCM RemoteConnect plans. https://www.thetelecomspot.com/products/grandstream-ucm-remoteconnect-ucmrc-plan
- [S33] Grandstream UCM63xx 1.0.29.11 release note (Jun 2025). https://firmware.grandstream.com/BETA/Release_Note_UCM63xx_1.0.29.11.pdf
- [S34] IP Phone Warehouse, hotel phone systems with UCM6300. https://www.ipphone-warehouse.com/blog/hotel-voip-phone-systems-with-grandstream-ucm6300-series-ip-pbxs/
- [S35] The Telecom Spot, UCM6304 product page. https://www.thetelecomspot.com/products/grandstream-ucm6304-ip-pbx-appliance
- [S36] Issabel (Wikipedia mirror, 2026-03). https://wiki.krisyotam.com/content/wikipedia_en_all_nopic_2026-03/Issabel
- [S37] Issabel CC manual, PBX installation. https://ccmanual.issabel.com/en/previous-requirements/issabel-pbx-installation.html
- [S38] Issabel CC implemented features. https://ccmanual.issabel.com/en/contact-center-description/implemented-features.html
- [S39] Issabel CC licensing type. https://ccmanual.issabel.com/en/contact-center-description/licensing-type.html
- [S40] Cisco UCM 15 data sheet. https://webex.com/content/dam/www/us/en/documents/pdf/ucm-15-data-sheet.pdf
- [S41] CUCM 15 Feature Configuration Guide (TOC). https://www.cisco.com/c/en/us/td/docs/voice_ip_comm/cucm/admin/cucm_b_feature-configuration-guide-for-15.pdf
- [S42] Cisco Q&A, Kari's Law and RAY BAUM'S. https://www.cisco.com/c/en/us/products/collateral/unified-communications/unified-communications-manager-callmanager/q-and-a-c67-743415.html
- [S43] Cisco Unified SRST data sheet. https://www.cisco.com/c/en/us/products/collateral/unified-communications/unified-survivable-remote-site-telephony/data-sheet-c78-744126.html
- [S44] Avaya IP Office platform fact sheet. https://www.avaya.com/content/dam/aem-avaya-portal/en_us/documents/fs-ipo-platform-sme8093en.pdf
- [S45] IP Office user licenses. https://ipofficekb.avaya.com/businesspartner/ipoffice/mergedProjects/installation/user_licenses.htm
- [S46] IP Office subscriptions. https://ipofficekb.avaya.com/businesspartner/ipoffice/mergedProjects/subscription/subscriptions.htm
- [S47] IP Office licenses (apps card). https://ipofficekb.avaya.com/businesspartner/ipoffice/mergedProjects/appscard/licenses.htm
- [S48] Avaya, IP Office emergency services access enhancements (R9.x). https://support.avaya.com/css/public/documents/101090741
- [S49] Avaya IP Office R12.3 release notes (Apr 2026). https://support.avaya.com/css/en/public/documents/101095575
- [S50] ITQlick, Avaya IP Office pricing estimates. https://www.itqlick.com/avaya-ip-office/pricing
- [S51] Mitel, What's New with MiVoice Solutions. https://www.mitel.com/lp/UC-Solutions-Private-Cloud-or-On-Site
- [S52] Mitel document center, MiVoice Business (10.6). https://www.mitel.com/document-center/business-phone-systems%3Amivoice-business%3Amivoice-business
- [S53] MiVoice Business brochure (Jul 2026, BTC). https://btc.bw/business/wp-content/uploads/sites/2/2026/09/MiVoice-Business-Brochure-July-2026.pdf
- [S54] Mitel MiVB Hospitality Solutions Guide. https://www.mitel.com/sites/default/files/s3_imports/Solution%20Guides/MiVB/All%20Releases/en/Hospitality_Solutions_Guide.pdf
- [S55] Mitel MiVoice MX-ONE product page. https://web-dev.mitel.com/products/mivoice-mx-one-onsite-phone-system
- [S56] OpenSIPS (Wikipedia). https://en.wikipedia.org/wiki/OpenSIPS
- [S57] CloudTalk (DE), 3CX Preise (Oct 2026; competitor marketing, EUR figures differ from 3CX list, so not relied on). https://www.cloudtalk.io/de/blog/3cx-preise/

**Caveats**
- I could not open the Avaya documentation.avaya.com pages because they are JS-rendered, so IPO hot desking, door relay, SCN and resilience are marked (inf.).
- The 3CX features page table was cut off after "Call Queues", so per-edition mapping beyond that row comes from [S3] and [S7].
- I did not read Wazo's 26.x release contents.
- CUCM and IPO prices are quote-only.
