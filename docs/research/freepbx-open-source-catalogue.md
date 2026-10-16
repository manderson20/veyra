> Research appendix to [FREEPBX_GAP_ANALYSIS.md](../FREEPBX_GAP_ANALYSIS.md). Compiled 2026-10-16 from the cited Sangoma wiki, GitHub and community pages; not edited since. Treat prices and version notes as a snapshot.

# FreePBX 16 / 17 — Catalogue of free (open-source) modules and built-in capabilities

Compiled 2026-10-16 from the Sangoma documentation wiki (sangomakb.atlassian.net, space "PG" = PBX GUI module guides and space "FP" = FreePBX Open Source), the FreePBX GitHub organisations (github.com/FreePBX and github.com/FreePBX-ContributedModules), and FreePBX community/announcement pages. Each section cites the page(s) it was taken from. Most PG module guides carry the banner "updated for version 13" but still describe the current GUI; version-specific notes (14+, 15+, 16+, 17) are called out where the source says so.

Conventions: "free" = GPL/AGPL module shipped in the Basic/Extended/Unsupported repositories. Commercial Sangoma add-ons are named only where they extend a free module, so a comparison knows where the free feature ends. Default feature codes are given as `*xx`; all are changeable in Admin > Feature Codes.

---

## 0. Which modules are free — the master list

Source: GitHub org listing (api.github.com/orgs/FreePBX/repos, GPLv2/GPLv3/AGPLv3 licences) and the PG "Standard Modules" index pages:
- Admin index: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/18710823
- Applications index: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21135611
- Connectivity index: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24641749
- Reports index: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25788713
- Settings index: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26738760

Free modules (rawname — GUI name — menu): framework; core (Extensions, Trunks, Inbound/Outbound Routes, Administrators, DAHDI channel DIDs); announcement (Announcements, Applications); api (GraphQL/REST API, Connectivity); arimanager (Asterisk REST Interface Users, Settings); asterisk-cli (Admin); asteriskinfo (Reports); backup (Backup & Restore, Admin); blacklist (Admin); bulkhandler (Admin); calendar + calendar event groups (Applications); callback (Applications); callforward, callwaiting, donotdisturb (feature-code only, Connectivity index); callrecording (Applications); cdr (CDR Reports, Reports); cel (Call Event Logging, Reports); certman (Certificate Manager, Admin); cidlookup (CallerID Lookup Sources, Admin); conferences (Applications); configedit (Config Edit, Admin); contactmanager (Admin); customappsreg (Custom Destinations + Custom Extensions, Admin); dahdiconfig (DAHDI Config, Connectivity); dashboard (System Dashboard); daynight (Call Flow Control, Applications); dictate (Dictation, per-extension); directory (Applications); disa (Applications); extensionsettings (Extension Settings report, Settings); fax (Fax Configuration, Settings); featurecodeadmin (Feature Codes, Admin); filestore (Settings); findmefollow (Follow Me, Applications); firewall (System Firewall, Connectivity); hotelwakeup (Wake Up Calls, Applications); iaxsettings (Asterisk IAX Settings, Settings); infoservices (echo test, speaking clock, speak extension, call trace feature codes); ivr (Applications); languages (Applications); logfiles (Asterisk Logfiles, Reports); manager (Asterisk Manager Users, Settings); miscapps (Misc Applications); miscdests (Misc Destinations); music (Music on Hold, Settings); outroutemsg (Route Congestion Messages, Settings); paging (Paging and Intercom, Applications); parking (Applications); pbdirectory / phonebook (Asterisk Phonebook — now deprecated); pinsets (PIN Sets, Settings); pm2 (NodeJS process manager, infrastructure); presencestate (Admin); printextensions (Reports); queueprio (Queue Priorities, Applications); queues (Applications); recordings (System Recordings, Admin); ringgroups (Applications); setcid (Set CallerID, Applications); sipsettings (Asterisk SIP Settings, Settings); soundlang (Sound Languages, Admin); speeddial; timeconditions + Time Groups (Applications); tts + ttsengines (Text to Speech, Applications/Settings); ucp (User Control Panel); userman (User Management, Admin); vmblast (Voicemail Blasting, Applications); voicemail (Voicemail Admin, Settings); weakpasswords (Weak Password Detection, Reports); webrtc (WebRTC Phone / UCP Phone); superfecta (CID Superfecta, Admin — GPLv2, maintained in github.com/FreePBX); restart (Bulk Phone Restart — deprecated); xmpp, cxpanel (iSymphony) — deprecated/removed in 17; digium_phones, digiumaddoninstaller (Digium phone add-ons, legacy); freepbxlocalization (translations); sng_freepbx_debian_install (FreePBX 17 installer, GPLv3).

Community-supported (open source, not maintained by core team) per https://sangomakb.atlassian.net/wiki/spaces/PG/pages/131694652: OSS End Point Manager (endpointman) and Dynamic Routes (dynroute). The FreePBX-ContributedModules org additionally hosts allowlist (Allow List, GPLv3, repo "unsupported", 17.0 branch), outcnam (Outbound CNAM), missedcall (Missed Call Notification, 16+), restapi (legacy RESTful API, AGPLv3), bulkextensions/bulkdids (deprecated), campon (deprecated), customcontexts, accountcodepreserve, synologyabb, and many unmaintained legacy modules (a2billing, bosssecretary, cidroute, routepermissions, silentmonitor, etc.).

System Admin (sysadmin) is a special case: the module itself is free with a free tier and a paid "Pro" tier; see section 2.17.

Commercial (NOT free) module list, for boundary reference, from https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22478862: Appointment Reminder, Broadcast (XactDialer), Caller ID Management, CDR Pro Reporting, Class of Service, Conference Pro, CRM Link, EndPoint Manager (commercial), Extension Routing, Fax Pro, High Availability, Outbound Call Limit, Page Pro, Park and Announce, Park Pro, PINSet Pro, Queue Reports (QXact), Phone Apps (REST Apps), System Admin Pro, UCP for EndPoint Manager, VM Notify, Voicemail Reports, Queue Pro (VQ Plus — includes Queue Callback, virtual queues), Web CallBack, Sangoma Property Management (hotel PMS), PBX Call Accounting, Contact Image, Advanced Recovery, MFA, Call Recording Reports, Brainbox, Scribe, SAML, Sangoma Talk/Connect softphones (licensed, free 2-user/1-year trial licence per Sangoma Talk FAQ https://sangomakb.atlassian.net/wiki/spaces/SS1/pages/31392032).

---

## 1. Platform, FreePBX 17 changes, and FreePBX "Distro" system-level features

### 1.1 FreePBX 17 (GA 2024-08-02; PBXact 17 GA 2024-11-04)
Sources: https://sangomakb.atlassian.net/wiki/spaces/FP/pages/222101505 ; FAQ https://sangomakb.atlassian.net/wiki/spaces/FP/pages/279052296 ; community GA thread https://community.freepbx.org/t/exciting-news-freepbx-17-is-now-generally-available/99487 ; updates thread https://community.freepbx.org/t/latest-updates-on-freepbx-17/102781 ; installer README https://github.com/FreePBX/sng_freepbx_debian_install
- OS: Debian 12 "Bookworm" only (CentOS/SNG7 distro dropped). Ubuntu may work but is unsupported. Debian 12.11.x required for DAHDI hardware installs. FreePBX 17 stays on Debian 12; FreePBX 18 targets Debian 13.
- Install: open-source Bash installer `sng_freepbx_debian_install.sh` run as root on vanilla Debian 12 (logs in /var/log/pbx/freepbx17-install.log); a Sangoma ISO that wraps the script; and `sngfd12` scripts to build your own ISO. No offline installer (script downloads packages). OS packages updated with `apt update && apt upgrade`; Sangoma mirrors FreePBX, Asterisk and dependencies as Debian packages (`freepbx17`, `sangoma-pbx17` are held packages). The "OS upgrade" option in Module Admin was removed.
- Versions at GA: Framework 17.0.19.1; Asterisk 21.4.1 / 20.9.1 / 20.7-cert1 / 18.24.1 / 18.9-cert9 selectable; PHP 8.2 (modules tested only on 8.2; commercial modules not compatible with newer PHP); Node.js 18.16. Since 2024-12-03 Asterisk 22 (LTS) is available and the wiki page now says 17 "by default comes with Asterisk 22"; switch versions with `apt install asterisk-version-switch` then the `asterisk-version-switch` script.
- Dialplan: Asterisk Macro replaced by GoSub throughout FreePBX-generated dialplan; Asterisk MySQL applications (app_mysql) removed (affects Dynamic Routes MySQL source — use ODBC).
- chan_sip removed/unsupported (Asterisk 21+ has no chan_sip); FreePBX 17 is chan_pjsip only. Restoring a backup auto-converts chan_sip trunks and extensions to PJSIP (restore flags `--convertchansipexts2pjsip`, `--convertchansiptrunks2pjsip`, `--skipchansipexts`, `--skipchansiptrunks`). A downgrade-to-Asterisk-20 guide exists for people who must keep chan_sip (unsupported). IAX2 trunks still supported.
- Removed/deprecated modules: Zulu (EOL), Cxpanel/iSymphony, XMPP (chat server + UCP chat), DUNDi (long deprecated and removed from FreePBX, Asterisk still supports it). Full deprecated list: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41812064 — Bulk DIDs, Bulk Extensions, Camp-On, Magic Button, UCP (ARI, the old panel), XactView/iSymphony, Bria Cloud Solutions, Sangoma Addons, Java SSH, Sangoma Phones module, General Settings (2.10), Bulk Phone Restart, XMPP Chat Management, PBX Vega Management, Asterisk Phonebook.
- Upgrade path: no in-place 16 -> 17 upgrade; back up on 16 (Backup & Restore module), install Debian + 17, restore. The old migration service is discontinued. Future major upgrades are expected to be in place (RC -> GA was an apt upgrade). Downgrade 17 -> 16 via restore is unsupported.
- Other 17 changes noted: front-end library updates (jQuery, Bootstrap), module-admin changelog now links each fixed issue to GitHub (open source) or Jira (commercial); updated ffmpeg in Sangoma Debian repo; Firewall still uses iptables in 16/17 and moves to nftables in 18 (GitHub firewall repo description); Filestore SSH warm-spare key is ECDSA on 17 (RSA on 15/16) and the SSH user is `asterisk` instead of `root`.
- Issue reporting: open-source modules on GitHub issue tracker; commercial modules via Sangoma support ticket.

### 1.2 "Distro"-level system features (System Admin module, free tier vs Pro)
Source: feature matrix https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35422997 and module page https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35618920 (details in section 2.17). Free: Activation (deployment ID), DNS, Hostname, HTTPS Setup, Intrusion Detection (fail2ban), Network Settings, Notifications, Port Management, Power, PnP, Storage, Support (log dump), Time Zone. Pro only: DDNS, Email Setup (SMTP relay GUI), Provisioning Protocols (FTP/TFTP/HTTP(S) provisioning credentials), DHCP server, Packet Capture, Support VPN, Updates (legacy distro), UPS, VPN Server (OpenVPN). Note on free systems SMTP must be configured at the OS level (postfix) by hand.

### 1.3 Module Admin / Updates (framework, free)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20023939 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20873412 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20318723
- Repositories: Basic, Extended, Unsupported, Commercial; "Check Online", Download all / Upgrade all / Reset / Process; per-module Install / Uninstall / Remove / Enable / Disable; Rollback to any of the previous 5 versions; Stable vs Edge tracks (Advanced Settings "Set Module Admin to Edge mode", or `fwconsole ma upgrade <mod> --edge`); upload third-party module tarballs from web URL or local disk; built-in shopping cart for commercial licences; update-notification email with machine ID.
- Admin > Updates (14+): summary (framework version, module counts, last online check), scheduler: Automatic System Updates (Enabled / Email only / Disabled), Automatic Module Updates, Automatic Module Security Updates, "Send Security Emails For Unsigned Modules", check daily or a chosen weekday within a time window; System Updates tab lists OS package updates (RPM on SNG7; apt on 17 handled outside GUI).
- CLI: `fwconsole ma install|upgrade|downloadinstall <module>`, `fwconsole reload`, `fwconsole restart`, `fwconsole backup ...`, `fwconsole firewall ...`, `fwconsole userman ...`, `fwconsole sysadmin clearforce` etc. (CLI index https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41517266).

### 1.4 Dashboard / System Status (dashboard module, free)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26019841
- Landing page with modular blocks: System Overview (service status Asterisk/Apache/MySQL/SSH and notification alerts, e.g. "interface in Trusted zone", "chan_pjsip vs chan_sip", "HTTP basic auth", php.ini modifications, unsigned modules, weak passwords), Uptime, Statistics graph (active calls, trunks, CPU/memory/disk/network; Hour/Day/Week/Month), Feeds (RSS, configurable in Advanced Settings). Alerts can be "Resolved" / ignored; notifications are also emailed by the framework notification system (Module Admin email).

### 1.5 Device & User mode and dialplan structure (core/framework, free)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26706012 ; Config Edit page ; Custom Destinations page
- Default "Extension mode" (one device = one user). Advanced Settings "User & Devices Mode = deviceanduser" splits the Extensions module into Devices and Users: two phones can share one extension, and users can hot-desk between phones with User Login / User Logoff feature codes (core "User Login"/"User Logoff" codes; commercial modules do not support this mode).
- Generated contexts the GUI relies on: `from-internal` (extensions' default context, used by DISA default), `from-trunk`/`from-pstn` (inbound trunk calls; `from-trunk-<trunkname>` per trunk when counting inbound channels), `from-analog` (DAHDI FXO), `ext-did` (inbound DID handling), `ext-local`. Custom dialplan goes in `extensions_custom.conf`, `extensions_override_freepbx.conf` and the other `*_custom.conf` files (editable in Admin > Config Edit); custom code is exposed to the GUI through Custom Destinations (context,exten,priority with optional Return) and Custom Extensions (reserve numbers in the extension registry).

---

## 2. ADMIN menu

### 2.1 Administrators (core) — deprecated in favour of User Management
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/18907372
- Create GUI admin users with username/password and a per-module access list (drag modules Not Selected -> Selected; must include "Apply Changes Bar").
- When Advanced Settings "Authorization Type" = usermanager, this module is only a fallback; User Management supplies admin login, full-admin rights, visible extension range and module access instead.

### 2.2 Asterisk CLI (asterisk-cli)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/18645231
- Text box to run any Asterisk CLI command from the browser and show output (e.g. `pjsip show endpoints`, `core show channels`).

### 2.3 Backup & Restore (backup, 15+ redesign)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20807752 ; warm spare https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20873219 ; CLI https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41746505
- Per-module backups: choose which modules' data to include (select all or subset), some modules expose sub-options; cross-version restore (15 -> 16 -> 17 supported, and legacy 13/14 tarballs are also restorable).
- Custom directories: default includes `__ASTETCDIR__` (all `*_custom.conf`); call recordings are NOT included unless you add `__ASTSPOOLDIR__/monitor`.
- Storage: one or more Filestore locations (Local, FTP/SFTP, SSH, S3, Dropbox, Email); option "Append BackupJobName Directory into Storage path".
- Email notifications (success/failure) per job; schedule (enable + cron-style selection, randomised defaults); maintenance: keep last X runs ("Delete After Runs", 0 = unlimited) and/or delete after age.
- Warm Spare: a backup job can push to a second PBX over SSH/FTP and trigger restore via the spare's GraphQL API (Machine-to-Machine app with `gql:backup` scope); options to restore or skip NAT settings, bind address, DNS, run Apply Config after restore, exclude Certman, exclude Trunks.
- Restore: upload file or pick a stored backup, confirmation screen shows modules contained; download/delete stored backups from GUI.
- CLI: `fwconsole backup --list`, `--backup=<id>`, `--restore <file>` with `--ignoremodules`, `--skipbindport`, `--skipdns`, `--skipremotenat`, `--skiptrunksandroutes`, `--skiprestorehooks`, `--restorelegacycdr`, `--restoresingle=<module>`, `--modules a,b`, `--useinfiledb`, 17-only chan_sip conversion flags; `--backupsingle <module> --singlesaveto <path>`; `--dumpextern` / `--externbackup` for remote-triggered jobs.

### 2.4 Blacklist (blacklist)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20644332
- System-wide list of blocked caller numbers with description; blocked callers go to a chosen destination, default is the "number not in service" recording.
- Settings tab: "Block Unknown/Blocked Caller ID" (anonymous/withheld CID) with destination.
- Statistics view of inbound calls from each blacklisted CID; CSV import/export.
- Feature codes: `*30` blacklist a number (prompts), `*32` blacklist last caller, `*31` remove a number.

### 2.5 Allow List (allowlist — contributed, GPLv3, "unsupported" repo, 16/17 branches)
Sources: module.xml https://github.com/FreePBX-ContributedModules/allowlist (release/17.0) ; feature-code table https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20351168
- Inverse of Blacklist: "manage a system wide list of allowlisted callers" (only known callers get through; others are diverted). Depends on core and cdr; Bulk Handler import/export hooks; `fwconsole allowlist` console command.
- Feature codes: `*38` add a number, `*39` remove a number, `*40` add last caller, `*41` pause/unpause allowlist checking. Superfecta also ships an "Allowlist" data source.
- The wiki has no user-guide page for this module; option details beyond the above were not documented in the sources read.

### 2.6 Bulk Handler (bulkhandler)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20318634
- CSV export/import of Extensions, DIDs (inbound routes), User Manager Users, User Manager Groups, Contacts; other modules hook in (UCP templates, Allow List, Missed Call Notification).
- Export produces a template with all headers; import shows required/recommended headers (e.g. extension, name, tech, secret [REGEN], callwaiting_enable, findmefollow_enabled/grplist, voicemail_enable/vmpwd/email/options; DIDs: extension, cidnum, destination, fax_* ; contacts: group, phone_1..3 number/type/flags, email_1..3).
- Validation page before commit with per-row editor and a "replace and update all existing data" toggle; progress bar; Apply Config afterwards. (No secret-strength validation on import — see Weak Password Detection.)

### 2.7 CallerID Lookup Sources (cidlookup)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20611384
- Defines CNAM lookup sources that an inbound route selects ("CID Lookup Source" on the Other tab); result replaces the caller-ID name and appears in CDRs.
- Source types: OpenCNAM (hobbyist 60 lookups/hour or Professional with SID/token), Internal (astdb populated by the Phonebook module), ENUM (DNS/enum.conf), HTTP and HTTPS GET (host, port, auth, path, query with `[NUMBER]` token), MySQL (host, db, query with `[NUMBER]`, user, password, charset). SugarCRM and Superfecta entries exist but are "Not Implemented".

### 2.8 CID Superfecta (superfecta — GPLv2, third-party origin, maintained in github.com/FreePBX)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20709838 ; source list https://github.com/FreePBX/superfecta/tree/release/17.0/sources ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/681050406
- Schemes: name, DID rules and CID rules (pattern match with `|` strip-prefix and `+` add-prefix), per-source lookup timeout, processor MULTI (all sources in parallel, "Multifecta timeout" controls how long priority order is honoured) or SINGLE (sequential), CID prefix URL (first 10 chars prepended), SPAM text prepend or substitute, "Enable SPAM Interception" (divert or terminate spam calls); sources are enabled/ordered per scheme with a wrench icon for per-source settings; inbound route selects "Enable Superfecta Lookup" + scheme.
- ~90 data sources shipped in 17.0: CNAM providers (OpenCNAM, BulkCNAM, CallerID Service, CIDName.com, EZCNAM, FreeCNAM, NextCaller, Telnyx, TrueCNAM, Twilio, VoIPCNAM, VoIP Innovations, Telco Data, Trunk Provided), local data (FreePBX Contact Manager, FreePBX User Manager, Asterisk Phonebook, Asteridex, LDAP, Google Contacts, iAddressBook, FOP2 phonebook, Superfecta Cache, SFDatabase, Regular Expressions 1/2, Allowlist, Abandon lookup), CRMs (SugarCRM, CapsuleCRM, ConnectWise, OpenEMR), spam databases (PhoneSpamFilter US/UK, FccComplaints, Tellows, Who Called, WhoCalled UK, Telepest UK, Say No To 0870, Responder o No), country directories (DE, AT, CH, NL, SE, AU, UK, AR, CA, FR...), and "Send to" notification sinks (email, URL, MQTT, Telegram, Pushover, PushBullet, IFTTT, Growl, NotifyMyAndroid, XBMC/Kodi, MythTV, Squeezebox, Soundbridge, Dreambox, NeutrinoHD, Winunciator, YAC, Yo).
- The "Send to email" source plus a loop-back inbound route can be used for ring/missed-call notifications on internal extensions (wiki example).

### 2.9 Certificate Manager (certman)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20611404
- Let's Encrypt: HTTP-01 challenge on port 80, fields Certificate Host Name (FQDN), Owner email, Country, State; auto-renewal roughly every 2 months; Firewall module opens port 80 dynamically during issue/renew (`fwconsole firewall lerules enable|disable`).
- Upload certificate (name, passphrase, CSR reference or own private key, certificate, trusted chain); generate self-signed certificate (a self-signed CA is created on first boot; "Delete Self-Signed CA" option); Generate CSR (CN, O, OU, C, ST, L) and download it; "Import Locally" from /etc/asterisk/keys; mark one certificate as default (used by Advanced Settings and copied to /etc/asterisk/keys/integration); validity period adjustable in Advanced Settings (default 730 days).
- Certificates are consumed by System Admin > HTTPS Setup (Apache), PJSIP TLS transport, DTLS-SRTP/WebRTC per extension, UCP Phone.

### 2.10 Config Edit (configedit, AGPLv3)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20808046
- In-browser editor for the `_custom` configuration files (extensions_custom.conf, pjsip.*_custom.conf, etc.); create new files; non-writable generated files are flagged read-only; Save then Apply Config.

### 2.11 Contact Manager (contactmanager)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20023898
- Contact groups of three types: Internal (contacts pulled from User Management, fields can be overridden), External (customers/vendors: display/first/last name, title, company, address, multiple numbers, XMPP, email, website, avatar), and the undeletable "User Manager" group of all users.
- Per-number Speed Dial: enable + code, dialled as `*10<code>` ("Contact Manager Speed Dials" also appear as GUI destinations).
- Consumers: UCP Contacts widget, Phone Apps (commercial), Superfecta source, CID lookups; visibility per user/group set in User Management ("Show in" / "Viewable" contact groups). Practical limit noted: clients slow above ~1000 contacts.

### 2.12 Custom Destinations and 2.13 Custom Extensions (customappsreg)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20709893 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/59375916
- Custom Destinations: register `context,exten,priority` targets from custom dialplan so every destination picker (IVR, inbound routes, queues...) can route to them; Description, Notes, and "Return = Yes" with a follow-on destination when the custom code ends with Return().
- Custom Extensions: reserve numbers/feature codes used by custom dialplan so the Extension Registry detects conflicts and other modules (Print Extensions) list them.

### 2.14 Feature Codes (featurecodeadmin) — full default table
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20351168 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20775224 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20447788
- Module functions: per code Enable/Disable and "Customize" to change the dial string (no duplicate check; avoid overlapping codes like *12/*123); every module registers its own codes; Misc Applications create user-defined codes.
- Allow List: `*38` add number, `*39` remove, `*40` add last caller, `*41` pause/unpause.
- Blacklist: `*30` add, `*31` remove, `*32` blacklist last caller.
- Call Forward: `*72` CF All activate, `*73` deactivate, `*93` CF All prompting activate, `*74` prompting deactivate, `*90` CF Busy activate, `*91` deactivate, `*94`/`*92` CF Busy prompting act/deact, `*52` CF No-Answer/Unavailable activate, `*53` deactivate, `*95` CFU prompting activate, `*96` CF toggle; for another extension dial `*720`/`*730`/`*900`/`*910`/`*520`/`*530` then source and destination.
- Call Waiting: `*70` activate, `*71` deactivate (the Call Waiting user guide lists them the other way round; the Feature Code table is authoritative).
- Camp-On (deprecated module): `*82` request, `*83` cancel, `*84` toggle.
- Conferences: `*87` conference status.
- Contact Manager: `*10` speed dials.
- Core: `*8` general call pickup (callgroup/pickupgroup), `**` directed call pickup prefix (`**<ext>`), `*2` in-call attended transfer, `##` in-call blind transfer, `*1` in-call toggle call recording (on-demand), `**` in-call disconnect, `*59` call seize, `555` ChanSpy, `777` simulate incoming call; User Login / User Logoff codes in Device & User mode; ZapBarge.
- Call Flow Control (daynight): `*28` + index 0–99, e.g. `*280`.
- Dictation: `*34` perform dictation, `*35` email completed dictation.
- DND: `*78` activate, `*79` deactivate, `*76` toggle.
- Fax: `666` dial system fax.
- Follow Me: `*21` toggle.
- Wake Up Calls (hotelwakeup): `*68`.
- Info Services: `*43` echo test, `*65` speak your extension number, `*60` speaking clock, `*69` call trace (last caller ID).
- Paging: `*80` intercom prefix (`*80<ext>`), `*54` user intercom allow, `*55` user intercom disallow.
- Parking: `*85` pickup parked call prefix (`*85<lot>` next call or `*85<slot>`), `*88` park to your assigned lot; Park Pro (commercial) `*86` force park into private lot; default lot extension `70`, slots `71–78`.
- Phonebook Directory (deprecated): `411` dial-by-name.
- PMS (Sangoma Property Management, commercial): `*36` room clean, `*37` mini-bar, `*44` message to receptionist.
- Queues: `*45` agent login/logout toggle (all queues), `*45<queue>` single queue, `*45*<ext>` / `*45<ext>*<queue>` variants that generate BLF hints, `*46` queue pause toggle, `*47` playback queue caller count.
- REST Apps (commercial): `*992` phone app hints.
- Speed Dial: `*75` set user speed dial, `*0` speed-dial prefix (`*0<code>`).
- System Recordings: per-recording feature code (optional PIN) to re-record a prompt from a phone; "Check Recording"/"Save Recording" codes.
- Time Conditions: per-condition override feature code (toggle temporary override, optional PIN).
- Voicemail: `*97` my voicemail, `*98` dial any mailbox, `*` direct-dial-to-voicemail prefix (`*<ext>`).

### 2.15 Module Admin — see 1.3.

### 2.16 Presence State (presencestate)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20611590
- Admin-defined list of presence states built on Asterisk presence (types Available, Chat, Away, DND, Extended Away, Unavailable, each with a free-text message, e.g. "Away (lunch)"); defaults are one of each type.
- Consumed by UCP Presence widget/side bar (users set status; auto-actions can turn DND or Follow Me on/off per state; set state on login/logout), Phone Apps, XactView/iSymphony/Zulu (legacy), Sangoma phones. No Apply Config needed.

### 2.17 System Admin (sysadmin) — free tier
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35618920 ; feature matrix https://sangomakb.atlassian.net/wiki/spaces/PG/pages/35422997 ; sub-pages 35226461 (Intrusion Detection), 35520890 (Port Management), 35586286 (Network), 35390087 (Notifications), 35226488 (Storage), 35455403 (HTTPS), 35520953 (Time Zone), 35488222 (DNS), 35193555 (Hostname), 35553747 (Power)
- Free: Activation (register deployment ID, needed before commercial purchases), DNS servers (/etc/resolv.conf), Hostname, HTTPS Setup (assign Certificate Manager cert to Apache, disable weak ciphers, choose SSL protocols), Intrusion Detection (fail2ban start/stop/restart, Ban Time default 1800 s, Max Retry, Find Time default 600 s, notification email, whitelist of IPs/subnets, banned-IP list; since 14.0.3/15.0.8 this lives in the Firewall module with zone sync — see 4.7), Network Settings (interface static/DHCP/unconfigured, IP/netmask/gateway, start on boot, add secondary or VLAN (802.1q 1–4094) interfaces), Notification Settings (From address; destinations for UPS, Safe Asterisk crash/restart, Storage, Intrusion Detection, Call Recording report, Abnormal call volume), Port Management (Admin 80, UCP 81, REST Apps 82, REST/GraphQL API 83, HTTP provisioning 84, LetsEncrypt-only 80; per-service HTTPS ports, disable a service, force-redirect to HTTPS, `fwconsole sysadmin clearforce`), Power (shutdown/reboot), PnP, Storage (disk usage, RAID status, two usage thresholds with hourly/daily/weekly/monthly email frequency, RAID failure mails), Support log dump, Time Zone (reboot required).
- Pro only (paid): DDNS (Sangoma-hosted FQDN), Email Setup (built-in postfix or external SMTP/Gmail with auth, debug/test mail), Provisioning Protocols (FTP/TFTP/HTTP(S) provisioning servers with random credentials, secure provisioning), DHCP server, Packet Capture (tcpdump to 500 MB files, download pcap/zip), Support VPN, Updates (legacy distro), UPS (apcupsd settings and shutdown thresholds), VPN Server (OpenVPN server 10.8.0.0 range, per-client configs linked to User Management users and downloadable in UCP, UDP 1194).

### 2.18 System Recordings (recordings)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20578785
- Create recordings for IVR/Announcements/Queues etc. three ways: upload (WAV, aiff, alaw, flac, g719, g722, gsm, mp3, oga, ogg, sln*, ulaw, wav49; multiple files or archives), record in browser (WebRTC microphone), or record over an extension (system calls the phone).
- Compound recordings: a sortable "File List" strings several files into one recording per language; files missing for the selected language are flagged; click-to-replace re-record mode; "Add System Recording" reuses existing files.
- "Convert To" output formats: alaw, g719, g722, gsm, sln, ulaw, wav, wav49 (multi-select).
- "Link to Feature Code" + optional numeric password lets users re-record a prompt from any phone without the GUI.

### 2.19 Sound Languages (soundlang)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20709972
- Install/remove core-sounds and extra-sounds language packs per codec (alaw, g722, g729, ulaw...) from the GUI: American/Australian/British English, Spanish, French, Italian, Japanese, Russian (list at time of writing).
- Set the Global Language default; define Custom Languages (language code + description, creates /var/lib/asterisk/sounds/<code>, upload files or archives); fallback to the global language when a prompt is missing. Language can be changed mid-call by inbound route, extension, or the Languages module.

### 2.20 User Management (userman) — see section 7.

### 2.21 Voicemail (voicemail / "Voicemail Admin") — see 6.14 and per-extension options in 3.10.

---

## 3. APPLICATIONS menu

### 3.1 Announcements (announcement)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21004696
- Play a System Recording then continue to a destination. Options: Description, Recording, Repeat key (0-9, *, #) to replay, Allow Skip (any key ends playback), Return to IVR (go back to the originating IVR instead of the fixed destination), Don't Answer Channel (play as early media), Destination after Playback.

### 3.2 Calendar (calendar) and 3.3 Calendar Event Groups
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21332158 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21233903 ; drivers pages (CalDAV 21102999, Google 21233937, iCal 21070227, Local 22478931, Outlook/EWS/365 22675496, Outlook OAuth2 22118742)
- Calendar sources ("drivers"): Local (built-in calendar with events/recurrence), CalDAV, Google, iCal URL, Outlook/Exchange EWS/365 (including OAuth 2.0 for Outlook). Office staff can manage call routing by editing a Google/Outlook calendar.
- Calendar Event Groups: collections of calendars, specific categories and/or specific events (even from different calendars) that can be linked as one unit.
- Module support: Time Conditions (Mode = Calendar vs Time Group; pick Calendar or Calendar Group and a time zone; matched whenever an event is active), Find Me/Follow Me (enable calendar matching, calendar/group, "Calendar Match Inverse" to enable FM/FM when there is or is not an event), Paging Pro scheduler (commercial) fires pages at event start times.

### 3.4 Callback (callback)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22118767
- Destination that hangs up on the caller and calls them back (saves caller's mobile/international charges). Options: Description, Callback Number (blank = use received caller ID), Delay Before Callback (seconds), Destination after Callback. Outbound leg follows Outbound Routes.

### 3.5 Call Flow Control (daynight)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22184251
- Manual day/night toggle switch between a Normal (green/BLF off) and Override (red/BLF on) destination; up to 100 toggles indexed 0–99, dialled as `*28<index>` (`*280`…`*2899`), BLF-subscribable.
- Options: description, current mode button, custom recordings for entering Normal and Override mode (defaults "feature code (de)activated"), optional password, Normal Flow Destination, Override Flow destination. Also controllable from UCP/Phone Apps.

### 3.6 Call Recording (callrecording)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22642752 ; MixMonitor-based recording policy used by Extensions/Inbound/Outbound Routes/Queues/Ring Groups/DISA
- Destination object that sets the recording policy for the remainder of the call flow then forwards: Force / Yes / Don't Care / No / Never (Force and Never are overrides that users cannot change without "Override" on-demand permission; Yes/No are equal-priority defaults; Don't Care passes through).
- Same five-state selector appears on inbound routes, outbound routes, queues, ring groups (Force/Don't Care/Never), DISA, and per-extension (inbound external, outbound external, inbound internal, outbound internal, On-Demand Recording Disable/Enable/Override, Record Priority Policy 0-20 to resolve conflicts between caller and callee). In-call `*1` toggles on-demand recording. Recordings are stored under /var/spool/asterisk/monitor and are playable/downloadable in CDR Reports, CEL and UCP (Call History / Call Events widgets).

### 3.7 Conferences (conferences, ConfBridge)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22708338
- Per room: Conference Number, Name, User PIN, Admin PIN, Join Message (system recording), Leader Wait, Talker Optimization, Talker Detection (AMI events), Quiet Mode (no enter/leave tones), User Count announcement, User Join/Leave (record name and announce), Music on Hold (when single caller) + MoH class, Allow Menu (`*` menu), Record Conference, Maximum Participants (0 unlimited), Mute on Join.
- In-conference `*` menu: 1 mute/unmute self; admin only 2 lock/unlock, 3 eject last joiner, 0 mute/unmute all non-admins; 4/5/6 listen volume down/reset/up; 7/9 talk volume down/up; 8 leave menu; # leave conference.
- Feature code `*87` conference status. Conference IVR, per-user auto-created rooms (8+ext), UCP conference control (mute/kick, live settings) and scheduling require Conference Pro (commercial).

### 3.8 Directory (directory)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22446264
- Dial-by-name directories (first three or more letters of first or last name) reachable from an IVR or as a destination. Options: name, description, CID name prefix, Alert Info, custom announcement, Invalid Retries, Invalid Retry Recording, Invalid Recording, Invalid Destination, Return to IVR, Announce Extension before transfer.
- Entries: All Users, individual Extension, or Custom Entry (any dial string, e.g. a mobile number); per entry Name (search key), Name Announcement (voicemail name greeting, text-to-speech, spell name, or system recording), and Dial target (can be another extension, e.g. an assistant). Speech-recognition directories are the commercial Directory Pro.

### 3.9 DISA (disa)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22446287
- Direct Inward System Access: outside caller gets internal dial tone. Options: name, PIN (multiple comma-separated; strongly recommended), Response Timeout (default 10 s), Digit Timeout (default 5 s), Call Recording policy, Require Confirmation (press key before PIN prompt), Caller ID to present, Context (default from-internal), Allow Hangup (`**` returns to dial tone for another call).

### 3.10 Extensions (core) — every per-extension option
Sources: PJSIP extension guide https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22020636 ; module page https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22741215 ; Virtual https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22118946 ; Custom https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22642904 ; Follow Me guide https://sangomakb.atlassian.net/wiki/spaces/PG/pages/23593115 ; Voicemail extension level https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21266559
- Extension types: PJSIP (default; chan_sip until 16 when "SIP Channel Driver" = both/chan_sip), IAX2, DAHDI (FXS channel), Virtual (no device: voicemail/follow-me/CID only), Other/Custom (free-form Dial string such as `SIP/joe@domain`, `Local/...@ctx`, used for remote SIP URIs or notification loops). Quick Create Extension dialog; Bulk Handler CSV import; GraphQL `addExtension`/`createRangeofExtension`.
- General: User Extension (immutable), Display Name (becomes CID name), Outbound CID `"name" <number>` (overrides trunk CID unless the route overrides it), Secret (auto-generated, strength meter, "Require Strong Secrets" in Advanced Settings), User Manager link (create new user with username/password/groups, link existing, or none).
- Voicemail tab: Enabled; Voicemail Password (digits; defaults to extension); Require From Same Extension (password prompt on `*97`); Disable `*` in Voicemail Menu (remote access via greeting); Email Address; Pager Email Address (short SMS-style notification); Email Attachment; Play CID; Play Envelope; Delete Voicemail after email; VM Settings (pipe-separated voicemail.conf per-mailbox options e.g. `review=yes|maxmessage=60|tz=...|imapuser=...|operator=yes|callback=...|dialout=...|exitcontext=...|volgain=...|maxmsg=...|serveremail=...`); VM Context (default `default`).
- VmX Locater (per extension, free): Enabled; Use When = Unavailable / Busy / Temporary greeting; Voicemail Instructions (play standard "leave a message" prompt or beep only); Press 0 (go to operator or custom destination — works even when VmX disabled), Press 1 and Press 2 (any destination incl. external number, e.g. cell phone; press 1 default goes to Follow Me).
- Find Me/Follow Me tab: Enabled (toggle also via `*21`, UCP, Follow Me module list, Calendar); Initial Ring Time (0 = skip primary); Ring Strategy ringallv2 (keeps ringing primary), ringall, hunt, memoryhunt, *-prim variants, firstavailable, firstnotonphone; Ring Time; Follow-Me List (extensions and external numbers suffixed `#`), Extension Quick Pick; Announcement; Play Music On Hold instead of ringing; CID Name Prefix; Alert Info; Confirm Calls (callee presses 1; ringall/ringall-prim only) with Remote Announce and Too-Late Announce; Change External CID mode Default / Fixed CID Value / Outside Calls Fixed CID / Use Dialed Number / Force Dialed Number + Fixed CID Value; No Answer destination (default = normal extension behaviour e.g. voicemail); calendar matching (see 3.2).
- Advanced tab — Assigned DID/CID: DID description, Add Inbound DID (creates an inbound route bound to the extension), Add Inbound CID (DID+CID routing; special values Private/Blocked/Unknown/Restricted/Anonymous/Withheld/Unavailable).
- Advanced — Call Camp-On Services (Asterisk CCSS): Caller Policy (cc_agent_policy) and Callee Policy (cc_monitor_policy) with Generic Device or native-technology modes (GUI module Camp-On is deprecated but the per-extension CCSS fields remain).
- Advanced — device settings (PJSIP): DTMF Signaling (RFC 4733 "RFC" default), Context (default from-internal), Trust RPID, Send RPID (none/RPID/PAI), Qualify Frequency, Transport (UDP/TCP/TLS/WS/WSS), Enable AVPF, Enable ICE Support, Call Groups, Pickup Groups, Disallowed/Allowed Codecs, Dial string, Mailbox (LDAP MWI multi-mailbox form), Voicemail Extension, Account Code, Max Contacts (multiple registrations per extension), Media Use Received Transport, RTP Symmetric, Rewrite Contact, MWI Subscription Type (solicited/unsolicited), Aggregate MWI, Media Encryption (none/SRTP via in-SDP/DTLS-SRTP), Media Encryption Optimistic, Match (Permit) IP/CIDR list, Maximum/Minimum Expiration, CID Num Alias (internal CID masquerade), SIP Alias (name-based SIP URI dialling). chan_sip extensions additionally expose nat, qualify, deny/permit, port, encryption, video, etc.
- Advanced — Extension Options: Asterisk Dial Options override; Ring Time (default from Advanced Settings); Call Forward Ring Time (Default/Always/seconds); Outbound Concurrency Limit (max simultaneous outbound calls — toll-fraud protection); Call Waiting Enable/Disable; Internal Auto Answer (Disable / Intercom — all internal calls auto-answered as intercom); Call Screening (disable / with memory / without memory — caller records name, callee accepts/rejects); Pinless Dialing (bypass route PIN sets); Emergency CID (always used on routes marked Emergency); Queue State Detection (Use State / Ignore State for queue member availability).
- Advanced — Recording Options: Inbound External, Outbound External, Inbound Internal, Outbound Internal calls (Force/Yes/Don't Care/No/Never), On Demand Recording (Disable/Enable/Override), Record Priority Policy.
- Advanced — Dictation Services: Dictation Service Enabled, Dictation Format (Ogg Vorbis/GSM/WAV), Email Address, From Address (uses `*34` record / `*35` email).
- Advanced — DTLS (WebRTC): Enable DTLS, Use Certificate (from Certificate Manager), DTLS Verify (Yes/No/Fingerprint/Certificate), DTLS Setup (active/passive/actpass), DTLS Rekey Interval.
- Advanced — Optional Destinations: No Answer, Busy, Not Reachable (device offline), each with its own CID Prefix.
- Other tab: Endpoint (brand/MAC/template/model/account — commercial EPM), iSymphony (legacy), Language Code (per-extension prompt language), Default Group Inclusion (include/exclude in default Page Group and default VMBlast group), Device Options: default Parking Lot.
- Hot desking: Device & User mode (login/logout feature codes) — see 1.5; Phone Apps "Login/Logout" app is commercial.

### 3.11 Follow Me (findmefollow)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/23593115
- Since 13 the module page is a list to quickly enable/disable Follow Me per extension (instant, no Apply Config) and jump to the extension's Find Me/Follow Me tab; all settings live on the extension (see 3.10). Users toggle with `*21`, UCP widget, Phone Apps, or Calendar linkage.

### 3.12 IVR (ivr)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24248373
- General: IVR Name, Description. DTMF options: Announcement (system recording), Enable Direct Dial (Disabled / Extensions / a specific Directory to restrict which extensions can be dialled), Timeout seconds, Invalid Retries, Invalid Retry Recording, Append Announcement to Invalid, Return on Invalid (back to parent IVR), Invalid Recording, Invalid Destination, Timeout Retries, Timeout Retry Recording, Append Announcement on Timeout, Return on Timeout, Timeout Recording, Timeout Destination, Return to IVR after VM (press 9 in voicemail returns to this IVR).
- IVR Entries: digits (single or multi-digit, hidden entries allowed) -> any destination, with per-entry "Return" flag to come back to the parent IVR; sub-menus by pointing an entry at another IVR. "Alias" naming is not a documented IVR option; speech recognition and advanced failover are IVR Pro (commercial).

### 3.13 Languages (languages)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24576074
- Destination object that sets the channel language (code from Sound Languages) then continues to a destination, e.g. "press 9 for Spanish" -> Spanish IVR. Falls back to the global language for missing prompts.

### 3.14 Misc Applications (miscapps) and 3.15 Misc Destinations (miscdests)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24641618 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24477803
- Misc Applications: create your own internal feature codes/extensions (e.g. `*7876` or `7876`) that send the caller to any destination (IVR, queue, voicemail app...); Enable/Disable; appears in Feature Codes module.
- Misc Destinations: wrap anything dialable from an extension (external number, feature code, extension, legacy application strings such as `voicemail:dialvoicemail`) as a destination selectable by other modules.

### 3.16 Missed Call Notification (missedcall — contributed, 16+)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24543299
- Emails the user (address from User Management) when a call to their extension is not answered: separately enable for missed internal, external, queue and ring-group calls; per-user or per-group settings in User Management; bulk enable/disable; custom email template; Bulk Handler import/export; feature codes; UCP widget and side-bar envelope; included in Backup & Restore. Not supported when Find Me/Follow Me is active. Install with `fwconsole ma downloadinstall missedcall`.

### 3.17 Paging and Intercom (paging)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24543322
- Settings: Auto-answer default announcement (beep, none, or system recording).
- Page group: Paging Extension (3–11 digits), Description, Device List (drag extensions; recommended max 25, hard limit "Max Paging Participants" in Advanced Settings), Announcement (default/none/recording), Busy Extensions = Skip / Force / Whisper (ChanSpy whisper into busy phone's earpiece), Duplex (two-way, otherwise listeners muted; `*1` unmutes), Default Page Group (new extensions auto-join).
- Intercom: `*80<ext>` one-to-one auto-answer intercom; `*54`/`*55` per-user allow/disallow; extension-level Internal Auto Answer = Intercom; Advanced Settings "Force All Internal Auto Answer".
- Page Pro (commercial) adds: Busy Page Group Valet/Force Valet (airport-style recorded paging), page announcement prepend, CID prepend, RTP multicast streams, Scheduler (date range, weekday/time events, exclusion dates, 15-minute granularity) and Calendar-driven schedules, outbound-route notifications (e.g. 911 page with `*1` barge). Multicast paging on phones must be configured on the handset (Skip/Force/Whisper does not apply).

### 3.18 Parking (parking)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24510575
- Free module: a single Default lot (Park Pro adds multiple lots, public/private lots, `*86`). Options: Parking Lot Extension (default 70), Name, Starting Position, Number of Slots (e.g. 71–78), Parking Timeout seconds, Parked Music Class, BLF Capabilities (hint per slot), Find Slot Next/First.
- Returned-call behaviour: Pickup Courtesy Tone (caller/parked/both/none), Transfer Capability and Re-Parking Capability (caller/parked/both/neither), Parking Alert-Info, CallerID Prepend, Auto CallerID Prepend (none/slot/extension/name), Announcement before return; Alternate Destination: Come Back to Origin (yes/no) and Destination for timeouts/unreachable parker.
- Feature codes `*85` (pickup from lot or slot; BLF `*85<lot>` lights when any call parked), `*88` park to assigned lot; per-extension default Parkinglot.

### 3.19 Queue Priorities (queueprio)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24510591
- Destination that sets caller priority 0–20 (default 0) before continuing; higher priority callers jump ahead in any queue entered later; used for SLA/VIP routing.

### 3.20 Queues (queues) — every option
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24510614
- Agent login: `*45` toggle all queues, `*45<queue>`, `*45*<ext>` and `*45<ext>*<queue>` with BLF hints (device hints `*45ddd*qqq` always generated), `*46` pause toggle, `*47` caller count playback; static agents always in, dynamic agents log in/out; Queue Password for legacy login; Restrict Dynamic Agents to the listed dynamic members.
- General: Queue Number, Name, Password, Call Confirm (+ Call Confirm Announce) for external/forwarded agents, CID Name Prefix, Wait Time Prefix (`Mnn:` minutes waited), Alert Info, Agent Restrictions (Called as Dialed / No Follow-Me or Call Forward / Extensions Only), Ring Strategy (ringall, leastrecent, fewestcalls, random, rrmemory, rrordered, linear, wrandom), Autofill, Skip Busy Agents (No / Yes / Yes+ringinuse=no / Queue calls only ringinuse=no), Queue Weight (priority among queues sharing agents), Music on Hold Class with MoH Only / Agent Ringing / Ring Only, Join Announcement (Always / When No Free Agents / When No Ready Agents), Call Recording policy, Mark calls answered elsewhere (suppress missed-call logs), Fail Over Destination.
- Queue Agents: Static Agents (one per line, remote/external numbers allowed, `,penalty` suffix, S/P/X/Z/D/A technology prefix advanced mode), Dynamic Agents list, Agent Quick Select.
- Timing & Agent Options: Max Wait Time (unlimited or seconds), Max Wait Time Mode Strict/Loose, Agent Timeout, Agent Timeout Restart, Retry seconds or "No Retry", Wrap-Up-Time (and global "Honor Wrapup Time" across queues), Member Delay, Agent Announcement (whisper queue name to agent), Report Hold Time to agent, Auto Pause (no / this queue / all queues), Auto Pause on Busy, Auto Pause on Unavailable, Auto Pause Delay.
- Capacity Options: Max Callers (0 unlimited -> failover), Join Empty (Yes / Strict / Ultra Strict / No / Loose), Leave Empty (Yes / Strict / Ultra Strict / Loose / No), Penalty Members Limit.
- Caller Announcements: position/hold-time announcement Frequency, Announce Position, Announce Hold Time (Yes/No/Once); Periodic Announcements: IVR Break Out Menu (single-digit IVR, callers press a key to exit the queue to another destination e.g. leave voicemail) and Repeat Frequency.
- Advanced: Service Level seconds (for statistics), Agent Regex Filter (validate dynamic-agent numbers), Reset Queue Stats; Event logging to queue_log is standard Asterisk; GUI queue reports beyond Asterisk Info "Queues" snapshot require QXact Reports (commercial). Queue Callback / virtual queues / queue-plus options are VQ Plus (commercial).

### 3.21 Ring Groups (ringgroups)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24314016
- Ring Group Number, Description, Ring Strategy (ringall, hunt, memoryhunt, *-prim variants, firstavailable, firstnotonphone, random), Ring Time (max 300 s per iteration), Extension List (extensions, remote extensions and external numbers with `#` suffix which also makes the entry follow the member's Follow Me), Announcement, Play Music On Hold instead of ringback, CID Name Prefix, Alert Info (distinctive ring), Ringer Volume Override (Sangoma phones), Send Progress (SIP 183), Mark Answered Elsewhere (Always/Yes/No), Ignore CF Settings, Skip Busy Agent, Enable Call Pickup (`**<group>`), Confirm Calls (ringall only) with Remote Announce and Too-Late Announce, Change External CID (Default / Fixed / Outside Calls Fixed / Use Dialed Number / Force Dialed Number) + Fixed CID Value, Call Recording (Force / Don't Care / Never), Destination if no answer.

### 3.22 Set CallerID (setcid)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24346745
- Destination that rewrites CID name and number using Asterisk variable syntax (`${CALLERID(name)}`, `${CALLERID(num):1}`, `1${CALLERID(num)}`, `${CDR(accountcode)}`, substring modifiers) then continues to a destination; used to tag calls per DID/company, strip `+`, etc.

### 3.23 Text to Speech (tts) and TTS Engines (ttsengines)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24445144 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26706082
- TTS: destination object with Name, Text, Engine and follow-on Destination; synthesized prompt is played then the call continues. Engines module registers engines by name and binary path; flite is installed by default, others (Cepstral, Google etc.) require their own licence/binary.

### 3.24 Time Conditions (timeconditions) and 3.25 Time Groups
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24412281 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24314065 ; calendar support https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21332158
- Time Condition: name, Override Code PIN, Invert BLF Hint, Change Override (Unchanged / Reset / Temporary Matched / Temporary Unmatched / Permanent Matched / Permanent Unmatched — temporary overrides expire at the end of the current time span and can be toggled by the per-condition feature code, BLF, UCP/Phone Apps; permanent only from GUI/apps), Mode Time Group or Calendar (calendar/calendar group + time zone), Destination matches / non-matches.
- Time Group: unlimited rules of time start/finish, weekday range, month-day range, month range; blank fields mean "all"; rules with blank times act as exclusions (fixed-date holidays, floating holidays like 4th Thursday of November); also assignable to Outbound Routes to restrict when a route is usable.

### 3.26 Voicemail Blasting (vmblast)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24248563
- VMBlast Number dialled to leave one message in many mailboxes; Group Description, Audio Label (read group number or beep only), Optional Password, Voicemail Box List (multi-select), Default VMBlast Group (new extensions auto-added via extension "Default VMblast Group" option).

### 3.27 Wake Up Calls (hotelwakeup) — hotel feature, free
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21299361
- Schedule reminder/wake-up calls from a phone (`*68`, voice prompts) or GUI (destination, time, date); call list with delete.
- Settings: Operator Mode (operator extensions can schedule for any destination), Max Destination Length (allow outside numbers), Operator Extensions (patterns), Ring Time, Retry Time, Max Retries, Wake Up Caller ID (`"hidden" <num>` supported). Room status/mini-bar/PMS codes are the commercial Sangoma Property Management module.

### 3.28 Dynamic Routes (dynroute — community supported)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/22020565
- Prompt caller for DTMF (announcement, max digits, timeout, Asterisk REGEX validation, invalid retries/recordings/destination) and/or perform a live lookup, then route on the result: Source types None, MySQL (deprecated with app_mysql removal), ODBC function + query, URL (plain-text HTTP response), AGI script with result variable, Asterisk variable/expression (e.g. `${REGEX(...)}`, `$[...]`, `${SET(GROUP()=...)}`).
- Variables `[INPUT]`, `[NUMBER]`, `[DID]`, saved input/result variable names (exposed to dialplan as `${DYNROUTE_name}`), chaining of several dynamic routes, Default destination plus exact-match entry table (result value -> destination). Typical uses: account-number IVR, customer lookups, geographic routing.

---

## 4. CONNECTIVITY menu

### 4.1 API (api) — GraphQL and REST with OAuth 2.0 (15+)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/24182986 ; applications https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26148878 ; auth https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25722906 ; tokens https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26050564 ; API list https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25755702
- OAuth 2.0 application types: Web-server app (authorization code), Browser/Single-page (implicit), Native app (resource-owner password), Machine-to-Machine (client credentials); refresh-token grant; scopes per module (Scope Visualizer page); Access Tokens tab shows expiry, last use and source IP, allows revocation; API URL List (authorize, token, resource, GraphQL endpoint, REST base). Served on port 83 by default (Port Management).
- GraphQL covers most modules (built-in GraphQL Explorer and documentation pages). Documented queries/mutations include Core (add/update/delete/fetch extensions, create range of extensions, inbound routes CRUD, core devices, advanced settings), CDR (fetchAllCdrs/fetchCdr), Sysadmin (activation, licence, provisioning ports/protocols, hostname, SSL certs), Framework (install/uninstall/enable modules, reload, system status), plus module pages for Backup, Blacklist, Certificate Manager, Filestore, Firewall, Find Me/Follow Me, Ring Groups, SIP Settings, System Recordings, Voicemail, SMS, SIPStation, EndPoint, Broadcast. Install on 15 with `fwconsole ma install api`.
- Legacy `restapi` module (AGPLv3, contributed) provided the older RESTful API.

### 4.2 Call Forwarding, 4.3 Call Waiting, 4.4 Do Not Disturb (feature-code modules)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181736 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25985133 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181812
- Call Forwarding: server-side CF (unconditional), CFB (busy or DND), CFU (no answer/unavailable) via `*72/*73`, `*90/*91`, `*52/*53` (+ prompting and remote-extension variants), per-extension Call Forward Ring Time, Advanced Settings "Call Forward Ringtimer Default" (0 = ring timer, -1 = unlimited); state visible in Extension Settings report and settable in UCP.
- Call Waiting: per-extension Enable/Disable, `*70/*71`, Advanced Settings "CW Enabled by Default" and "Occupied Lines CW Busy" (unanswered CW call reports busy -> busy greeting).
- DND: `*78` on, `*79` off, `*76` toggle; UCP widget; automatic via Presence state; independent of handset DND.

### 4.5 DAHDI Config (dahdiconfig) and 4.6 DAHDI Channel DIDs (core)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25952375 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26017925 ; FreePBX 17 DAHDI/Wanpipe page https://sangomakb.atlassian.net/wiki/spaces/FP/pages/697860097
- Auto-detects Allo, Digium, OpenVox, Rhino, Sangoma cards; Global settings (language, busy detect + count, caller ID, call waiting, CID presentation, three-way calling, flash transfer, call forwarding, call return `*69`, echo cancel / EC when bridged / echo training, answer immediately, fax detection, RX/TX gain, free-form extra chan_dahdi.conf settings), System settings (tone region, system.conf extras), Modprobe and Module load order, Sangoma wanpipe settings (DAHDI mode, T1/E1).
- Digital spans (T1/E1/PRI, BRI, GSM) with signalling/switch type and group assignment; analog FXO (kewl/loop start, context from-analog) and FXS ports (mapped to DAHDI extensions); trunks pick DAHDI groups with round-robin/ascending/descending hunt (r0/R0/g0/G0).
- DAHDI Channel DIDs maps an analog channel to a pseudo-DID so inbound routes can match it. FreePBX 17 supports DAHDI/FXO on Debian 12.11 with Asterisk 21 (separate how-to).

### 4.7 Firewall (firewall, AGPLv3) — responsive firewall, zones, intrusion detection
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181828 ; responsive https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181896 ; services https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181855 ; zones 26050726 ; custom rules 26083485 ; safe mode 25756033 ; getting started 26148986 ; blacklist 25755946 ; intrusion detection 14.0.3/15.0.8 https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25690310
- iptables-based (16/17; nftables planned for 18), IPv4 + IPv6, deny-by-default. Zones: Reject, Internet (external; only HTTPS admin + UCP by default), Other (DMZ/VPN: UCP, unfiltered SIP/IAX), Local (internal: most services), Trusted (no filtering — for networks/hosts only; an interface left in Trusted raises a dashboard alert). Interfaces get a default zone; Networks tab overrides by host, CIDR, hostname or DDNS name.
- Trunks/peers are auto-discovered and allowed on their own protocol only; RTP range from SIP Settings is auto-allowed (unusual ranges refused).
- Services tab per zone: SSH, Web Management, Web Management (Secure), UCP, SIP (pjsip), CHAN_SIP, IAX, WebRTC, Let's Encrypt; Extra Services: Zulu UC, iSymphony, HTTP/HTTPS provisioning, OpenVPN server, REST Apps HTTP/HTTPS, XMPP, FTP, TFTP, NFS, SMB/CIFS; Custom Services (any local port) ; Blacklist tab (hosts/networks never allowed into Responsive, DNS names resolved later are auto-added).
- Responsive Firewall: exposes SIP/PJSIP/IAX to unknown hosts tentatively; after 10 unregistered signalling packets the host is dropped for 60 s; 50 failed attempts in 24 h (or 50 packets in under 10 s) -> 24 h block that extends while the attacker keeps sending; thresholds not configurable; Status tab shows pending/blocked hosts.
- Safe Mode (reboot twice within 5 minutes delays rules 5 minutes), "Firewall can not be disabled" lock file, custom rules files /etc/firewall-4.rules and /etc/firewall-6.rules (root-owned, enabled in Advanced), `fwconsole firewall` CLI (sync, lerules, trust/untrust, etc.), "Add /etc/hosts as Trusted".
- Intrusion Detection (fail2ban) tab (moved from System Admin in 14.0.3/15.0.8): Ban Time, Max Retry, Find Time, email, whitelist with Import from firewall zones and registered extension IPs (SIP/PJSIP/IAX), custom whitelist, Banned IPs list with per-IP unban or move to whitelist, Sync mode Legacy/Enabled/Disabled with 5-minute cron (`fwconsole firewall sync`), option to disable fail2ban on boot (dashboard alert), validation of whitelist entries. Works with the Firewall module installed but disabled.

### 4.8 Inbound Routes (core) — every option
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26116316
- General: Description; DID Number (exact or `_` pattern with X and [..]; blank = any/no DID); CID Number (exact, `_` pattern, or Private/Blocked/Unknown/Restricted/Anonymous/Unavailable; blank = any); CID Priority Route (CID-only routes win over DID-only routes); route precedence DID+CID > DID > CID > catch-all; Alert Info (SIP Alert-Info header for distinctive ring/auto-answer); CID name prefix; Music On Hold class for the call; Set Destination (any destination).
- Advanced: Signal RINGING (send 180 before answer), Reject Reverse Charges (PRI collect calls), Pause Before Answer (seconds, for shared analog lines/fax/alarm seize).
- Privacy: Privacy Manager (callers with no CID must enter their 10-digit number; Max attempts, Min Length), interacts with per-extension Call Screening.
- Fax: Detect Faxes Yes/No; Fax Detection type Dahdi / NVFax / SIP (T.38/CNG via `faxdetect`); Fax Detection Time (seconds of ringing while listening); Fax Destination (fax recipient user, or system fax email).
- Other: Call Recording policy; CID Lookup Source; Language (en, cn, de, es, fr, he, hu, it, pt, bp, ru, sv listed); Enable Superfecta Lookup + Scheme. Paging/notification on inbound (Page Pro), Class of Service and Extension Routing add extra fields when their commercial modules are installed.
- DIDs can also be bulk-imported (Bulk Handler) or created per extension ("Add Inbound DID"); GraphQL `addInboundRoute`.

### 4.9 Outbound Routes (core) — every option
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181933 ; Route Congestion Messages https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26509533
- Route Settings: Route Name (no spaces); Route CID; Override Extension (route CID beats extension CID; emergency CID still wins on Emergency routes); Route Password (numeric or path to an authenticate file); Route Type Emergency (forces extension Emergency CID) and/or Intra-Company (preserve internal CID name/number); Music On Hold class; Time Group (route only usable inside the group, else next matching route); Route Position (ordering; also drag-and-drop on the list — first match wins, emergency route first); Trunk Sequence for Matched Routes (ordered failover list of trunks); Optional Destination on Congestion (default Normal Congestion, or any destination such as a recording); Duplicate Route button.
- Dial Patterns: rows of `(prepend) prefix | [match pattern / CallerID]` with X, Z, N, [1-3], `.` wildcard; prefix is stripped, prepend added; CallerID column restricts the pattern to a calling extension number (extension-based routing without the commercial Extension Routing module); Dial Pattern Wizards (download local NPA-NXX patterns from localcallingguide.com, generic 7/10/11-digit, US toll-free, US information N11, US emergency 911/933 with prefixes, US international 011., 1NXXNXXXXXX); CSV import/export of patterns.
- Additional Settings: Call Recording policy (Force/Yes/Don't Care/No/Never); PIN Set (prompt for PIN from a PIN Set, optionally logged to CDR accountcode; per-extension "Pinless Dialing" bypass); Class of Service / Extension Routing / T38 Gateway (Fax Pro) / Notifications page group (Page Pro) appear only with the commercial modules.
- Route Congestion Messages module: choose the message or congestion tone played when no route matches ("No Routes Available") and when all trunks fail ("Trunk Failures"), with separate messages for Emergency and Intra-Company routes.

### 4.10 Trunks (core) — every type and option
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25690439 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25723188 ; sample configs https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26181983
- Types: SIP (chan_pjsip; chan_sip up to 16), IAX2, DAHDI, ENUM (e164.org lookup), DUNDi (limited; removed in 17), Custom (dial string with `$OUTNUM$`, e.g. `Local/$OUTNUM$@leastcost-custom`, `SIP/$OUTNUM$@host:port`, `IAX2/$OUTNUM$@ip`).
- General (all types): Trunk Name; Outbound CallerID `<NXXNXXXXXX>` or `"hidden" <num>`; CID Options = Allow Any CID / Block Foreign CIDs / Remove CNAM / Force Trunk CID (emergency CIDs always pass; intra-company routes pass internal CID); Maximum Channels (outbound; count inbound by using context `from-trunk-<name>`); Continue if Busy; Disable Trunk; Dial Pattern Manipulation Rules (prepend/prefix/match pattern, first match applies, number replacement by prefix-only match) with Dialled Rules Wizard (always dial with prefix, remove prefix from local numbers, directory assistance, local-number lookup NA-only, CSV upload); Outbound Dial Prefix (e.g. `9` or `w` pauses).
- PJSIP trunk — Simple: Permanent Auth Rejection, Retry Interval, Expiration, Forbidden Retry Interval, Max Retries, Qualify Frequency, Username, Secret, SIP Server, Port, Outbound Proxy, Contact User, Context (inbound), Transport, Codecs (ordered). Advanced configuration mode adds Client URI, Server URI and AOR Contact (permanent contacts); the GUI exposes further PJSIP endpoint/registration fields that the wiki guide does not enumerate.
- chan_sip / IAX2 trunk: free-form PEER details, USER context, USER details, Register String (`user:pass@provider[/DID]`).
- DAHDI trunk: pick group with hunt scheme (round robin ascending r0 / descending R0 / ascending g0 / descending G0) from DAHDI Config.

### 4.11 WebRTC Phone (webrtc) — see UCP Phone in 7.3.

---

## 5. REPORTS menu

### 5.1 Asterisk Info (asteriskinfo)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26182024
- Live snapshots: Summary (uptime, last reload, active SIP/IAX2 channels, registries, peers online/offline), Registries, Channels, Peers (name/host/status latency), SIP Info, IAX Info, Conferences (ConfBridge/MeetMe), Subscriptions (all BLF hints and watcher counts), Voicemail Users (new-message counts), Queues (waiting callers, logged-in members and paused/in-use states).

### 5.2 Asterisk Logfiles (logfiles) and Asterisk Logfile Settings
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26673201 ; settings page https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26542220 (empty)
- View the tail of /var/log/asterisk/full and other logs from the GUI (for recent events; CLI `asterisk -r` / `tail -f` recommended for depth). Logfile Settings module defines log files and levels for logger.conf (the wiki page has no body text).

### 5.3 Call Event Logging (cel)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26444382
- Lists all inbound/outbound calls from the Asterisk CEL table with a "Show" detail window of channel events per call, and plays associated call recordings; exposed to end users through the UCP Call Events widget (Asterisk 13+).

### 5.4 CDR Reports (cdr)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25824047 ; CSV https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26477005
- Raw CDR search by Call Date range, CallerID Number/Name, Outbound CallerID Number, DID, Destination, Destination CallerID Name, Userfield, Account Code, Duration, Disposition; playback/download of recordings; CSV export; remote CDR database option. Graphs/statistics dashboards are CDR Pro Reporting (commercial).

### 5.5 FreePBX System Status — see 1.4 Dashboard.

### 5.6 Print Extensions (printextensions)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26574919
- Printable list of every number dialable from outside (inbound routes/DIDs) and inside (extensions, ring groups, queues, conferences, parking slots, feature codes, misc apps, custom extensions) with their destinations; toggle sections, click-through to the object, printer-friendly view.

### 5.7 Weak Password Detection (weakpasswords)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26771582
- Reports extensions, trunks and user accounts with weak SIP secrets/passwords (fewer than 6 characters etc.) and raises dashboard security notifications; new extensions get 32-char generated secrets; "Require Strong Secrets" switch in Advanced Settings; Bulk import and Backup restore bypass validation.

### 5.8 Extension Settings report (extensionsettings) — located under Settings
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26804339
- One table of all extensions showing current Call Waiting, DND, CF/CFB/CFU, VmX busy/unavailable and Follow-Me states.

---

## 6. SETTINGS menu

### 6.1 Advanced Settings (framework)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26804291 (plus settings referenced from other guides)
- Hundreds of framework/module settings with tooltips, grouped (Dialplan and Operational, Device Settings, System Setup, GUI Behavior, Module Admin, Ring Group, Certificate Manager, Firewall, Asterisk REST Interface, etc.); "Display Read Only Settings" / "Override Readonly Settings" unlock protected ones. Settings cited in the guides: Force All Internal Auto Answer; Show All Device Settings on Add; Send RPID default; default SIP/DAHDI callgroup & pickupgroup; Enable Custom Device States; Waiting Period to Stop Asterisk (120 s); Asterisk Dial Command Options (e.g. `r`); Ringtime Default; 24-hour format; Call Forward Ringtimer Default; CW Enabled by Default; Occupied Lines CW Busy; Max Paging Participants; SIP Channel Driver (chan_sip / chan_pjsip / both); User & Devices Mode; Display Extension Ring Group Members; Set Module Admin to Edge mode; Require Strong Secrets; Authorization Type (usermanager); certificate validity days; custom firewall rules enable; NodeJS ports 8001/8003 and TLS; Asterisk mini-HTTP 8088/8089; RSS feeds; VEGA cache; Honor Wrapup Time across queues.

### 6.2 Asterisk IAX Settings (iaxsettings)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26738784
- Codec list/order (ulaw, alaw, gsm, siren14, lpc10, speex, g722, adpcm, siren7, g723, slin, g726, g729, ilbc, g726aal2), Codec Priority (host/caller/disabled/reqonly), Bandwidth low/medium/high, Video support (h264, h263p, h263, h261), registration min/max expiry (60/3600), Jitter buffer (enable, force, max size 200 ms, resync threshold 1000, max interpolations), Language, Bind Address/Port (4569), Delay Auth Rejects, free-form Other IAX Settings.

### 6.3 Asterisk Manager Users (manager)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26771608
- Create AMI accounts: name, secret, Deny and Permit IP/mask lists (`&` separated), read/write rights per AMI class; used by dialers, CRMs, wallboards, FOP2 etc.

### 6.4 Asterisk REST Interface Users (arimanager)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25824129
- Enable ARI in Advanced Settings (internal ARI user/password, pretty-print JSON, websocket write timeout); add external ARI users with username, password (crypt or plain), read-only flag.

### 6.5 Asterisk SIP Settings (sipsettings)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26542239 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26574980 ; STUN list https://sangomakb.atlassian.net/wiki/spaces/PG/pages/25824149
- General tab: Allow Anonymous Inbound SIP Calls (needed for SIP URI/ENUM inbound), External Address + Local Networks with "Detect Network Settings", RTP port range (default 10000–20000), RTP checksums, Strict RTP, codec list and order (ulaw, alaw, g722, gsm, etc.; g729 noted as requiring commercial licensing), RTP timers (rtptimeout/rtpholdtimeout/rtpkeepalive), STUN server field in the WebRTC section (needed by UCP Phone), free-form "Other SIP Settings" (any sip.conf general directive, e.g. `notifycid=yes`, `faxdetect=no`).
- Legacy page adds: NAT yes/no default, IP Configuration (Public IP / Static IP with External IP / Dynamic IP with Dynamic Host) and Local Networks. Per-driver tabs (chan_pjsip transports UDP/TCP/TLS/WS/WSS with certificate selection; chan_sip on 16 and earlier) exist in the GUI, but the current wiki does not document them field by field; inbound-route SIP fax detection requires `faxdetect=yes` in the SIP settings. A Provider Specific Settings page lists carrier quirks.

### 6.6 Extension Settings — see 5.8.

### 6.7 Fax Configuration (fax) — free inbound fax
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26574994 ; user fax settings https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20808182
- Free module provides inbound fax-to-email via Asterisk res_fax (SpanDSP / T.38): global Default Fax Header, Default Local Station Identifier, Outgoing Email address, system Email address (used by the `666` Dial System Fax code and legacy detection), Error Correction Mode, Max/Min transfer rate, Default Paper Size (Letter/A4).
- Per user (User Management > Fax): Enabled and Attachment Format (PDF/TIFF/both) are free; a user with fax enabled is selectable as Fax Recipient on inbound routes/fax detection. Store Locally, outbound faxing from UCP (coversheets, station ID, retries 0–3, email results Never/Always/On Success/On Failure, Inbox/Archived/Outgoing/Sent/Failed folders) and T.38 gateway on outbound routes require Fax Pro (commercial).

### 6.8 Filestore (filestore, 15+)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26640528
- Storage back-ends used by Backup & Restore (and warm spare): Email (list name, from, addresses one per line, max attachment size default 25 MB), FTP (host, port, TLS, SFTP, user/pass, filesystem type, absolute path, active/passive, timeout), Local path, Dropbox (OAuth2 access token, app folder path), SSH (host, port, user, private key path — RSA on 15/16, ECDSA on 17 — remote path), S3 (display name, bucket, region, access key, secret, path). Failed remote writes fall back to /var/spool/asterisk/backup/.

### 6.9 Music on Hold (music)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26575033
- Ships 11 default tracks; unlimited categories; upload WAV/MP3 (MP3 converted to WAV, per-file volume adjustment at upload), enable/disable random play, delete files; Streaming categories (application path such as `mpg123 ... http://stream`, optional format ULAW; not recommended for production). Categories are selectable per inbound route, queue, ring group, outbound route, conference, parking lot, follow-me.

### 6.10 PIN Sets (pinsets)
Source: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26444508
- Named lists of PINs (one per line, description max 50 chars), "Record in CDR" writes the PIN to the CDR accountcode; attached to an Outbound Route (Additional Settings > PIN Set) so callers must enter a valid PIN; per-extension Pinless Dialing bypass. Per-user PIN management is PINSet Pro (commercial).

### 6.11 Route Congestion Messages (outroutemsg) — see 4.9.

### 6.12 Text to Speech Engines — see 3.23.

### 6.13 Voicemail Admin (voicemail) — system-wide voicemail
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26509545 ; Dialplan Behavior https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21266519 ; Advanced Settings https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21397558 ; Timezone definitions https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21004564 ; multiple e-mail addresses https://sangomakb.atlassian.net/wiki/spaces/PG/pages/21332042 ; BLF on mailbox https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20351184
- Usage/Stats: view voicemail usage per mailbox and globally, delete message files, edit any mailbox's settings (same fields as the extension Voicemail tab), define voicemail time zones (tz definitions with custom date/time wording).
- Dialplan Behavior: Disable Standard Prompt, Direct Dial Mode (unavailable/busy/no message), Voicemail Recording Gain (dB), Operator Extension (destination for "0"), VmX Locater globals (Msg Timeout 2 s, Times to Play Message, Error Re-tries, disable standard prompt after max loops / on `dovm`).
- Advanced Settings (voicemail.conf general): attach, emailsubject (default "PBX Voicemail Notification"), emailbody template with VM_NAME/VM_DUR/VM_MSGNUM/VM_MAILBOX/VM_CALLERID/VM_DATE, emaildateformat, fromstring/serveremail, pager subject/body/from, mailcmd, format (wav49|gsm|wav), maxmessage/maxsecs (300 s), minsecs, maxsilence, silencethreshold, maxgreet, maxmsg (100, max 9999), maxlogins, minpassword, forcename, forcegreetings, tempgreetwarn, envelope, saycid, sayduration/saydurationm, review, operator, callback/dialout/exitcontext contexts, sendvoicemail, usedirectory, moveheard, nextaftercmd, backupdeleted, pbxskip, skipms, listen-control-* keys, volgain (sox), pollmailboxes/pollfreq (MWI), externnotify (default vmnotify-newvm.php), externpass/externpassnotify, IMAP storage (imapserver, authuser/authpassword, imapgreetings, greetingsfolder, imapparentfolder, timeouts, flags), ODBC storage (odbcstorage/odbctable), SMDI, ADSI, custom password prompts (vm-password etc.), charset, cidinternalcontexts, searchcontexts, userscontext.
- User-side: greetings (unavailable, busy, name, temporary) recorded from `*97/*98` menus or uploaded/recorded in UCP; password change in phone menu or UCP; Exchange/UM integration how-to; voicemail to multiple e-mails via alias; BLF hint on a mailbox for MWI lamp. Voicemail notifications with per-user templates/SMS are VM Notify (commercial); voicemail usage reports are Voicemail Reports (commercial).

---

## 7. USER MANAGEMENT and UCP

### 7.1 User Management (userman, AGPLv3)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20840809 ; users 21299278 ; groups 19991803 ; directories https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20710028 ; group/user settings https://sangomakb.atlassian.net/wiki/spaces/PG/pages/20808182
- Users: login name, description, password, groups, Primary Linked Extension (1:1), user details (display name, email, first/last name, title, company, cell/work/home/fax, language, time zone, contact image, date/time formats), quick password change, welcome e-mail (templated subject/body with variables, HTML option, resend to many), bulk CSV via Bulk Handler, auto-created from Extensions.
- Groups: name, description, locale defaults, member list; every permission below can be set at group level with per-user Yes/No/Inherit.
- Directories (multiple, ordered, one default): PBX Internal, Microsoft Active Directory (and legacy), OpenLDAP (and legacy), Voicemail directory; enable/disable, scheduled synchronisation (sync logs userman_sync.log). OAuth/SAML/MFA login are commercial (SAML, MFA modules) — not in the free module.
- Password policy (16+): force reset on first login, password expiry days (default 90) with reminder days (5), complexity thresholds (length, upper, lower, numeric, special, punctuation, weak-password detector threshold) enforced on UCP password changes.
- Permission areas: Administration GUI (allow admin login, full admin rights, visible extension range, per-module Administration Access); Conferences (auto-create room 8+ext, add to conference IVR — Conference Pro); Contact Manager (show in / viewable groups); Fax (Enabled, attachment format free; rest Fax Pro); Phone Apps (commercial); CRM (commercial); VPN (Sysadmin Pro); UCP (allow login, active sessions with kick, Allowed Extension Settings, Enable Originating Calls i.e. click-to-dial via desk phone, Appointment Reminder, CDR/CEL access per extension with playback/download rights, Conferences, End Point Manager buttons, Presence, SMS DIDs (SIPStation), System Admin VPN download, Voicemail access per mailbox with playback/download/settings/greetings/VmX rights, WebRTC phone enable + certificate, Zulu tab (legacy)); XMPP (legacy chat account); Zulu (legacy); Missed Call Notification (contributed module adds its tab).

### 7.2 UCP — User Control Panel (ucp, AGPLv3; UCP 14+ redesign, 15+ templates)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41288462 ; dashboards 41943044 ; widgets 41615714 ; side bar 41222918 ; settings 41746722 ; templates https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41779551 ; module pages 41452026, 41943083, 42008623, 42008638, 41255600, 41222991, 41517591, 41452088, 41190053, 41943137, 41812244, 41223049, 41648520, 41255663, 42008670
- Framework: browser UI on its own port (81 default; HTTPS recommended), login with User Management credentials, multiple named Dashboards (tabs; add/rename/reorder/lock/delete), Dashboard Widgets on a 12-column drag/resize/lock grid, Side Bar Widgets (global: Presence, Phone, Chat, Missed Calls), per-widget settings gear, desktop notifications, UCP tour; user Settings dialog (username/password change, user details + Gravatar, language, time zone, date/time formats); Node.js server for real-time updates (ports 8001/8003).
- UCP Templates (15+): admin builds a dashboard layout via the `FreePBXUCPTemplateCreator` virtual user or imports from any user, assigns per group/user (Inherit), "Rebuild Widgets" or "Merge With Existing", user-side "Reset" button, templates exported/imported through Bulk Handler as JSON-in-CSV.
- Free widgets: Voicemail (per mailbox: list with date/CID/duration, in-browser playback, call-me-to-play, forward to another mailbox, download, delete, Asterisk folders; settings: PIN, email, attach, play CID, play envelope, delete after email, auto-refresh; greetings Unavailable/Busy/Name/Temp with play, upload, in-browser record over HTTPS, delete; VmX Locater enable/use when/press 0/1/2); Call History (CDR with direction/voicemail/conference icons, recording playback/download) and Call Events (CEL based, intended replacement); Call Forwarding (Unconditional/Unavailable/Busy numbers + ring timer); Call Waiting toggle; Do Not Disturb toggle; Find Me/Follow Me (list, announcement, initial ring, list ring time, confirmation); Contacts (personal groups, add/edit/delete contacts with numbers/XMPP/email/website/avatar; click-to-call); Presence (status selector; set status on login/logout; per-status automatic DND/Follow Me actions); Phone (WebRTC in-browser phone, see 7.3); Conferences status/control (requires Conference Pro); Device Management (requires UCP for EPM); Fax (requires Fax Pro; free users only get fax-to-email); SMS (SIPStation/SMS Plus); RSS Feeds (from Advanced Settings); Chat (XMPP — removed in 17); Missed Call Notification widget (contributed); VPN config download (Sysadmin Pro).

### 7.3 UCP Phone / WebRTC Phone (webrtc)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/41812244 ; https://sangomakb.atlassian.net/wiki/spaces/PG/pages/38634428
- Browser softphone (SIP over WSS, DTLS-SRTP) that rings together with the user's primary extension (a hidden 99XXXX device in device/user terms); enabled per user/group in User Management > UCP > Phone with a Certificate Manager certificate; requires valid HTTPS certificate (Let's Encrypt), Asterisk mini-HTTP 8089, STUN server configured in SIP Settings; features: dial pad, answer/hangup, hold/unhold, call timer in side bar, silence ringer, disconnect (appear offline); calls follow the primary extension's CID/route rules. Supported in Chrome/Firefox/Edge/Opera-era browsers.

### 7.4 Zulu / Sangoma Connect — what remains free
Sources: FAQ https://sangomakb.atlassian.net/wiki/spaces/FP/pages/279052296 ; community https://community.freepbx.org/t/freepbx-17-and-zulu/96562 ; Sangoma Talk FAQ https://sangomakb.atlassian.net/wiki/spaces/SS1/pages/31392032
- Zulu UC is deprecated/EOL and not available in FreePBX 17 (it was a licensed product with a small free user allowance on 15/16). The replacement "Sangoma Softphones" module (Sangoma Talk mobile / Sangoma Phone desktop) is licensed per user; Sangoma's FAQ mentions a free 2-user, 1-year trial licence. The only fully free softphone path in 17 is the UCP WebRTC Phone (7.3) or any third-party SIP softphone registered as a PJSIP extension.

---

## 8. OTHER free modules and concepts

### 8.1 OSS End Point Manager (endpointman — community supported)
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/26050792 ; https://github.com/FreePBX/endpointman ; https://github.com/provisioner/Provisioner
- Community phone-provisioning GUI (fork of the original FreePBX endpointmanager, GPLv3) that uses the separate Provisioner project's brand/family JSON templates packaged as tgz "endpoint packages"; generates config files served by TFTP/HTTP. Not supported by Sangoma; the wiki only links a tutorial video and the two repos. Brand coverage was not documented in the pages read (the Provisioner README does not list brands; data lives per brand/family in the repo). The commercial Sangoma EndPoint Manager (templates, firmware, BLF layouts, UCP button editing) is the supported alternative.

### 8.2 Speed Dial (speeddial), Asterisk Phonebook (deprecated) and Contact Manager speed dials
Sources: https://sangomakb.atlassian.net/wiki/spaces/PG/pages/18416059 ; Contact Manager page ; feature code table
- Speed Dial module: `*75` lets a user set a personal speed dial; `*0<code>` dials it. Asterisk Phonebook (deprecated module) gave system-wide name/number/speed-dial entries with CSV import/export, a `411` dial-by-name directory and an "Internal" CID lookup source; Contact Manager now carries system speed dials (`*10<code>`) and CID lookup via Superfecta.

### 8.3 Outbound CNAM (outcnam — contributed, 17.0)
Source: module.xml https://github.com/FreePBX-ContributedModules/outcnam
- Admin-menu module storing a Superfecta scheme to look up caller names on outbound calls, with options to write the result to CDR and to send it in RPID/PAI (fields enable_cdr, enable_rpid, scheme). No wiki guide; options beyond module.xml were not documented.

### 8.4 Dictation (dictate), Info Services, Camp-On, Call Screening
- Dictation: per-extension service (format, e-mail) with `*34`/`*35` (section 3.10). Info Services: `*43` echo test, `*60` speaking clock, `*65` speak extension, `*69` call trace. Camp-On (CCSS) GUI module is deprecated but Asterisk CCSS policies remain per extension. Call Screening (caller says name) is a per-extension option and is triggered for no-CID callers via inbound-route Privacy Manager.

### 8.5 Hotel-style features in the free set
- Wake Up Calls (3.27), Voicemail Blasting, Call Flow Control, DISA, Paging, Parking; room-status/mini-bar/check-in PMS (`*36/*37/*44`) belongs to the commercial Sangoma Property Management module.

### 8.6 Queue-related commercial boundary (for comparison)
- Free Queues module has no callback-in-queue; Queue Callback, virtual queues, queue "Plus" options are VQ Plus; agent/queue reporting and wallboards are QXact Reports; Phone Apps queue login screens are commercial. Free alternatives: feature codes `*45/*46/*47`, Asterisk Info Queues snapshot, raw queue_log, AMI/ARI.

### 8.7 Extension Routing concept
- The free way to restrict which extensions may use a route is the CallerID column in Outbound Route dial patterns (section 4.9) or PIN Sets; the commercial Extension Routing module adds a per-route allowed-extension list, and Class of Service generalises it.

### 8.8 Translations / localisation
- freepbxlocalization repo ships GUI translations (all .po files, plus Russian and Japanese); UCP and admin GUI language selectable per user; prompts via Sound Languages.

---

## 9. Coverage notes — what could not be documented from primary sources

- Allow List and Outbound CNAM: only module.xml metadata and the feature-code table exist; no Sangoma user guide (option-level detail such as destination for non-allowlisted callers is undocumented).
- OSS End Point Manager: no feature/brand list on the wiki or in the READMEs read.
- Asterisk Logfile Settings: wiki page is empty.
- Asterisk SIP Settings chan_pjsip tab: the current wiki user guide only documents the General tab; PJSIP transport/T.38 field names above come from references in other guides (WebRTC/STUN, fax detection), not a field-by-field page.
- Advanced Settings: no exhaustive option list is published; only options referenced in other guides are listed.
- freepbx.org blog posts (FreePBX 17 GA, Debian future) returned HTTP 403/404 to the fetcher; 17 details were taken from the Sangoma wiki, FAQ and community threads instead.
- Zulu free-user allowance on 15/16: only the Sangoma Talk FAQ's "free 2-user 1-year licence" statement was found; no page states the historical Zulu free tier.
- IVR "alias" option: not present in the IVR user guide; not documented.
- Framework dialplan context names are taken from references inside module guides (DISA, trunks, Print Extensions, Superfecta example), not from a dedicated architecture page.
