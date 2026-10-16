> Research appendix to [FREEPBX_GAP_ANALYSIS.md](../FREEPBX_GAP_ANALYSIS.md). Compiled 2026-10-16 from the cited Sangoma wiki, store, reseller and community pages; not edited since. Prices are reseller sale prices in USD and will drift.

# FreePBX / PBXact commercial (licensed) modules and Sangoma add-ons — feature catalogue

Compiled 2026-10-16 from the Sangoma documentation wiki (sangomakb.atlassian.net, read through the Confluence REST API), Sangoma/FreePBX pages, reseller listings (thetelecomspot.com, voipsupply.com, hssl.us) and FreePBX community threads. freepbx.org add-on pages and voipsupply.com category pages returned HTTP 403 to automated fetches, so prices below are reseller "sale prices" or figures quoted by Sangoma staff/wiki, not a Sangoma price list. Anything marked *(uncertain)* could not be confirmed from a primary source.

Legend for pricing: "25Y" = outright 25-year license (one year of updates included, then yearly maintenance); "1Y" = one-year license. SKUs follow the pattern FPBX-C25Y-xxx / FPBX-C01Y-xxx.

---

## 0. Licensing model, bundles, platform status (applies to all modules)

**License model**
- All commercial modules are bound to a PBX "Deployment ID" (System Admin → Activation shows the Deployment ID and the registered modules). A Deployment ID can be moved to a new server (e.g. a FreePBX 17 rebuild) and keeps its licenses. https://sangomakb.atlassian.net/wiki/spaces/FP/pages/279052296 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35259278
- Two purchase forms: an outright "25 year" license that includes 12 months of upgrades, after which a "Yearly Upgrade Fee" (maintenance) is needed to keep updating; or a 1-year license. Sangoma's Commercial Module EULA sets the yearly upgrade fee at 33 % of current MSRP for modules with MSRP ≤ $100 and 18 % for modules > $100 (fee always follows current MSRP). SysAdmin Pro is quoted as the exception (no maintenance fee). Bundle renewals are calculated per module on individual MSRP, not on the bundle price. EULA: https://www.sangoma.com/wp-content/uploads/FreePBX-Commercial-Module-EULA.pdf ; https://community.freepbx.org/t/commercial-module-renewal-questions/106599 ; https://community.freepbx.org/t/25-year-license/106208
- Newer modules (CDR Pro, Advanced Recovery, Call Accounting, Scribe, SAML, Property Manager Pro, Queue Wallboard, Softphones) are sold annual/monthly only — "newer commercial modules ... are no longer available with 25 year licenses". https://community.freepbx.org/t/25-year-license/106208
- Expiry enforcement (2026 behaviour): dashboard warnings when the support/maintenance contract is about to expire; a one-month grace period with e-mails (start, 7 days left, 1 day left); after that the module's GUI is blocked ("Module Access Blocked"/"Maintenance Expired") when the installed version is newer than the licensed one; Sangoma Talk shows "Expired-License/ERROR E67" and can only place emergency calls. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/1878425608
- System Admin → Commercial Licenses lists every licensed module, license expiry, maintenance expiry, newest available version with changelog link, support contract expiry and PBXact POMPs expiry. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35226559
- Support included with a module license = bug reports only; setup/how-to help is paid support credits. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/32571674
- Commercial modules are "not Open Source GPL and are only designed to work with the FreePBX Distro" (SNG7) and, for 17, with the Sangoma Debian packages installed by the official install script. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22478862

**Bundles** (module lists from Sangoma wiki; prices are reseller sale prices)
- Starter: SysAdmin Pro, Extension Routing, Conference Pro, Fax Pro, Paging Pro, Park Pro — 25Y $349, 1Y $169.
- Advanced: Appointment Reminder, Caller ID Management, Class of Service, Call Recording Reports, Pinset Pro, Voicemail Notify, Voicemail Reports, Web Call Me — 25Y $1,149, 1Y $579 (reseller: "$1,528 worth" separately).
- Call-Center: Caller ID Management, Class of Service, CRM Link, Outbound Call Limiting, Pinset Pro, QXact Reports, VQ Plus, Web Call Me, XactDialer — 25Y $2,299.
- Everything: all of the above (Appointment Reminder, CID Mgmt, CoS, Conference Pro, Call Recording Reports, CRM Link, Extension Routing, Fax Pro, Outbound Call Limiting, Paging Pro, Park Pro, Pinset Pro, QXact, SysAdmin Pro, VM Notify, VM Reports, VQ Plus, Web Call Me, XactDialer) — 25Y $3,449, 1Y $1,729 (reseller: "worth over $4,252"). Note: EPM and Phone Apps are NOT in any bundle.
- Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/39092560 ; https://www.thetelecomspot.com/collections/freepbx ; https://www.voipsupply.com/sangoma-freepbx-everything-bundle-fpbx-c25y-eb-commercial-module-software

**FreePBX 17 (Debian 12) availability**
- FreePBX 17 GA 2024-08-02, PBXact 17 GA 2024-11-04; PHP 8.2 only — "commercial modules are not compatible with newer PHP versions"; Asterisk 21/22 (no chan_sip). Commercial modules are delivered from Sangoma's Debian repo via the official install script; Ubuntu is not supported for them. https://sangomakb.atlassian.net/wiki/spaces/FP/pages/222101505 ; https://sangomakb.atlassian.net/wiki/spaces/FP/pages/279052296 ; https://community.freepbx.org/t/freepbx-17-commercial-modules-for-ubuntu-22/99418
- Deprecated/removed in the 17 cycle: Zulu UC, Cxpanel/iSymphony (XactView), XMPP. Also on the deprecated list: Sangoma Phones Module (DPMA GUI), Bulk DIDs/Extensions, Camp-On, Magic Button, ARI, Bria Cloud, Sangoma Addons (G.729/DPMA licence loader), Java SSH, Bulk Phone Restart, Vega Management, Asterisk Phonebook. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41812064
- FreePBX High Availability (DRBD/Pacemaker) is EOL — "not supported on FreePBX 14+ and SNG7"; Advanced Recovery is the replacement. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22642992
- Modules documented as 17-capable in the wiki: Scribe (15/16/17), Advanced Recovery ("PBX 17+ improvements"), CDR Pro (MES needs Asterisk 20+), SAML, MFA, Sangoma Connect/Desktop (module versions 17.0.x listed), EPM, SysAdmin, Phone Apps/restapps. Everything else in the catalogue (Fax Pro, VQ Plus, QXact, CoS, Park/Page/Conference Pro, etc.) is still sold and listed in the module admin repos for 17 *(no single official "available on 17" list was found; inferred from current store listings and the 17 FAQ)*.

---

## 1. Fax Pro (module "Fax Configuration Professional", SKU FAX)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34177114 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/33882339
- Base (free) FreePBX only does inbound fax-to-e-mail; Fax Pro adds outbound faxing, per-user fax in the User Control Panel (UCP) and on-server storage/archiving of inbound and outbound faxes. No separate menu item — it unlocks extra settings in Fax Configuration, User Management, Inbound Routes and UCP.
- Global settings: default fax header, local station ID (TSID), outgoing e-mail address (From for faxes sent by e-mail), system fax e-mail, Error Correction Mode on/off, max/min transfer rate (14400/9600 recommended), default paper size Letter/A4.
- Company cover page: JPG logo upload, company name, address (1–3 lines), phone, web site, footer text; PDF preview button. Each user can add recipient name and a personal message per fax; sender name/phone/e-mail default from User Management and can be overridden per fax.
- Global dial prefix for outbound faxes so a dedicated outbound route (e.g. T.38-only trunk) can be used. Retries (global 0-3, per-user override). E-mail results Never/Always/Success/Failure (global + per-user override). Storage quota: max pages per user, Reject vs Delete-Oldest when full. "Concurrent Fax"/channel-control option (14+) lets UCP send one fax to multiple recipients.
- Per-user settings (User Management → Fax tab; also editable by the user in UCP → Fax → Settings): enabled, attachment format None/PDF/TIFF/Both, store locally, outgoing station ID, outgoing header, cover-sheet name/tel/e-mail, e-mail results, retries.
- Inbound route fax detection: Detect Faxes yes/no, detection type SIP (T.38/CNG) or DAHDI, detection time in seconds, fax destination (any "Fax Recipient: user"). Fax recipients become destinations in other modules.
- UCP fax widget: folders Inbox, Archived, Outgoing (live status: In Progress / Retrying / OK), Sent, Failed; columns date, from, to, status, pages; actions view PDF in browser, download, forward (to outside number or extension), delete; drag-and-drop upload of one or more PDF/TIFF documents; browser pop-up notification on new fax.
- T.38: module description says it lets you "configure and manage Asterisk T38 gateway options on each extension and outbound route". E-mail-to-fax (sending a fax by e-mailing the PBX) is NOT a Fax Pro feature — not documented anywhere; SIPStation offers T.38 in/outbound carrier side.
- Not supported on PBXact Cloud. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/12976475
- Pricing: 25Y $150 (FPBX-C25Y-FAX), 1Y $50 (FPBX-C01Y-FAX). In Starter and Everything bundles. https://www.thetelecomspot.com/collections/freepbx?page=4

## 2. EndPoint Manager (EPM, SKU EPM) + UCP for EPM (SKU UCPEPM)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/31064118 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/31096876 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/32080709 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/31097141 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/32702741 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35455566
- Brands provisioned: Aastra, Algo, AND, AudioCodes, Cisco (SPA and Enterprise 79xx/69xx SIP), Cortelco, CyberData, Digium, Grandstream, Htek, Mitel, Mocet, Obihai, Panasonic, Phoenix Audio, Polycom, Sangoma (S/D/P series, Vega FXS gateways), Snom, Uniden, Vtech, Xorcom, Yealink (22 brands; the Supported Devices table lists several hundred models with "certified / tested / background-image support" flags). Sangoma phones and Vega gateways do not need an EPM licence; all third-party phones do. Only "Extension mode" is supported (not Device & User mode).
- Global settings: internal IP, external IP/FQDN, ports pulled from SysAdmin Port Management (web, HTTP provisioning, REST apps), phone admin password and phone user password (min 6 chars, also used by Login REST app), resync interval, XML-API default login (hot-desking), show IP address and ping status in Extension Mapping.
- Per-brand templates: destination/registration address (internal/external/custom), time zone offset, NTP server, DST, background image, line label (name / ext / both), multicast paging enable + listen addresses, dial pattern, firmware slot, default ring tone (5 built-in), screen saver + timeout, headset/EHS priority, call waiting tone, BLF alert (audio/visual), hotline/off-hook auto-dial destination, provisioning server address and protocol (TFTP/FTP/HTTP/HTTPS), per-model button layouts.
- Button types (Sangoma): Line, BLF, Call Park, Conference, DTMF, Hold, Intercom, LDAP, Multicast Paging, Record, Redial, Speed Dial (commas = 500 ms pause, trailing + waits for more digits), Transfer, Voicemail, XML API (Phone App). Buttons can be drag-reordered; soft-key visibility per phone state (idle/hold/incoming/connected/dial/calling). Other brands have brand-specific sets (Aastra BLF/XFER, XML, Services, Call List; Grandstream Dial DTMF, Call Return; Polycom built-in New Call/Call Forward soft keys; Algo door-phone destination/relay digit, strobe cadence, pager volume; CyberData relay destination, door PIN codes 1-10, 15 paging zone dial codes; Grandstream FXS gateway T.38 vs passthrough fax mode). Expansion modules: up to 2 (Cisco, Grandstream, Obihai, Yealink, Xorcom) or 3 (Polycom, Snom) per phone, buttons configured like phone keys. Save / Save+Rebuild / Save+Rebuild+Update Phones (no reboot for Sangoma "Push Config").
- Extension Mapping: extension → MAC → brand/template/model/account (multi-account lets 2+ extensions share one phone, DECT bases/ATAs map several handsets/ports by account), expansion module selection, BLF substitution (replace self-BLF with another extension + label), VPN client pairing (SysAdmin Pro OpenVPN, Sangoma phones), colour status green/yellow (config stale), bulk rebuild/update, delete config.
- Network Scan: scans the PBX subnet for unprovisioned supported MACs and maps them to extension/template/model in one step. Custom Extensions: define extensions on other PBXs (number, secret, label, IP, port) for extra line keys.
- Image Management: upload GIF/JPEG/PNG ≤ 256 KB; EPM converts to each model's size/format (ImageMagick needed; Yealink background upload not supported).
- Firmware Management: two firmware slots per brand (drag versions from Sangoma's list), per-template slot selection; Custom Firmware Management GUI to upload third-party firmware (slot "0.0") per brand/model/version.
- Basefile Edit: edit or add any raw config parameter per template/model; survives module upgrades. Variables list exposed for basefiles.
- Zero-touch: Sangoma phones use PnP (SysAdmin 13.0.73+, same L2 segment) → DHCP option 66 → Sangoma redirect server rs.sangoma.net (order of precedence); Sangoma phones can also be configured via DPMA (Asterisk res_digium_phone) from EPM, D80 is DPMA-only. No Yealink RPS or Polycom ZTP/RPRS integration is documented in EPM (not found).
- Known limits: Cisco Enterprise no BLF, Polycom VVX 50 BLF entries, Grandstream line-key BLF issues, Mitel EOL, Snom no multicast listen, Yealink no background upload.
- UCP for EPM: lets end users change their own phone's (or other users' phones, by admin permission) button types/labels/values/accounts from UCP → Device Management, Save Model / Save & Restart, Reset to Template. Requires commercial EPM.
- Pricing: EPM 25Y $199 (FPBX-C25Y-EPM), 1Y $99; UCP for EPM 25Y $25, 1Y $13 (reseller notes UCP for EPM is now bundled with EPM). Free for Sangoma phones only. https://www.thetelecomspot.com/collections/freepbx , https://www.thetelecomspot.com/products/sangoma-freepbx-endpoint-manager-25-year-license-fpbx-c25y-epm

## 3. System Admin Pro (SKU SYS)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35618920 , feature matrix https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35422997 , sub-pages 35390162 (VPN), 35226461 (IDS), 35553787 (Updates), 35520980 (UPS), 35226488 (Storage), 35520890 (Ports), 35488206 (DDNS), 35455403 (HTTPS), 35619028 (Email), 35390087 (Notifications), 35553684 (Provisioning Protocols), 35259433 (DHCP), 35259412 (PnP), 35586286 (Network), 35520872 (Packet Capture)
- Free part of System Admin: Activation (deployment ID, licence update), DNS servers, Hostname, HTTPS Setup (assign Certificate Manager certs — including Let's Encrypt certs generated there — to Apache, cipher/protocol toggles), Intrusion Detection (fail2ban start/stop, ban time, max retry, find time, e-mail, whitelist, banned-IP list), Network Settings (static/DHCP per NIC, add secondary/alias and 802.1q VLAN interfaces), Notification Settings (from address; UPS, Safe-Asterisk crash, storage, intrusion, call-recording-archive, abnormal-call-volume e-mails), Port Management (Admin 80, UCP 81, HTTP provisioning 84, REST/GraphQL 83, RESTful Phone Apps 82, LetsEncrypt-only 80; custom ports, disable, force-HTTPS redirect), Power (shutdown/reboot), PnP, Storage (disk usage, RAID status, two thresholds with e-mail frequency), Support log dump, Time Zone.
- Pro-only: DDNS (Sangoma-assigned external FQDN that follows the detected public IP; force IP, update interval default hourly), Email Setup (built-in Postfix or external SMTP/Gmail with auth, debug/test mail), Provisioning Protocols (FTP server with credentials, TFTP enable, HTTP/HTTPS provisioning authentication with random user:pass), DHCP server (with Firewall Internet/Local zones, NAT), Packet Capture (start/stop, 500 MB rolling pcap, download/zip/delete), Support VPN (tunnel to Sangoma support), Updates (Distro OS updates and schedule — legacy ≤13; SNG7/17 update via Module Admin and OS tooling), UPS Server (apcupsd: cable/UPS type, device, on-battery delay, min battery %, min runtime, timeout, alert e-mail), VPN Server (built-in OpenVPN server: enable, server range default 10.8.0.0, redirect-gateway option, per-client enable/name/DDNS or remote address/fixed IP, link client to User Manager user → download config in UCP, assign to Sangoma phones in EPM; UDP 1194), Secure Provisioning (HTTPS provisioning only with Pro).
- Not in SysAdmin: "Power Fail" (no such feature; UPS handles shutdown), NTP server config (phones get NTP via EPM), firewall (separate free Firewall module).
- Pricing: 25Y $39 (FPBX-C25Y-SYS), 1Y $19; stated to carry no yearly maintenance fee. Included in Starter/Everything bundles. https://www.thetelecomspot.com/products/sangoma-freepbx-sysadmin-pro-25-year-license-fpbx-c25y-sys

## 4. Call Recording Reports (SKU CRR)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/62488691 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/62718047
- Reports → Call Recordings: list recordings by year/month (and day) with type (In/Out/Queue…), source, destination, date-time, duration; sort by any column.
- In-browser player (play/pause/replay/mute/seek), download WAV, delete single recording.
- Auto-archive: monthly archive on the 1st of recordings older than N months (recommend ≤ 3), stored as backup1-3.tar in /var/spool/asterisk/monitor, only three kept (oldest auto-deleted), reminder e-mail (to/from configurable) on archive creation; download archives as .tgz from Recording Archives tab.
- Filestore upload (v15+): push archives to any Backup/Filestore remote (FTP/SFTP/S3/Dropbox etc.), failure e-mail, status column, logs in /var/log/asterisk/recording_report.
- "Remove zero duration files" nightly cleanup.
- Not present: annotation/tagging, per-user access restrictions (admin module), e-mail of individual recordings, search by caller ID free text (filtering is by month and column sort). User-level recording playback is in UCP Call History (free) and transcription/tagging is in Scribe.
- Pricing: 25Y $99 (FPBX-C25Y-CRR; hssl.us $85.69), 1Y $50. Advanced/Everything bundles. https://www.thetelecomspot.com/collections/freepbx , https://hssl.us/freepbx-cm-call-recording-reports-25-year-license/

## 5. Queue Pro / VQ Plus (Virtual Queue Plus, SKU VQP)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35586407 , 35259658 (Virtual Queues), 35521271 (options in Queues), 35390529 (Penalty Rules), 35193846 (Queue Callback), 35226854 (Callback Report), 35292326 (Pause Codes)
- Queue Callback ("press 1" break-out, or via an IVR break-out menu): caller keeps place in line and is called back when their position reaches the front; options: callback caller ID, number prepend (route selection), allowed dial patterns for the number the caller may enter, callback into the same queue / another queue / a virtual queue, periodic announcement, number prompt, Force CID (no alternate number), "Handle Queue Announcements" by callback daemon (position/holdtime/periodic), allow caller to record a message played back on callback, confirmed/callback/accept prompts, answer timeout, retries and retry delay (AMD/no-answer → retry; failure forfeits position). Callback reports: Pending (with position), Successful, Failed (with reason), clear buttons.
- Virtual Queues: a destination that overrides a real queue's settings per call — CID name prefix, Alert-Info, MoH class, join announcement, language, max wait time, queue priority (VIP jump), queue position insert, agent announcement, call-confirm announcement, initial min/max penalty, penalty rule set, destination (real queue or later point), per-virtual-queue caller/agent post-hangup destinations and failover destinations.
- Queue Plus Options tab on each queue: Initial Min / Max / Raise penalty, Queue Penalty Rule set, Caller Post-Hangup destination (e.g. survey) and Agent Post-Hangup destination, separate failover destinations for FULL, JOINEMPTY, LEAVEEMPTY, JOINUNAVAIL, LEAVEUNAVAIL, Lazy Members (skip agent who already didn't answer this call; Sangoma Asterisk patch), Auto-Unpause-if-Life.
- Queue Penalty Rules (queuerules.conf GUI): ordered rules with duration since previous rule, new max / min / raise penalty as absolute or ±delta (raise penalty needs Asterisk 15+).
- Queue Pause Codes: define pause reason codes; *46<reason> pauses in all queues, *46<reason><queue> in one queue; reasons appear in reports.
- Queue Wallboard is a separate module (below). Standard FreePBX already has queue priority/weight, agent restrictions ("extensions only / no follow-me"), ring strategies, autopause, caller position announcements — VQ Plus adds the above on top.
- Pricing: 25Y $475 (FPBX-C25Y-VQP), 1Y $157. Call-Center/Everything bundles. https://www.thetelecomspot.com/collections/freepbx?page=4

## 6. Queue Wallboard (SKU QWB)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35292431 , 35815429 , 35749996 , 35750020
- Real-time queue statistics rendered as UCP dashboard widgets (any UCP user with permission; intended for a dedicated wallboard screen). Admin (Reports → Queue Wallboard) defines widgets; User Management → Queue Stats tab controls which widgets each user/group may add.
- Widget types: Abandoned Calls (per queue), Active Calls, Agent State (Busy/Idle/On Call for one agent in one queue), Agent Summary, Average Wait Time (graph over selectable averaging period), Caller Outcome Summary (answered / timeout / hung-up over 1 h–1 month), Clock (timezone, 12/24 h), Last 24 Hours of a Queue, Generic HTML/Text, Multiple Agent Summary (scrolling, mentioned in community). SLA % and summary stats are listed on the overview page.
- Remote servers: pull queue data from other FreePBX/PBXact systems (AMI user/password + MySQL credentials) for a single-pane multi-PBX wallboard.
- Widgets can be freely positioned/resized in UCP; optional footer text per widget.
- Pricing: 1Y $395 (FPBX-C01Y-QWB); no 25Y SKU found. https://www.thetelecomspot.com/collections/freepbx?page=2

## 7. Queue Reports — Q-Xact (SKU QXT)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34111833 , 33456817 , 33587730
- Template-driven queue reporting: 16 report types — All/Answered/Unanswered Call Distribution by Queue, Answered by Agent, All by Day, by Hour, by Day of Week, All/Answered/Unanswered Service Level (15-second buckets), Call Disconnection Cause, Call Detail List (all/answered/unanswered), Agent Availability Detail (login/logout/pause/unpause), Agent Missed Call Detail.
- Selectable columns per table: queue name, number/percent of calls, day/date/DOW/hour, service-level duration, agent, action, caller, inbound DID, unique ID, total/avg/min/max wait and talk time, ring time, call duration stats, disconnection reason/number/percent, original and abandon position.
- Run a template for a date range against selected queues/agents; export each table to CSV. Data retained 90 days by default (Advanced Settings).
- Report Scheduler: hourly/daily/weekly/monthly schedules with run windows, start/end dates or run forever, rolling start ("beginning of day/week/month", "now minus X"), e-mailed to a delivery address.
- Pricing: 25Y $795 (FPBX-C25Y-QXT), 1Y $263. Call-Center/Everything bundles. https://www.voipsupply.com/sangoma-freepbx-cm-q-xact-25-year-license

## 8. Class of Service (CoS, SKU CLS)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27361476 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27296334
- Create any number of classes; members are extensions (drag Exclude↔Include). An extension can be in several classes; Allow wins over Deny by default (switchable in Advanced Settings). Extensions in no class have full access.
- Per class, Allow/Deny lists for: Outbound Routes, Feature Codes, Ring Groups, Queues, Conferences, Paging groups, Voicemail Blast groups, Contact Groups (directory).
- Used by Property Manager for check-in/check-out room dialling classes (names starting with PMS-).
- When CoS is enabled it replaces Extension Routing's route allow/block UI.
- Not provided: PIN bypass of CoS (PIN behaviour lives in Pinset Pro; Pinset Pro's per-extension pinless dialing is per route), time-based CoS.
- Pricing: 25Y $99 (FPBX-C25Y-CLS), 1Y $50. Advanced/Call-Center/Everything. https://www.thetelecomspot.com/products/sangoma-freepbx-class-of-service-25-year-license-fpbx-c25y-cls

## 9. Extension Routing (SKU EXR)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/32572684 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/32441751
- Adds an "Extension Routing" allowed/blocked extension list to every Outbound Route (drag and drop) and an "Allowed Routes" checkbox list to every Extension (same data, two views; check/uncheck-all toggle).
- Blocking also blocks that extension's Follow-Me and Call-Forward numbers from the route; ring groups with external numbers are unaffected.
- Superseded/overridden by Class of Service when CoS is installed.
- Pricing: 25Y $39 (FPBX-C25Y-EXR). Starter/Everything. https://www.thetelecomspot.com/collections/freepbx?page=4

## 10. Conference Pro (SKU CP)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27492527 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27492542 , desktop admin guide https://sangomakb.atlassian.net/wiki/spaces/PG/pages/868188161
- UCP Conferences widget: users see the rooms they are allowed (User Management → UCP → Conferences: enable, allowed bridges), live participant list, mute/unmute and kick users, and edit room settings live: user PIN, admin PIN, join message, max participants, leader wait, talker optimization, talker detection, quiet mode, user count, join/leave announce, MoH on/off and class, allow * menu, record conference, mute on join.
- Conference IVR ("Conference List IVR" destination): per-room "Add to Conference IVR" flag, selectable announcement; callers dial the room number from the IVR.
- "Link Conference to this user" in User Management creates a personal conference room per user (shown in Sangoma Desktop). 
- Phone Apps "Conference Rooms" app and Sangoma Desktop conference tab use the same rooms (ConfBridge required for desktop).
- Not provided: invite-by-dial-out from UCP (the UCP text mentions "invite contacts" but no dial-out control is documented), web/video conferencing (that is Sangoma Meet).
- Pricing: 25Y $30 (FPBX-C25Y-CP), 1Y $15. Starter/Everything. https://www.thetelecomspot.com/collections/freepbx?page=2

## 11. Voicemail Notify — VM Notify (SKU VMN)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34833983 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35390265
- Monitors a mailbox; on new message calls a recipient list (internal or external numbers) in priority groups (all numbers of priority 0 simultaneously, then priority 1, …) until someone presses 1 twice to accept; 2 declines; 3 plays caller ID. Only one recipient can claim; answering machines cannot accidentally accept.
- Settings: Outbound CID mode Default/Fixed/Mailbox/Force Mailbox, fixed CID, CID name, initial greeting and instructions recordings, retry count (cycles), retry delay (min), priority delay (min), enable/disable toggle.
- E-mail on success and/or failure with templated subject/body ({{STATUS}}, {{CALLERID}}, {{MAILBOX}}, {{TIME}}, {{LENGTH}}, {{ACCEPTEDBY}}, {{ID}}, {{RETRY}}, {{PRIORITY}}, {{LOG}}), optional WAV attachment; the voicemail is deleted from the mailbox after e-mail is sent. UCP widget available.
- Pricing: 25Y $75 (FPBX-C25Y-VMN), 1Y $38. Advanced/Everything. https://www.thetelecomspot.com/products/sangoma-freepbx-vm-notify-25-year-license-fpbx-c25y-vmn

## 12. Voicemail Reports (SKU VMR)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35226647 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35423268
- Reports → Voicemail: Greetings & Settings tab per mailbox — password (shown in clear), whether Name/Busy/Unavailable/Temporary greetings are recorded (with in-browser playback), e-mail attach address, delete-after-e-mail flag.
- View Voicemails tab: every message on the system — mailbox, date, folder, caller ID, duration, playback (play/pause/loop/mute).
- No password-strength scoring, no usage graphs beyond the list, no export documented.
- Pricing: 25Y $25 (FPBX-C25Y-VMR; hssl $21.64), 1Y $13. Advanced/Everything. https://www.thetelecomspot.com/collections/freepbx?page=2

## 13. Park Pro (SKU PARK) and Park & Announce
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34046313 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/33424262 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/33489572
- Multiple parking lots (free module has one "Default" lot). Per lot: parking extension, name, starting slot, number of slots, timeout (s), parked MoH class, Public (anyone can park into it) or Private (only extensions assigned to the lot; *85 pickup prefix still works from anywhere), BLF hints per slot, Find Slot First/Next, pickup courtesy tone (caller/parked/both/none), DTMF transfer capability, re-park capability, Alert-Info on return, CID prepend text + auto prepend (Slot/Extension/Name), announcement before return, Come-Back-to-Origin yes/no, timeout destination (any destination).
- Each extension is assigned a parking lot (Extensions → Other → Parkinglot); desktop app and Phone Apps "Parking" app use the user's lot. "Park on extension"/call-park-to-extension (Asterisk "park on busy ext") is not a Park Pro feature (not found).
- Park & Announce (needs Park Pro + Page Pro): its own extension/destination; optional caller-recorded message (prompt, max length, silence detect, success/failure prompts); target lot, pre-park announcement, timeout override, retry count with retry announcement (auto re-park N times), timeout destination (never returns to origin); page group, CID prepend, auto slot prepend, announce slot number, up to three system recordings, drag-and-drop announce order (e.g. "Sales call from <caller name>, parked on <slot>").
- Pricing: 25Y $125 (FPBX-C25Y-PARK), 1Y $50. Starter/Everything. https://www.thetelecomspot.com/collections/freepbx?page=2

## 14. Page Pro / Paging Pro (SKU PAGE)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34144404 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34275520
- Adds to each page group in Paging & Intercom: Busy Page Group handling Do Nothing / Valet / Force Valet (valet = record the page, play when group free; force valet = always record-then-play "airport style"); Page Announcement (no beep, beep, or a system recording played before the pager talks or before a valet page); CID prepend; RTP Multicast streams (IP:port list — phones receive via multicast instead of individual calls); Scheduler with server-time display, schedule date range, weekly day/time events (15-min picker, free text allowed), exclusion dates (holidays) — plays the page announcement recording to the group (school bells, shift buzzers).
- Outbound Notifications: link a page group to an Outbound Route (Additional Settings → Notifications); when a call goes out that route (e.g. 911) the group is paged with the calling extension and dialled number and members can press *1 to barge into the call.
- Enables Park & Announce together with Park Pro.
- Standard (free) module already provides page groups, duplex/intercom, skip-busy, force page, announcement-before-page is Pro. Priority paging and "paging to Sangoma phones" are standard SIP paging/multicast (multicast listen addresses are set in EPM templates).
- Pricing: 25Y $95 (FPBX-C25Y-PAGE), 1Y $48. Starter/Everything. https://www.thetelecomspot.com/collections/freepbx

## 15. Sangoma Property Management (SPM, SKU SPM) + Oracle Connector + BrainBox
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35782839 , 35717338 , 35782916 , 35946674 , 36175958 , 35946818 , 35226116 , 132087846
- Hotel/B&B/hostel PMS built into FreePBX/PBXact; staff use a UCP dashboard ("Pms"); free up to 10 rooms, "Property Manager Pro" licence for unlimited rooms.
- Config (Applications → Property Manager): operating mode (Hotel default), lock room phone at check-out (calls redirect to reception), call between rooms on/off, room-must-be-clean before check-in, logo/address/e-mail, invoice e-mail template, receptionist extension or ring group, emergency route (alerts receptionist + web redirect to emergency page), default CoS for check-in and check-out (CoS names prefixed PMS-; custom context if no CoS licence), taxes (combinable), tourist tax %, discount %, call-duration rounding, currency, scheduled discounts/room-rate changes by date, HTML customer ticket, room types (price, extra-guest price, taxes), rooms (name, extension, type), billing rates per outbound route (billing duration, digit mask for privacy, prefix, connection charge, price), up to 14 maid-service codes (TTS or audio, priority), RAC remote-access-control URLs per room for check-in/out (IP relays/door locks), UCP privileges per staff group (Receptionist, Accounting, Restaurant, Hotel Guests).
- Dashboard: occupancy pie, booking (arrival/departure, room, name, language, e-mail, voicemail password, payment mode/advance, address, ID/TIN), check-in (auto-creates guest UCP account and voicemail, extra guest), check-out (now/scheduled/other date, group, payment method, discount, itemised calls and mini-bar, PDF invoice stored and e-mailed; resets voicemail and DND), wake-up calls per room, room list with guest details, SMS-to-phone text message to room phones (Sangoma/Yealink/Grandstream), room transfer (keeps voicemail/UCP), per-room CoS/call restriction, room status clean/dirty, mini-bar charges, guest messages to reception, reports.
- Phone App "SPM/My Room" on Sangoma phones: send predefined text to reception, e-mail secret codes, set room clean/not clean, view mini-bar, set/see/delete alarm clock, call count.
- Oracle Connector add-on (PBXact, requires SPM licence): Oracle Hospitality OPERA/Fidelio FIAS-style link — PMS→PBX: check-in, check-out, room move, room update, reminders (wake-ups), DND, COS, guest name (name shown on room phone); PBX→PMS: call accounting, room status, mini-bar, notifications. *(Micros/Fidelio protocol name not stated on the page; it is "Oracle-certified").*
- BrainBox (third-party by Graymatter Networks, sold via FreePBX store): hospitality suite with reporting, room phone management and integrations with "various Property Management Systems"; support by Graymatter, not Sangoma.
- Pricing: SPM free ≤ 10 rooms; Property Manager Pro 1Y $195 (FPBX-C01Y-SPM, annual); reseller lists PBXact tiers $345 (300 rooms) and $495 (1,000 rooms) per year *(reseller figures)*. Oracle Connector and BrainBox prices not found. https://www.thetelecomspot.com/products/freepbx-cm-spm-sangoma-property-manager-pro-1-year-license

## 16. Appointment Reminder (SKU AR)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26477189 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26575099 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26020013
- Multiple reminder campaigns; global max simultaneous calls. Per reminder: enabled, daily start/end time window, max advance notice (days before appointment), retry count and retry delay (hours; rolls to next day if outside window), TTS engine for saying the name (flite default), fixed caller ID / CID name / default-vs-fixed CID mode.
- Call flow: initial greeting (custom recording), say recipient name (TTS), date announcement + spoken appointment date, instructions ("1 confirm, 2 cancel, 3 reschedule"), 0 → customer-service destination, reschedule behaviour Transfer (to destination) or Log for Callback.
- Recipients: add manually (name, number, date/time), CSV upload (Name, Number, "YYYY-MM-DD HH:MM:SS", optional 4th column add/update/delete; "*" date deletes all for a name/number), one-time upload actions (use command column / append / replace / merge), or scheduled automatic CSV download over HTTP/FTP every N seconds (min 300) with delete-after-import (FTP).
- Reports: per reminder, date range, filter by appointment date or call date, sort by name/call status/appointment date/call date, on-screen or CSV; daily completion e-mail with CSV/text attachment.
- Not provided: SMS/e-mail reminders (voice only), answering-machine-specific handling.
- Pricing: 25Y $795 (FPBX-C25Y-AR), 1Y $263. Advanced/Everything. https://www.thetelecomspot.com/collections/freepbx?page=4

## 17. Broadcast / XactDialer (SKU XTD)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26477706 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27263270
- Outbound message-broadcast dialer (explicitly "not a predictive dialer"). Call Groups: name, manual entries, CSV import ("Name",Number,add|remove), or HTTP/FTP URI auto-import with update period and delete-after-retrieve.
- Campaigns: name, concurrent calls, campaign caller ID, dial prefix (route selection), e-mail reports (never / daily after end time / after completion), active flag, one or more call groups, schedule (dates/times), destination when a live person answers vs destination when answering machine/voicemail answers (Asterisk AMD), duplicate campaign.
- Service Status tab: start/stop broadcast service, per-campaign active checkbox, placed/remaining counts, CSV report (callee, number, dialled, answered, delivered_to person/machine), mark complete, restart, delete. General: global concurrent calls, max retries for busy, report from-address.
- Remote toggle: campaigns can be activated/deactivated by dialling a destination (e.g. hidden IVR option) — school-closing use case.
- No DNC list, survey/IVR scoring or SMS; destinations can be any FreePBX destination (IVR, announcement, queue).
- Pricing: 25Y $795 (FPBX-C25Y-XTD), 1Y $263. Call-Center/Everything. https://www.thetelecomspot.com/collections/freepbx?page=3

## 18. Caller ID Management (SKU CIDM)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26772576 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27394176
- Table of CID presets: name, feature-code prefix (auto-generated, editable), CID name, CID number, Persistent yes/no (next call only vs until changed). User dials the prefix (optionally followed by the number) to send that CID; requires a trunk that honours per-call CID.
- Not provided: per-user selectable CID list in UCP/softphone, time-based CID, DID-based automatic CID (that is in standard Extensions/Outbound Routes).
- Pricing: 25Y $65 (FPBX-C25Y-CIDM), 1Y $33. Advanced/Call-Center/Everything. https://www.thetelecomspot.com/products/sangoma-freepbx-caller-id-management-25-year-license-fpbx-c25y-cidm

## 19. Outbound Call Limit (SKU OCL)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34177148 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/33882399
- Compliance limiter: limits how many times the SAME destination number can be called through a given outbound route per period (not per-extension concurrency). Up to three limit lines per rule (N calls per X hours/days/months, all evaluated), "limit reached" recording, rule attached in Outbound Route → Additional Settings → Call Limit.
- Pricing: 25Y $195 (FPBX-C25Y-OCL), 1Y $65. Call-Center/Everything. https://www.thetelecomspot.com/products/sangoma-freepbx-outbound-call-limit-25-year-license-fpbx-c25y-ocl

## 20. Pinset Pro (SKU PIN)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34111801 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34177317 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/33489704
- Extends free PIN Sets (PIN list per outbound route, record PIN in CDR accountcode) with per-extension "Pinless Dialing" switches per route (e.g. CEO bypasses the international PIN) and per-extension PIN association.
- Reports → Pinsets Code Reports: filter by date range, source, destination, duration, billable time, account code (PIN); Summary (billable hours) and Detailed (date/time, account code, src, dst, duration, billable time) CSV downloads.
- Pricing: 25Y $45 (FPBX-C25Y-PIN), 1Y $23. Advanced/Call-Center/Everything. https://www.thetelecomspot.com/collections/freepbx?page=4

## 21. Web Callback / Web Call Me (SKU WCM)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35193874 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35226900 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35554153
- Generates an HTML/JS "Call Me" widget to paste into any web site; visitor enters a number, PBX originates a call to the visitor and connects it to a chosen destination (extension, queue, IVR …).
- Per callback: name, CID name prepend, number prepend (route), allowed dial patterns, icon choice, valid/invalid/error messages, destination; generated HTML; fully custom form possible via /etc/schmooze/wcb.html posting to /wcb.php (PBX web port must be reachable from the web site).
- Pricing: 25Y $50 (FPBX-C25Y-WCM), 1Y $25. Advanced/Call-Center/Everything. https://www.thetelecomspot.com/collections/freepbx?page=2

## 22. CRM Link (Sangoma CRM, SKU CRM) + Zapier + REST API
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/27263360 , 29491369 , 29196603 , 169410602
- Supported CRMs: Salesforce, SugarCRM 6.5/8.0 (needs module installed in Sugar), SuiteCRM (listed via Sugar family — the wiki names Sugar; SuiteCRM support *uncertain*), Zoho CRM, ConnectWise, and a "Generic API" option to connect any CRM via the published API.
- Features: push every call's history (CDR) to the CRM and attach to matching Contact/Lead/Account; link to or upload call recordings into the CRM (not ConnectWise); upload voicemails to the CRM linked to call history (not ConnectWise); click-to-call from the CRM and inbound screen-pop with create-Account/Contact/Lead — originally via the Zulu UC browser plug-in; today via Sangoma Connect Desktop (SCD) call pop-up URL into Salesforce (documented) or the generic browser pop-up URL with %CALLER_ID_NUMBER%/%CALLER_ID_NAME%/%INCOMING_DID%.
- Sangoma CRM REST API (token auth on the admin web port): GET calls by uniqueid, lists (both/inbound/outbound with since/limit/offset), recording and voicemail streams, users by extension/id, webhooks CRUD (inbound/outbound/both URL posts).
- Zapier integration (since 2021, requires licensed CRM module): triggers on new inbound/outbound calls, search call data; examples for Slack, Gmail, Salesforce, Excel, Dynamics 365, Google Calendar/Sheets, SugarCRM 7+.
- Included free on PBXact; FreePBX add-on.
- Pricing: 25Y $275 (FPBX-C25Y-CRM), 1Y $91. Call-Center/Everything. https://www.thetelecomspot.com/collections/freepbx?page=4

## 23. Phone Apps / RESTful Phone Apps (SKU PHA)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/34046391 , 35389951 , 34079071 , 35291903 , app pages 34210130–35226224
- Requires commercial EPM (free for Sangoma S/D/P phones; licence needed for third-party phones). XML/REST apps launched from a phone button (XML-API key type) or app menu; a restapps daemon drives BLF light states and centre-screen notifications.
- Apps: Call Flow Control (toggle Normal/Override per call flow), Call Forward (enable, store home/cell/office), Conference Rooms (see callers, mute/kick, dial in), Contacts (Contact Manager groups, search, dial), Do Not Disturb (toggle, BLF), EndPoint Login/Logout (hot-desking; updates EPM Extension Mapping; "XML-API default login" template), Follow Me (toggle/manage), Parking (see/pick up/park calls; Park Pro aware), Presence (set status: Available/Away/Chat/DND/… synced with UCP/XactView/XMPP), Queue Agents (log in/out, pause/unpause per queue), Queues (admin view of agents/callers per queue), Time Conditions (force match/unmatch temporarily or permanently), Transfer to Voicemail (button only), Visual Voicemail (list, choose which to play), SPM/My Room (hotel). BLF colour semantics table per app (green/red/blinking).
- Supported devices: Sangoma s305/s4xx/s5xx/s7xx, D40/45/50/60/62/65/70 (D6x/D80/P-series use the next-generation DPMA phone apps); limited/best-effort on Aastra 67xx/68xx/9xxx, Yealink T2x/T3x/T4x/T5x/VP530, Obihai 1022 (feature matrix per model: BLF, centre-screen notifications, soft keys, etc.). Polycom and Digium (D-series are now Sangoma) are not in the current REST apps matrix; Polycom phone apps are not listed.
- User permissions per app in User Management → Phone Apps; port set in SysAdmin Port Management (default 82).
- Pricing: 25Y $499 (FPBX-C25Y-PHA), 1Y $165. Not in bundles. https://www.thetelecomspot.com/products/sangoma-freepbx-phone-apps-25-year-license-fpbx-c25y-pha

## 24. Contact Image
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35946940
- Adds a tab to an Extension (e.g. a door phone) so that calls from that extension push a live still image fetched from the device's HTTP/HTTPS URL (relative path appended to the endpoint IP, optional basic-auth user/password) to Sangoma phones instead of the contact avatar. Tested with Alcatel IP80 door phone.
- Pricing: "commercial module, buy from the portal" — price not found.

## 25. CDR Pro (SKU CDP)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22282324 , https://www.freepbx.org/add-on/cdr-pro/ (price via search)
- Unifies all legs of a call into one record (own table; `fwconsole cdrpro --sync` back-fills 6 months). Predefined reports: All, Inbound, Outbound, Internal, Answered, Missed, DID Summary, Ring Group, Queues, Extension Details; predefined or custom date/time ranges; graphical view (call type, disposition, hourly volume, hourly average MES) and tabular view with call legs, CEL events, recording play/download; export CSV/Excel/PDF/JSON (graphs to PDF).
- Media Experience Score (Asterisk 20+) per call. Report Scheduler with daily/weekly/monthly/custom frequency, e-mail template, attachment format; "run now" test. UCP CDR Pro widget. New calls appear within 10 minutes.
- Included in PBXact Cloud base; FreePBX add-on with free trial.
- Pricing: 1Y $299 (FPBX-C01Y-CDP), annual only. https://www.thetelecomspot.com/collections/freepbx?page=2

## 26. PBX Call Accounting (SKU CA)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35914096
- Cost allocation for inbound and outbound calls (FreePBX 14+): multiple Rate Decks (dial-pattern → rate, with mandatory Time Group column for peak/off-peak), add patterns manually or bulk CSV import/export via Bulk Handler (numeric patterns only, no wildcards), assign decks to Trunks (inbound billing requires trunk deck) and to User Manager users or groups, priority setting when user and trunk decks differ, dashboard with calls/cost today, reports (CDR summary + detailed) filtered by date range, source, deck, user, group, exported CSV/PDF. Sample SIPStation international rate deck provided.
- Pricing: 1Y $400 (FPBX-C01Y-CA), annual only. https://www.thetelecomspot.com/collections/freepbx?page=3

## 27. Advanced Recovery (SKU ADR) — and the history of FreePBX High Availability
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35783290 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/36241708 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22642992
- Warm-spare replication + optional automatic switchover between a Primary and an identical Secondary (FreePBX 15+; licence required on BOTH servers; depends on Backup & Restore, API, Filestore; SSH keys both ways; `fwconsole advr --precheck` on 17+).
- Quick Configuration wizard: secondary IP, sync frequency (cron), Auto Switch services with threshold, Disable Remote Trunks on secondary, exclude NAT / bind address / DNS settings from restore, apply config after restore; notifications by call to an extension (separate recordings for primary-failed and standby-failed) and e-mail; failure notification frequency.
- Monitors network interface, Asterisk, MySQL and PBX stack; switchover hooks for custom/third-party scripts; control of primary services after failback; per-trunk activation choices after switchover; EPM integration rebuilds Sangoma S/D phone configs to point at the secondary; dashboard with service status, last sync, Sync Now; Expert configuration page for extra files/dirs.
- No floating IP / DRBD; phones must re-register to the secondary (EPM push or DNS).
- FreePBX HA (old module, FPBX-C25Y-HA): DRBD + Pacemaker + floating IP, chan_sip only, Distro 10.13.66 or older; EOL and unsupported on 14+/SNG7/17; reseller listing now redirects to an unrelated product. PBXact "High Availability (license per PBX node)" on the features page refers to this legacy option *(current PBXact HA offering uncertain; Advanced Recovery is the shipping product)*.
- Pricing: 1Y $400 per server (FPBX-C01Y-ADR), annual only. https://www.thetelecomspot.com/products/freepbx-cm-advanced-recovery-1-year-license

## 28. MFA Module (Multi-Factor Authentication for the admin GUI)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/36241789 (+ child pages)
- OTP factors for Admin GUI logins: e-mail OTP (30-min expiry, 3 attempts, resend limits), call to the user's extension (press #), authenticator app TOTP (QR by e-mail; Google/Microsoft Authenticator), user-choice of factor at login, 10 single-use recovery codes, "trusted device" for 30 days (not in incognito).
- Pricing: "Starting in April 2025, this module is now $0" (was $18 per admin per year, FPBX-C01Y-MFA-01U).

## 29. SAML Single Sign-On (module pbxsaml)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/925106179 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/1095172124 (+ Entra/Okta/Google setup pages)
- SAML 2.0 SSO for the Admin Control Panel, UCP and the Sangoma Phone Desktop client; IdPs: Microsoft Entra ID, Okta, Google (one IdP at a time); wizard accepts IdP metadata upload or manual Entity ID / certificate / ACS; HTTPS with valid cert required; matches on user e-mail (must be unique in User Manager).
- Pricing: annual auto-renewing licence sized by number of SAML users, one per Deployment ID, in PBXact Add-Ons and PBXact.cloud (monthly); price not published on the wiki.

## 30. Scribe (AI transcription, summaries, sentiment, TTS)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/488898594 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/488800289 , https://portal.sangoma.cloud/scribe/ , https://www.voipsupply.com/sangoma-scribe-ai-transcription-services
- Released 2024 for FreePBX/PBXact 15/16/17; cloud LLM-based transcription of voicemails, call recordings and uploaded audio ("Scribe your audio"); multi-language; AI summary; sentiment analysis (positive/neutral/negative, dashboard and per-call timeline); synchronized playback view (click text to seek); PDF export; share by e-mail; "Scribe Rewind" retroactive transcription of past recordings; Scribe Tags (keyword tags for search/alerting/reporting); Text-to-Speech generation of System Recordings from typed text; stereo/multichannel recording option for diarization; usage/cost predictor (works before licensing).
- Enablement per user/group in User Management for voicemail and for call recordings (choose call types); Voicemail-to-Email gets {VM_PBX_SCRIBE} transcript variable (Scribe takes over the mail command); transcripts visible in UCP (Call History, CDR Pro, Voicemail widgets), Sangoma Desktop, Sangoma Talk, web phone, and the admin dashboard (report types all/inbound/outbound/internal/voicemail, date range, tabular/graph).
- This is Sangoma's only voicemail-transcription product; no Google/IBM Watson speech-to-text module exists from Sangoma (community scripts only).
- Pricing: monthly subscription FPBX-C01M-SCRIBE $24.99 per PBX including 1,000 shared minutes/month (unused minutes do not roll over), Top-Up FPBX-C01M-SCRIBETUM $39.99 for 1,000 minutes valid 3 months (requires active subscription), overage $0.04/min listed on the Sangoma cloud portal.

## 31. Sangoma Softphones: Sangoma Talk (mobile), Sangoma Phone Desktop, browser phone, Advanced Queue licences (module "Sangoma Connect"/sangomaconnect + sangomartapi)
Sources: https://sangomakb.atlassian.net/wiki/spaces/SS1/pages/31162802 , 31392017 , 31392032 , 31097192 , 31162639 , 809631750 , 868188161 , 865566958 , 31293688 , 31260975 , 522256385 , https://www.freepbx.org/add-on/desktop-and-mobile-integration/ (via search), https://www.thetelecomspot.com/collections/freepbx
- Naming: FreePBX blog "Sangoma Connect" (2020) = wiki "Sangoma Talk" mobile app (iOS/Android, Acrobits-based "cloudsoftphone" stack) + "Sangoma Phone Desktop" (Windows/macOS; Linux via browser). The PBX module is "Sangoma Connect"; the store product is "FreePBX Softphones". One Softphones user licence covers mobile and desktop for that user; PBXact includes one softphone licence per extension licence (max 1,000); FreePBX buys them; a free 2-user/1-year trial exists; existing Zulu licences carried over.
- Sangoma Talk mobile: provisioning by "magic link" e-mail from User Management (or admin-copied deep link); PJSIP extensions only (chan_sip workaround documented); unique e-mail per user; one PBX/one device per user; transports UDP/TCP/TLS (SRTP "secure calling" option); push notifications via Sangoma push servers that register to the PBX on the app's behalf (whitelist all.sipis.acrobits.cz IPs in Firewall/fail2ban; `fwconsole sc` creates firewall rules); Sangoma Cloud (connect.sangoma.com, US/Canada) proxies provisioning/auth/contacts — SIP credentials not stored there; single registration FQDN (LAN/WAN via DNS); features: blind and attended transfer, local 3-way, 1:1 video (Asterisk 16+, h264), contacts with Gravatar avatars, favourites/quick-dial with BLF, history, keypad DTMF, hold, scheduled DND, visual voicemail, SMS/MMS to external numbers via SIPStation DIDs (no co-worker chat in Talk), E911 location, Sangoma Meet integration for multi-party video, Scribe transcripts; ~1 GB per 1,000 minutes.
- Sangoma Phone Desktop (FreePBX/PBXact 15+, Asterisk 16+/18+ recommended, ConfBridge, TLS+WSS, RTAPI secure port, HTTPS): make/receive calls, blind transfer, call log, visual voicemail (+Scribe), favourites with BLF and presence icons, presence, chat (1:1, group DMs, public/private rooms, attachments with admin storage quota), chat room → conference, chat-to-SMS (SIPStation or VoIP Innovations DIDs; per-user default outgoing DID; 1:1 only), call park/retrieve in the user's lot, conference room view with admin PIN controls (mute/unmute/kick/end), merge calls into ad-hoc conference, on-demand call recording, call pop-up URL in default browser (CALLER_ID_NAME/NUMBER/INCOMING_DID; prefix strip), emergency location (per-location DID), external/private contacts (synced to UCP), originate calls from desk phone ("Making calls with: Desk Phone"), Call Activity groups (see other users' calls; Monitor/Whisper/Barge with permission), My Queues (login/logout/pause with reason), languages EN-US/UK, FR, DE, IT, ES; SAML login; Outlook click-to-dial and browser click-to-call listed on the PBXact features page.
- Browser phone (https://phone.sangoma.com): no install, same feature set incl. advanced queue monitor/whisper/barge, visual voicemail + Scribe, call logs, contacts, optional chat; needs sysadmin 17.0.2.32/16.0.49.12/15.0.33.31+, sangomartapi 17.0.9.18+, restapps 17.0.1.39+, sangomaconnect 17.0.3.25+, HAProxy rebuild; no click-to-call/tel: handler yet.
- Advanced Queue licences (desktop/web): Supervisor licence per supervising user (queue call control: move call to top, answer from queue, assign call to agent, log out dynamic agents; Monitor/Whisper/Barge) and Queue licence per monitored queue; permissions Detailed View / Queue Call Control per queue in User Management; reload is blocked if more queues are configured than licensed. Wiki worked examples: Supervisor $6/licence/year, Queue $60/licence/year (e.g. 5 supervisors + 10 queues = $630/yr). PBXact also needs these add-ons for supervisor features.
- Status page: Sangoma Talk/Desktop show "Expired-License" and only emergency calls when support/maintenance lapses (see §0).
- Pricing: FreePBX Softphones 1 user 1Y $19 (FPBX-C01Y-ZULU-01U), 20 users 1Y $299 (FPBX-C01Y-ZULU-20U); annual only; included with PBXact. https://www.thetelecomspot.com/products/sangoma-connect-zulu-for-freepbx-1-user-1-year-license

## 32. Zulu UC, XactView V3 / iSymphony, XMPP — discontinued
Sources: https://sangomakb.atlassian.net/wiki/spaces/FP/pages/279052296 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41812064 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35521337 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25952518 , https://community.freepbx.org/t/zulu-desktop-download-link/89078 , https://community.freepbx.org/t/xactview-replacement-for-pbx-17/106465 , https://www.voipsupply.com/sangoma-module-renewal-connect-zulu
- Zulu UC (desktop/mobile softphone, chat, SMS, fax, CRM click-to-call/screen-pop browser plug-in, Outlook): deprecated during FreePBX 17 development and not available on 17; retailer renewal SKUs marked discontinued; replaced by Sangoma Talk/Phone Desktop (licences transfer 1:1). Community notes Zulu was retired by 2023.
- XactView V3 / iSymphony (operator panel: live call view, drag-drop transfer, presence, queue/agent panels, user packs and queue licences PBXT-OPT-XVW-U020/Q001): module deprecated; reseller SKUs discontinued; not on PBXact/FreePBX 17; no official replacement — community uses FOP2, UCP Queue Wallboard and Sangoma Desktop queue/call-activity views.
- XMPP Chat Management (Let's Chat/Prosody-style IM + UCP chat): deprecated in 17; chat now lives in Sangoma Desktop.
- Sangoma Addons module (G.729 / DPMA licence loader) and Sangoma Phones Module (DPMA GUI) are also deprecated; DPMA for Sangoma D/P phones is driven from EPM.

## 33. Sangoma Meet (video meetings)
Sources: https://sangomakb.atlassian.net/wiki/spaces/SS1/pages/31162802 , https://meetings.sangoma.com/ , app-store listings via search
- Browser/mobile multi-party video meetings with screen sharing and recording; integrated as the "multi-party video" button in Sangoma Talk and Sangoma Phone Desktop; still actively published (app release Oct 2025, release notes 2024 on the wiki). Offered free of charge at launch (2020); no current FreePBX/PBXact price list found *(licensing today uncertain — appears bundled with Softphones/PBXact)*.

## 34. SMS and SIPStation trunking integration
Sources: https://sangomakb.atlassian.net/wiki/spaces/SAF/pages/16121901 , https://sangomakb.atlassian.net/wiki/spaces/SAF/pages/15925665 , https://www.freepbx.org/sms-and-tls-for-sangoma-connect/ (via search), https://github.com/simontelephonics/smsconnector
- SIPStation module (free in FreePBX) auto-provisions trunks, routes and DIDs from a Sangoma SIPStation account; 20-day free trial from the GUI; per-DID e911 management from the PBX; T.38 inbound (free) and outbound (metered); per-DID failover numbers, trunk groups across sites, dual data-centre registration, global failover; Fraud Guard caps on international calling; IP ACL/registration alerts.
- SMS: Sangoma supports SMS/MMS only on SIPStation (and VoIP Innovations for desktop chat) DIDs; send/receive in UCP SMS widget, Sangoma Talk mobile, Sangoma Phone Desktop chat; SMS is a metered add-on enabled in the SIPStation account; DIDs from off-net rate centres may not support SMS; no SMS-to-e-mail feature. Third-party "SMS Connector" module (open source) adds other providers on 16/17; "SMS Plus" adds blocking.

## 35. PBXact — what it adds over FreePBX, licensing, support
Sources: https://sangomakb.atlassian.net/wiki/spaces/PP/pages/11894963 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/11829483 , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/12976475 , https://www.thetelecomspot.com/products/pbxact-sofware-base-system-new-deployment , https://community.freepbx.org/t/why-is-the-pricing-so-annoying-1-375-over-25-years-for-the-pbxact-iso-over-an-appliance/89153 , https://www.voipsupply.com/blog/voip-insider/sangoma-support/ , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/1878425608
- PBXact = FreePBX with the commercial modules bundled under a per-user licence (appliance sizes 25/40/60/75/100/300/400/1200/2000/5000 users, or software-only). "Enhanced features (known as Commercial Modules in FreePBX)" included: Call Recording Reports, CDR Pro, Class of Service, Conference Pro, EndPoint Manager (Sangoma phones; third-party phone support is an add-on licence per user), Extension Routing, Fax Pro (not on Cloud), MFA, Park Pro, Page Pro, Phone Apps (Sangoma phones), SysAdmin Pro, UCP for EPM, VM Notify, Voicemail Reports, CRM Link, XMPP Pro (legacy), Advanced Recovery; plus one Sangoma softphone (Talk + Desktop) user licence per extension licence (cap 1,000). Not included: the "Call Centre" bundle (XactDialer, Outbound Call Limiting, Appointment Reminder, Pinset Pro, Queue Pro/VQ Plus incl. callback, Web Callback, Q-Xact, Call Recording Reports per the call-centre table), Queue Wallboard, Property Manager Pro, Oracle Connector, Call Accounting, Advanced Recovery licence, third-party phone support, SAML, Scribe, desktop Advanced Queue licences — all PBXact add-ons.
- Licensing: software-only base PBXT-DEPLOY-BASE $450 (or PBXT-UPGR-BASE to convert a FreePBX deployment) plus a per-user licence (Sangoma staff forum figure $8/user one-time, 2019–2020 *(dated)*); requires a Bronze/Gold/Platinum support plan (SKUs SVCM-PBXT-{BRONZE,GOLD,PLAT}-{BASE,USER} first year and 1YR/3YR renewals; prices not public). Appliances include first-year POMPs; all PBXact systems require an active POMPs (Peace of Mind Package) to receive updates — Bronze = updates/licence maintenance only, Gold/Platinum add support credits (30/60 or 60/120 depending on source) and Platinum 24/7 outage support; hardware warranty one year, extendable. POMPs expiry triggers the same grace-period/blocked-module behaviour as FreePBX maintenance.
- PBXact Cloud: same enhanced features in the base monthly price except Fax Pro; EPM/Phone Apps/UCP-EPM for non-Sangoma phones via "Third Party Phone Support" add-on; Call/Contact Center add-on bundle.
- Community cost example: 25-user PBXact ISO ≈ $1,375 over 25 years incl. support vs ≈ $645 for a 25-user appliance *(user-reported)*.

## 36. Asked-for items that are NOT Sangoma commercial modules (or could not be found)
- Text To Speech / TTS Engines modules: open-source FreePBX modules (flite, festival, Cepstral Swift; Google/Polly via community hacks). Scribe adds a commercial TTS for System Recordings. https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26640584
- Dynamic Routes: open-source module (lookups via MySQL/URL/AGI, ASR only through custom scripts) — not commercial.
- Speech-to-text via Google/IBM Watson: no Sangoma module; Scribe (§30) is the commercial path.
- "Allow List", "Sangoma CyberSecurity": no FreePBX commercial module exists; Firewall, Intrusion Detection, Responsive Firewall are free. Sangoma sells separate network-security services outside FreePBX.
- Sangoma CX (cloud contact centre) and Sangoma Business Voice: cloud UCaaS/CCaaS products; no documented integration module for FreePBX/PBXact was found.
- Sangoma CM: no product by that name found (possibly "Contact Manager", which is a free module).
- E-mail-to-fax, fax cover-page per user templates beyond the company template, Yealink RPS/Polycom ZTP integration in EPM, recording annotation, SMS-to-e-mail: not documented anywhere; treat as absent.
- Prices not found: Contact Image, Oracle Connector, BrainBox, SAML, Sangoma Meet, PBXact per-user and POMPs tiers (reseller "login for price").

## 37. Price table (reseller sale prices in USD, fetched 2026-10-16; MSRP may differ)
| Module | SKU root | 25-year | 1-year | Bundles |
|---|---|---|---|---|
| EndPoint Manager | EPM | 199 | 99 | — |
| UCP for EPM | UCPEPM | 25 | 13 | (now bundled with EPM) |
| System Admin Pro | SYS | 39 (no maintenance) | 19 | Starter, Everything |
| Fax Pro | FAX | 150 | 50 | Starter, Everything |
| Call Recording Reports | CRR | 99 | 50 | Advanced, Everything |
| VQ Plus / Queue Pro | VQP | 475 | 157 | Call-Center, Everything |
| Queue Wallboard | QWB | — | 395 | — |
| Q-Xact Queue Reports | QXT | 795 | 263 | Call-Center, Everything |
| Class of Service | CLS | 99 | 50 | Adv, CC, Everything |
| Extension Routing | EXR | 39 | — | Starter, Everything |
| Conference Pro | CP | 30 | 15 | Starter, Everything |
| VM Notify | VMN | 75 | 38 | Advanced, Everything |
| Voicemail Reports | VMR | 25 | 13 | Advanced, Everything |
| Park Pro | PARK | 125 | 50 | Starter, Everything |
| Page Pro | PAGE | 95 | 48 | Starter, Everything |
| Pinset Pro | PIN | 45 | 23 | Adv, CC, Everything |
| Web Call Me | WCM | 50 | 25 | Adv, CC, Everything |
| CRM Link | CRM | 275 | 91 | CC, Everything |
| Caller ID Management | CIDM | 65 | 33 | Adv, CC, Everything |
| Outbound Call Limit | OCL | 195 | 65 | CC, Everything |
| Appointment Reminder | AR | 795 | 263 | Advanced, Everything |
| XactDialer / Broadcast | XTD | 795 | 263 | CC, Everything |
| Phone Apps | PHA | 499 | 165 | — |
| CDR Pro | CDP | — | 299 | — |
| Call Accounting | CA | — | 400 | — |
| Advanced Recovery (per server) | ADR | — | 400 | — |
| Property Manager Pro | SPM | — | 195 | — |
| MFA | MFA | — | 0 (since Apr 2025) | — |
| Scribe | C01M-SCRIBE | — | 24.99/month (1,000 min) + 39.99 top-up | — |
| Softphones (Talk+Desktop) | ZULU-xxU | — | 19 per user, 299 per 20 | included in PBXact |
| Desktop Advanced Queue | — | — | 6 per supervisor, 60 per queue (wiki example) | — |
| Starter / Advanced / Call-Center / Everything bundle | SB/AB/CB/EB | 349 / 1,149 / 2,299 / 3,449 | 169 / 579 / — / 1,729 | |
Sources: https://www.thetelecomspot.com/collections/freepbx (pages 1-4), https://www.voipsupply.com/sangoma-freepbx-cm-q-xact-25-year-license , https://hssl.us/freepbx-cm-call-recording-reports-25-year-license/ , https://sangomakb.atlassian.net/wiki/spaces/PG/pages/488800289 , https://sangomakb.atlassian.net/wiki/spaces/SS1/pages/522256385
