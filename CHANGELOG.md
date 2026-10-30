# Changelog

All notable changes to Veyra are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/). Before 1.0 the minor
version counts completed milestones in roadmap order (Milestone 4 → 0.4.0,
Milestone 4b → 0.5.0, Milestone 5 → 0.6.0, …); patch versions carry fixes
between milestones; `-dev` marks work in progress. Milestones 0 to 3 all
shipped as `0.1.0-dev.0` before this scheme was adopted.

## 0.27.55 — 2026-10-30

No migration.

### Added
- **Template editor** (#350): a local template showing *Parent updated* can take the new version as its parent, after Veyra checks that it still works. A local template that fails to load can be opened, repaired or deleted.

### Fixed
- **Customize** no longer adds an empty `model_settings` block to files whose parent has no such block, such as the Algo template, where changes were silently ignored. Such a file is now a full copy to edit, and saving a block the parent file does not have is refused, with the reason.

## 0.27.54 — 2026-10-30

No migration.

### Added
- **Provisioning requests page** (#347): Provisioning → Requests lists what phones asked for and what they got, including refused requests, with the reason in plain words. Filter by MAC, address, file or result. Kept 30 days, as the retention settings say. A phone Veyra does not know belongs to no organization yet, so only platform administrators see its requests.

## 0.27.53 — 2026-10-30

No migration.

### Fixed
- **Active Calls shows which calls are being recorded** (#351), including calls recorded by a policy or from a phone, and still shows it after you reload the page. Only a recording started from the web has **Stop recording**; the others show a *Recording* badge.

## 0.27.52 — 2026-10-30

No migration.

### Added
- **Change a user's email address and delete a user** (#352): both on the user's page. Changing an address signs the person out, cancels any reset link and tells the old address; accounts from an identity provider keep the provider's address. A user must be disabled before deletion; their phones and voicemail stay, unassigned, and recordings, call history and the audit log are kept.

## 0.27.51 — 2026-10-30

No migration. Deploy changes once after updating.

### Fixed
- **Voicemail PIN changed from the phone is kept** (#346): before, the next deployment put the old PIN back. A new PIN from the phone must now have at least 4 digits, and more than 10 is not kept. Changing a PIN from the phone is written to the audit log. Deploy changes shows as pending afterwards; deploying does no harm.

## 0.27.50 — 2026-10-30

No migration.

### Added
- **Export call recordings**: Telephony → Call Recording → Recordings → **Export** downloads the recordings the filters show as a ZIP: audio as MP3 (or the stored Ogg Opus) named with the call's date, time, direction and numbers, plus `recordings.csv` with the call details of each. New permission *Download many recordings at once*, given to organization administrators. Each export is written to the audit log with the recordings it held. Exported files are not encrypted.
- The Recordings list can be filtered by end date, direction, and number or name.

### Changed
- **Download** on a recording now saves an MP3 with a readable name, which plays in any audio player.
- The Call History CSV has a `recording_ref` column that matches the export's spreadsheet.

## 0.27.49 — 2026-10-30

Migration 0073. Deploy changes once after updating.

### Added
- **Conference rooms, live** (#96): the room's page can now **start and stop recording** and **invite a number**: it rings an extension or outside number, who joins without the PIN when they answer. The call follows your phone's class of service, and emergency numbers are refused. A room set to record every meeting cannot be stopped from the page.
- **Room owners and the Conference widget** (#96): name the phones that own a room, and their users get that room's live controls in a new **Conference** widget on My Phone, with no administrator permission.

## 0.27.48 — 2026-10-30

No migration.

### Added
- **Google Drive backup destination** (#344): System → Backups → Add destination → **Google Drive** copies backups to a Shared drive through a service account, with each file's checksum compared after upload. The recording archive can use it too. The service account must be a **Manager** of the Shared drive; the Test button checks this by deleting a test file for good.

## 0.27.47 — 2026-10-30

Migration 0072.

### Added
- **Recording archive**: System → Backups → **Recording archive** keeps a copy of every call recording on a backup destination (folder, SFTP or S3-compatible), in case the server is lost. A copy lives exactly as long as its recording: when a recording is deleted, by hand or at its retention date, its copy is deleted too, within about an hour, and Veyra checks that it is gone. If it cannot delete a copy, it keeps trying and raises the backup alert. Encrypted recordings stay encrypted.

### Fixed
- **Let's Encrypt with high availability** (#43): the standby now takes over the public certificate fully. After a switchover the new primary serves it for the public name, the SIP TLS transport can present it, and it keeps renewing. Before, the new primary served the Veyra certificate until someone pressed **Get the certificate**, and the certificate would not renew there.

## 0.27.46 — 2026-10-30

Migration 0071 (adds a column for the new destination). The web server's settings change (the update applies them).

### Added
- **From FreePBX: recordings and hold music** (#42): System → Import and Export → From FreePBX → **Import the audio** takes an archive of the server's sounds and hold music folders. Recordings keep their FreePBX names, so the imported IVR menus find them, and each hold music folder becomes a hold music set. It only adds, so you can run it again.
- **Custom dialplan** (platform administrators only): System → Telephony Engine → **Custom dialplan** holds your own `[custom-…]` Asterisk contexts, deployed like any other change. Commands that reach the server's shell or files are refused, and every change is in the audit log. Calls reach them through a new **Custom dialplan** destination, on inbound routes, menus, ring groups, queues and the other places a call can be sent, which only platform administrators can choose. A context must have an `s` extension to be offered, and one in use cannot be removed.
- **From FreePBX: dynamic queue agents** (#42): add the output of `asterisk -rx "database show QPENALTY"` and queue agents who log in with a code come over too.

### Fixed
- **Firmware uploads over 25 MB failed** at the web server, although Veyra accepts images up to 512 MB. Firmware uploads and FreePBX files can now be up to 1 GB and take up to 15 minutes.

## 0.27.45 — 2026-10-30

No migration.

### Added
- **Recordings**: a **Delete** button (deletes the audio now instead of at its retention date, audited), and filters by organization, start date and **Show deleted**.
- **Extended absence for many boxes** (Voicemail → **Extended absence…**): one away period, such as the summer break, for the boxes you pick, with or without taking messages.
- The trunk page shows the engine's registration status word (for example *Rejected*), the queue **Agents** card shows who last changed each agent and when, outbound routes show which organization or site they are for, and classes of service show their supervisor settings.
- The fax cover sheet has a **From** field (empty: your name).
- A phone's **Building** and **Location (dispatchable)** can be changed on its page; before, only when registering it.
- Firmware images have an **Edit** button for their models and notes, and the upload dialog offers the manufacturers Veyra has templates for (a misspelt manufacturer hid the image from profiles).
- Call history filters by talk time and by recorded or not (the CSV export follows).
- A revision on System → Telephony Engine can be deployed **When no calls are active**, like the top-bar button.
- The template editor's **Insert a Veyra variable** panel lists the provisioning variables (`{{ vars.name }}`).
- **New extension** offers the organization's extension templates and, with many users, a search for the user.
- Supervisors with more than one extension choose which phone rings on Active calls (**Supervise from**).
- A site's emergency settings can play a **recorded page** when an emergency call is made there, and the responder list shows the site's extensions first.
- **Audit log**: a date range and **Export CSV** (the same filters; up to 100,000 events).
- Integration tokens can be given **metrics.read** to scrape the Prometheus metrics (`/api/v1/metrics`); being server-wide, only a platform administrator can grant it, and it gives nothing else.
- Speed dial, BLF and intercom keys accept numbers typed with spaces, dashes or brackets (`+1 (573) 555-0100`), as users' own keys already did; the hint for each key's value shows under the field instead of only on hover.

### Fixed
- **A recording in use can no longer be deleted.** Deleting a recording that a call queue, recording policy, recorded page or bell played silently removed it from them; now the delete is refused with the list of what uses it, and the Audio page's **Used by** counts all of them.
- The My Phone **Announcement** widget shows the layout's current text for people who rearranged their own My Phone; before, they kept the text from when they saved.
- The firewall page shows its Allow, Block, Lift, feed and settings controls only to people who may change the firewall.
- The emergency route warning no longer counts extensions whose site has an emergency number; removing a route's time condition also clears its after-hours fax inbox.
- An emergency site's notification page must belong to the site's organization (it could be another organization's), and the site dialog lists only that organization's pages and extensions.
- Text after creating a shared inbox and on the account's Voicemail card says how to open a shared inbox (**\*98** and its number).
- **A customized phone template now applies only to its own organization.** Before, customizing a model template (say Poly VVX 450) in one organization changed the files of that model's phones in every organization whose profile used the family, and other organizations saw it in their template list. A **Platform-wide** template still applies everywhere.
- **Phone passwords in profiles and devices are no longer shown.** Secret template settings (such as the phone's administrator password) come back masked; leaving the dots in place keeps the saved value, typing replaces it.
- **Editing a My Phone layout** (System → Portal layouts) opened the dialog empty, so saving could overwrite the layout with blanks. It now opens with the layout's own settings.
- Yes/no setting overrides on a phone's page are a choice (**As the profile**, **Yes**, **No**) instead of a text box where a typo silently meant no.
- **Out-of-date text across the interface**, found while writing the guides: "coming later" notes for things that exist (dashboard, first-run setup, Settings, users, feature codes, paging zones, provisioning templates), wrong menu paths (Audio, Directory → Sites, Phone provisioning, Email delivery), the email card saying only voicemail uses it, the shared-inbox text (members open it with **\*98**), conference recordings, pickup, bells (start, end or both), the extension's voicemail card, the import kinds, and the central console's ignored update-source field (removed).
- The dashboard's **SIP trunks** row shows how many trunks are up instead of "not available yet", and says why counts are missing (engine not answering, or server-wide counts not shown to you). The HA **Details** link shows only to those who can open it.
- Inbound routes list every kind of destination by name; before, anything but an extension or a menu showed as "Voicemail of".
- First-run setup lists where to set up outside lines, email, backups and updates afterwards, instead of milestone numbers.
- Paging zones show the pending-deployment banner; the zone dialog says dialling a zone needs a deployment.
- Single sign-on users see where to change their password instead of a password form that cannot work; the sign-in method shows as Google, Microsoft or Single sign-on.
- **Change PIN** is no longer offered for shared inboxes (it could not work); the PIN shown after a reset names a shared inbox correctly.
- The **Email** dialog in a voicemail inbox no longer deletes the message by default.
- The site **Time zone** is a list like the organization's, the New extension dialog no longer keeps the previous emergency caller ID, **New organization** is disabled while multi-tenancy is off, the Registrations search waits for typing to stop, and the Phone provisioning card explains how to turn on the plain-HTTP bootstrap.

## 0.27.44 — 2026-10-29

No migration.

### Added
- **Companion rollout guide**: System → **Companion rollout** walks through putting the Companion extension in people's browsers in five steps — where the browsers are managed (Google Admin console, Windows Group Policy or Intune for Chrome and Edge, or people install it themselves); making the browsers trust the server (nothing to do with a public certificate, otherwise how to push the Veyra CA certificate, with the download); how people sign in (password or single sign-on, with silent sign-in on managed Chromebooks); pushing the extension (the values to copy, exact console steps, and a registry file for Chrome and Edge on Windows); and a check that shows who has signed in to the Companion and from which device, with what to look at when nobody has.

- **Help built into Veyra**: a **Help** link in the top bar opens the guide for the page you are on (**How do I…?**), or the list of guides, with search. Each guide says which Veyra release it was last reviewed for. Administrators see the setup guides; everyone sees the guides for users. 64 guides cover every page: getting started, phones and devices, trunks and routing, call features, paging and bells, voicemail and fax, sign-in and security, maintenance, and guides for everyone (My Phone, voicemail, account security, the Companion).
- **Guides on the GitHub wiki**: the same guides are published to the project wiki at every release, each page stamped with the release it reflects and its date.
- **Guides kept current**: each guide names the parts of Veyra it describes; when one of them changes, the guide must be reviewed before the next release (docs/GUIDES.md).

- **Roll back a module**: the Module Manager shows **Roll back** when the previous version of a module is kept, with the version it goes back to. Before, this was only possible through the API.

- **Backup destinations** (#44): System → Backups → **Destinations** copies every verified backup to a NAS folder, an **SFTP server** or **S3-compatible storage** (Amazon S3, Backblaze B2, Wasabi, Cloudflare R2, MinIO…), up to five. SFTP signs in with Veyra's own SSH key and a confirmed host key; S3 secrets are stored encrypted. Each copy is checked; a failed copy raises the new **Backup copy to a destination failed** alert and is retried with the next backup; each destination can keep its own number of backups. **Test** checks a destination at any time.

### Changed
- Settings → **Companion extension deployment** is now a short summary with a button to the rollout guide.
- The backup **Copy to directory** setting became a **Folder** destination (*Copy folder*); nothing to redo.

### Fixed
- Rotating the installation key now also re-encrypts the Let's Encrypt DNS credentials and EAB key; before, they could no longer be read after a rotation.

## 0.27.43 — 2026-10-29

Migration 0070 (a column for test sign-in results, and the extension's fax machine setting).

### Added
- **Guided single sign-on setup** (#335): System → Sign-in → **Set up a provider** walks through connecting Google Workspace, Microsoft Entra ID or another OpenID Connect provider in five steps — choose the provider, register Veyra in its console (exact steps for each, with links, the redirect address to copy, and for Microsoft where to find the tenant ID and the secret's *Value*), enter the credentials, choose who can sign in, then test and turn on. The provider is saved turned off, so people only see its button once you turn it on.
- **Test sign-in**: from the last step (or **Test** on a provider's row) you sign in through the provider exactly as people will, and Veyra shows which account it would use — already linked, linked by e-mail on first use, or created with its role — or why it would be refused, with a hint for the usual mistakes (wrong secret, redirect address, domain, no account). It signs no one in and changes nothing, and works before the provider is turned on.
- **Grandstream ATAs** (#37): official templates for the HT801 and HT802 (`grandstream.ht80x`) and the HT812, HT814 and HT818 (`grandstream.ht81x`), first and second generation: one extension per analog port (line 1 on port 1), voicemail indication (stutter tone and lamp), hotline and warm line for door, elevator and emergency phones, time and daylight saving, VLAN, firmware, the daily provisioning check with the device credential and the Veyra CA. The ATA's own star codes are turned off so *69, *72, *78 and the other feature codes reach Veyra. Experimental until checked on hardware.
- **Fax machines on ATAs** (#37): an extension's new **Fax machine (T.38)** switch (extension page, Phones tab) offers T.38 to it, so a fax relays end to end over a trunk with T.38 on; the ATA template puts that port in T.38 and every other port in G.711 pass-through, which works with any trunk. The `fax_mode` template variable can force one mode for every port. Needs a deployment.
- **Template editor: Insert a Veyra variable** (#339): beside a local template's source file, a searchable panel lists the template's values, every fact Veyra provides (device, organization, lines, keys, paging zones, server, features) with what it holds, and common snippets; a click inserts it at the cursor, and a list's loop is one click too.
- **Template editor: Variables form** (#339): a local template's own variables can be added and edited as a form (name, type, default, description, required, secret, allowed pattern, maximum length), and inherited variables can get a different default in this template — no more editing the manifest by hand.

### Changed
- The Sign-in page's **Add provider** button is now **Set up a provider**; the setup notes card moved into the guided setup. Edit still opens the dialog.
- The hotline help on the extension page now says it reaches every provisioned phone and ATA, not only Poly and Yealink.

## 0.27.42 — 2026-10-29

No migration.

### Added
- **Grandstream phones** (#36): official templates for the Grandstream GRP26xx (GRP2601–GRP2604, GRP2610–GRP2670) and GXP21xx (GXP2130, GXP2135, GXP2140, GXP2160, GXP2170) desk phones, from the same profiles, keys and variables as the Poly and Yealink phones: up to six lines, line, BLF, speed dial, transfer and multicast paging keys, voicemail indication, the profile's paging zones as multicast listen addresses, time zone and daylight saving, VLAN, firmware, the daily provisioning check with the device credential, the phone directory, hotline and intercom auto-answer. The phones install the Veyra CA from their configuration, so no manual certificate step is needed. Experimental until checked on hardware.

### Fixed
- **Previewing a Yealink template in the template editor failed** ("no attribute 'directory_url'") since 0.27.0: the preview's sample server lacked the directory address. It now has it, with the host and provisioning path the Grandstream templates use. Previews of a real phone (device page) were not affected.

## 0.27.41 — 2026-10-27

Run the installer's upgrade once (`sudo installer/upgrade.sh --yes`) for the certificate helper, its unit and permission, certbot and the new NGINX server; no migration.

### Added
- **A certificate every browser trusts, from Let's Encrypt** (#43): System → Settings → **HTTPS certificate** gets a certificate for the server's public name from Let's Encrypt (or another ACME authority, staging for a trial run), proving the name with a DNS record (Cloudflare, Route 53, Google Cloud DNS, DigitalOcean, Linode, DNSimple, OVH, or your own DNS server through RFC 2136) or a web request on port 80, and renews it by itself. Browsers, the Companion and passkeys then work without installing `veyra-ca.crt`. Phones and the server's IP addresses keep the Veyra CA certificate. The DNS provider's credentials are stored encrypted and never shown again. A failed renewal raises the new alert "Public certificate not renewed", and the certificate's expiry is watched like the Veyra one. When the firewall limits the web interface to the allow list, port 80 opens for ten minutes while the authority checks a web request. Console: `sudo veyra certificate status|renew|remove`. See docs/PUBLIC_CERTIFICATES.md.
- **Choose the SIP TLS certificate**: System → Telephony Engine → TLS certificate picks the Veyra CA one (phones trust it) or the public one (softphones that connect by the public name).

### Fixed
- **SIP over TLS could not start**: the TLS transport pointed Asterisk at a key in the root-only `/etc/veyra/tls`, which Asterisk cannot read. Asterisk now reads copies in `/etc/asterisk/veyra-tls` that the installer keeps current. Deploy the telephony configuration after installing if TLS is on.

## 0.27.40 — 2026-10-27

Run the installer's upgrade once (`sudo installer/upgrade.sh --yes`) for the Asterisk hold and the new root unit mode.

### Added
- **Maintenance windows for operating system and Asterisk updates**: on System → Updates, the *Operating system* and *Telephony engine (Asterisk)* policies can now install automatically in a maintenance window: every update except Asterisk (or security updates only) for the system, and Asterisk on its own, only when no call is in progress. A Veyra backup is taken first, administrators get an email after each run, and a needed server restart is reported (never done automatically).

### Changed
- **Ubuntu's nightly updater no longer upgrades Asterisk**: it restarted Asterisk at a random time, dropping calls. Asterisk updates, security ones included, now install in the telephony window or from the Updates page.
- Package runs from the Updates page wait for the package lock instead of failing while Ubuntu's own updater runs, and back up Veyra before upgrading.

## 0.27.39 — 2026-10-27

Run the installer's upgrade once (`sudo installer/upgrade.sh --yes` from the release tree) for the operating-system package buttons: they need a new root unit and its permission, which an update from the web interface does not install.

### Added
- **Install operating system updates from the Updates page**: the "Operating system packages" card now has *Check now*, *Install security*, *Install all except Asterisk* and *Include Asterisk* (which warns before dropping calls in progress). Progress and the output show on the card, a "restart needed" notice appears when the kernel or a core library changed, and the list is read again when a run finishes. Platform administrators with "Approve and apply updates" only, after entering the password again; every run is in the audit log.

- **Extension templates set forwarding, caller ID and voicemail too** (#172, from #173): the busy, no-answer and offline forwards, the outside caller ID number and name, and the voicemail options of the extension's own box (recording attached, delete after email, days kept, operator extension), each lockable like the other template settings. A voicemail box created for an extension that follows a template takes its options.
- **An organization-wide "still ring during Do Not Disturb" list** (#170, from #173): on the organization page, up to 50 numbers or extensions (the district office, emergency responders) that ring every phone of the organization through Do Not Disturb. Needs a deployment after a change. Migration 0069.
- **Ring groups can skip a member who keeps missing calls** (#166, from #173): for groups that ring one member at a time, "Skip a member after unanswered calls" passes over someone who let that many calls in a row ring out, for a set number of minutes (15 by default); answering a call clears it, and if everyone would be skipped nobody is. Needs a deployment.
- **After-hours voicemail greeting** (#169, from #173): pick a time condition in a voicemail box's settings and record an "After hours" greeting; while the condition is closed (holidays and phone overrides included) callers hear it instead of the unavailable greeting. A temporary or extended-absence greeting still takes priority. Needs a deployment.
- **Beep when a supervisor listens in** (#167, from #173): a switch on the organization page makes both sides of a call hear a short beep when a supervisor starts to listen, whisper or join, from a phone code or the Calls page. Off by default; some states require notice. Needs a deployment.

### Security
- Calendar presence (My Phone → calendar): the server now checks that the calendar's address is on the internet at the moment it connects and again for every redirect, so a calendar address can no longer point the server at an internal address through a redirect or a DNS change after the check.
- Module requirement strings are matched with an expression that cannot backtrack exponentially (code scanning alert 28).

### Changed
- Dependency updates: FastAPI 0.161.1, alembic 1.20.1, pydantic-settings 2.16.1, websockets 17.3, setuptools ≥ 84.2.1; Next.js 16.4.3, react-dom 19.3.1, vite 8.3.5, eslint 10.13.0, typescript-eslint 8.72.0; companion vite 8.3.5 and @types/chrome 0.3.6.

## 0.27.38 — 2026-10-26

Migration 0068. The new codes and rules need one telephony deployment (Telephony → Deploy) before phones use them.

### Added
- **Codes staff know from the phone company** (#163): `*67` before a number hides your number on that call (never on 911), `*69` calls back the last outside caller, `*70` before a number turns call waiting off for that call, `*77` / `*87` refuse or accept callers who hide their number. All are on the Feature Codes page, where they can be renamed or turned off.
- **Call waiting and anonymous call rejection per phone** (#163): the call handling card (extension page and My Phone) has a Call waiting switch (off: a second caller hears busy or goes to your busy forward) and "Refuse callers who hide their number".
- **Forward when the phone is offline** (#165): a separate target, for example a cell phone, used at once while no phone of the extension is connected (power, network or internet outage), instead of voicemail.
- **Callers who still ring during Do Not Disturb** (#170): up to 20 numbers or extensions per phone, on the call handling card. A North American number matches however the carrier sends it.
- **Extension templates** (#172): Telephony → Extension Templates sets class of service, intercom, phones that may register, department, ring time, call waiting and anonymous call rejection for a group of extensions, each optionally locked. Pick a template when creating an extension (also the `template` column of a bulk import), choose one on the extension's Call Handling tab, and "Apply…" a changed template to its extensions after a preview.
- **Supervisor listen, whisper and join** (#167): from the live Calls page ("Supervise…", permission "Listen to, whisper on and join calls in progress") your phone rings and, once answered, you hear the call, talk to your colleague only, or join it. Phones whose class of service allows supervising can do the same with `*222`, `*223` or `*224` plus the extension. A class of service can be marked "Never monitored". Every session is in the audit log.
- **More ring group strategies** (#166): one at a time starting after the last member who answered (circular), each call starting one member later (round robin), or the member longest without a call first (longest idle). Members can have their own ring time ("Ring time per member"), also for "one after the other".
- **Hotline phones** (#168): an extension can have a hotline number (and a warm-line delay), so lifting the handset dials it: elevator, lobby, vestibule and emergency phones. Set on the extension's Phones tab; provisioned Poly and Yealink phones pick it up at their next check-in (Poly dials at once; the Yealink delay waits for a digit first). Templates `yealink.base` 0.3.0 and `poly.vvx.base` 0.4.0.
- **Code sets** (#164): Telephony → Feature Codes can load the codes staff know from their old system ("Metaswitch (Sparklight code card)" or the Veyra defaults) into the table as a draft, list what changes and which fixed codes still differ, and save it like any change.
- **Extended absence on voicemail** (#169): a fifth greeting, "Extended absence", with a first and last day and "Take no messages while away" (callers hear the greeting and the call ends). It plays as the temporary greeting between the dates and removes itself after the last day. On the Greetings tab of My Phone and the Voicemail page; administrators can set the same absence on many boxes at once (`PUT /voicemail/absence`).
- **A trunk channel kept for 911** (#171): a trunk with a maximum channel count keeps one channel (configurable, "Channels kept for emergency calls") that only emergency calls may use. The emergency readiness page advises when an emergency trunk has no channel count, so nothing can be kept.

### Changed
- The class-of-service API router was registered twice; it is registered once now.
- Feature codes: a one-character code (direct to voicemail's `*`) can be saved again from the API.
- Trunks send the caller's identity header even when the number is withheld (`trust_id_outbound`), marked private, as carriers expect for `*67` calls.
- A trunk that already has a maximum channel count now keeps one of those channels for emergency calls; set "Channels kept for emergency calls" to 0 for the old behaviour.

### Documentation
- **PBX feature comparison** (`docs/research/pbx-comparison/`): Veyra compared with Metaswitch (Alianza Core) and 20 other phone systems, with a recommended roadmap. The roadmap items to build are filed as issues labelled `gap:metaswitch`.
- The README's status line now says where Veyra is (pre-1.0, Milestone 22 in progress) instead of "Milestone 1".

## 0.27.37 — 2026-10-20

No migration. Module API 1.3.

### Added
- **More module commands on the server** (#149): `sudo veyra modules` can now uninstall, update, upload a `.vmod` package, roll back, and show or change a module's settings, as the Module Manager page does. Each one is audited.
- **Module settings per organization** (#149): a module's Settings dialog has a "Settings for" choice, so a module's per-organization settings can be set for each organization from the web interface.
- **Modules can read phones, extensions, users and sites** (#149, module API 1.3): module authors get read-only lists of them without passwords or PINs, instead of relying on events.
- **Modules say which Python libraries they need** (#149): a module lists them in its manifest (`[runtime] requires`), and Veyra refuses to install it with a clear message when one is missing, instead of failing when it loads.
- **Search and filters on module pages** (#149, module API 1.3): a module's table page can have a search box and up to five filters. The example Notes module can now be searched.

### Fixed
- Veyra creates a module's private data folder when the module loads; modules no longer have to create it.
- A module that says it has a health check but never adds one now shows as "degraded" instead of healthy.

## 0.27.36 — 2026-10-20

Migration `0067`.

### Added
- **Delete old voicemail automatically** (#142): a voicemail box can delete messages older than a number of days (Voicemail → the box → "Delete messages older than"), once a day, from every folder, to save storage on the phone server. Empty keeps them, as before.

## 0.27.35 — 2026-10-20

No migration.

### Changed
- **The live call list updates as calls happen** (#111): Calls refreshes the moment a call starts, is answered or ends on a phone you can see, instead of every few seconds.

## 0.27.34 — 2026-10-20

No migration.

### Added
- **Voicemail PINs from FreePBX** (#42): add FreePBX's `voicemail.conf` next to the database dump and users keep their voicemail PIN and the email address their messages go to. The extensions import file gets a `voicemail_pin` column for this (it sets a PIN and is never exported).

## 0.27.33 — 2026-10-20

No migration.

### Added
- **Time conditions in the bulk import and from FreePBX** (#41, #42): export, edit and import business hours (`mon-fri 07:30-16:00`) and holidays; from FreePBX, time groups become hours and holidays, and a route that went through a time condition keeps its open and after-hours destinations.

## 0.27.32 — 2026-10-20

No migration.

### Added
- **IVR menus in the bulk import and from FreePBX** (#41, #42): export, edit and import auto-attendant menus with their keys (`1=extension:1001; 2=ring_group:6000`), timeout and invalid destinations and greeting recording; the FreePBX import brings its IVR menus too (upload their recordings first).

### Fixed
- The secret scan no longer flags the made-up password in the FreePBX test file.

## 0.27.31 — 2026-10-20

No migration.

### Added
- **Queues in the bulk import and from FreePBX** (#41, #42): export, edit and import queues with their members; the FreePBX import now brings the queues too.
- **Agent time in the queue report** (#135): Reports → Queues shows, for each agent, how long they were logged in to the queue and how long paused in the period, and how many callers left through the queue's break-out menu. Counted from this release on.

## 0.27.30 — 2026-10-20

No migration.

### Added
- **Rotate the installation key from the web** (#125): System → Settings → **Installation key** shows its fingerprint and offers **Rotate the key…**, which does what `sudo veyra installation-key rotate` does on the console: a new key, every stored secret re-encrypted, the previous key kept, the services restarted. Platform administrators only, after confirming it is you.

### Changed
- **Report builder** (#139): group by up to three things (for example who answered, then direction, then outcome); show up to 5000 rows; choose which measure the chart draws; schedule monthly reports on any day — a month without that day sends on its last day.

## 0.27.29 — 2026-10-20

No migration.

### Added
- **Move from FreePBX** (#42): System → Import and Export → **From FreePBX** reads a database dump of your FreePBX server (`mysqldump asterisk > asterisk.sql`) and turns its extensions, ring groups and inbound routes into import files. Check and import each one; what has no equivalent yet (time conditions, catch-all routes…) is listed for you to set up by hand. SIP passwords are not carried over.
- **Ring groups in the bulk import** (#41): export, edit and import ring groups with their members, outside numbers and failover.

## 0.27.28 — 2026-10-20

No migration. Deploy the telephony configuration after installing (for `*37`).

### Added
- **Set your presence from the phone** (#136): dial `*37` followed by 1 (available), 2 (away), 3 (busy), 4 (in a meeting), 5 (at lunch) or 6 (out); `*37` alone puts you back to available. Your automatic actions for that state (Do Not Disturb, a forward) apply, as on My Phone.
- **Presence from your calendar** (#136): on My Phone → Presence → **From your calendar**, paste your calendar's secret iCal address (Google or Outlook). While a meeting is on, colleagues see "In a meeting" — never the meeting's title — and afterwards you are available again. A state you picked by hand is left alone.

## 0.27.27 — 2026-10-20

Migration `0066`.

### Added
- **Automation: "when this happens, do that"** (#117): System → **Automation** has rules that listen to what Veyra already reports — a call ended, a voicemail arrived, an alert was raised — and only fire when your conditions hold (for example *outcome is missed* and *did contains 0100*). A rule then emails a group and/or starts a recorded page. A rule can also get its own secret web address, so a door controller or a panel that can call a URL can start a page ("front door held open"). Each rule has a quiet time so a burst fires once, a **Test now** button, and a list of its recent runs.

## 0.27.26 — 2026-10-20

No migration.

### Added
- **Wideband audio for HD phones** (#138): a recording uploaded to the audio library at 16 kHz or better (most WAV and MP3 files) now also keeps a 16 kHz copy, which phones talking G.722 (HD voice) hear on pages, prompts and hold music instead of the 8 kHz version. Recordings uploaded before this release stay 8 kHz until you upload them again.

## 0.27.25 — 2026-10-20

No migration. Deploy the telephony configuration after installing.

### Added
- **Record a call from the web** (#135): Calls (the live call list) has **Record** and **Stop recording** next to each call, for administrators with the new permission "Start and stop recording a call in progress" (organization and site administrators by default). The recording is filed with the call under Call Recording, like the phone's record code.
- **Classes of service cover the in-call codes** (#135): a class that does not allow "Record this call" gets an error tone when its phone presses the record code, and a class that allows neither transfer code cannot transfer calls with the transfer keys. Deploy the telephony configuration after installing.

## 0.27.24 — 2026-10-20

No migration.

### Added
- **Your provisioning variables for the Companion** (#130): `GET /me/provisioning/variables` returns the non-sensitive variables of your organization and site together with the feature codes, and phone templates can use the codes as `{{ server.feature_codes.<key> }}`.
- The Module Manager page links the module author guide.
- **Voicemail in the Companion** (#136): the browser extension's popup lists your newest voicemail messages; **Play** listens in the browser and **Call me** plays it on your phone. Reinstall or update the Companion from the server to get it.
- **Who left the voicemail, in the webhook** (#139): the `voicemail.message` webhook now includes the caller's number and name, when the message arrived and how long it is.

### Fixed
- Voicemail webhooks no longer mix up two organizations that use the same box number.

## 0.27.23 — 2026-10-20

No migration. Deploy the telephony configuration after installing.

### Changed
- **Safer upgrades** (#88): before an upgrade switches to the new release it now tests the new web server configuration. If it is rejected the upgrade stops with nothing changed, and the current version keeps running — no more half-upgraded server.
- When an upgrade fails after the switch, System → Updates says that the new version is installed and running and that a later step failed, instead of only "failed".
- The passkey screens link the server's certificate authority (needed when the browser does not trust the certificate yet).
- The `extension.updated` event (webhooks, modules) now carries the organization and the extension number.
- **Block the last caller (`*32`) after group calls** (#135): an outside call a phone answered through a ring group or a queue now counts as its last caller too, not only calls that rang the phone directly.

### Added
- **Module author guide** (#94): docs/MODULE_AUTHOR_GUIDE.md explains what a module is, the core concepts, what a module can and cannot extend today, a complete worked example with tests, and a prompt to give an AI coding agent that builds a module.
- **`*85` + slot picks up a parked call** (#135), the FreePBX habit; dialling the slot alone still works. A phone key on `*85<slot>` lights while a call waits there. The code can be changed or turned off on the Feature Codes page.

## 0.27.22 — 2026-10-20

Migration `0065`.

### Added
- **Passkeys** (#107): sign in with your fingerprint, face, device PIN or a security key — Touch ID on a Mac, Windows Hello, a phone — instead of typing an authenticator code. Account → Two-factor authentication → **Add a passkey**; name, rename and remove them like authenticator devices. At sign-in the passkey is offered first, with the authenticator code and recovery codes still available. "Confirm it is you" also accepts a passkey. Administrators choose the allowed second factors in Settings → Two-factor policy (passkeys are allowed by default). Passkeys need Veyra opened by its host name with a trusted certificate: browsers refuse them on an IP address or a page with a certificate warning.

## 0.27.21 — 2026-10-20

No migration.

### Added
- **Live conference control** (#96): a conference room's page shows who is in the room right now, and administrators can mute or unmute someone, remove them, mute everyone else, lock or unlock the room, or end the conference.

## 0.27.20 — 2026-10-20

No migration.

### Added
- **Import and export as CSV** (#41): System → **Import and Export** exports extensions (with their voicemail settings and pickup groups), users (with roles), inbound routes and shared voicemail inboxes as a spreadsheet file, or gives a blank template. Edit the file, **Check the file** to see what would be created, updated or refused — nothing is saved — then **Import**. Rows are matched on their first column and updated in place; an empty cell keeps a value and a dash (-) clears it. Every row goes through the same checks as the web pages; rows with errors are left out and listed. See docs/BULK_IMPORT.md.

## 0.27.19 — 2026-10-20

No migration.

### Added
- **Download and install in one step** (#89): the review dialog on System → Updates has **Download and install now**, which downloads, verifies and starts the installation in one click; "Download and verify only" stays for the careful path.
- **Update available in the top bar** (#89): when a newer Veyra release is found, a "Veyra X is available" pill appears next to the deploy control and links to System → Updates; hide it with its × until the next release. While an installation runs it says so.

### Changed
- **System → Updates has tabs** (#85): **Updates** (what is available, the last check, the history), **Settings** (email notifications and update policies) and **System packages**.
- **Updates always come from the official Veyra feed** (#84): the update source address and access token are gone from the page; only the notification recipients remain.

## 0.27.18 — 2026-10-20

No migration. Deploy the telephony configuration after installing.

### Added
- **Call me to play** (#136): a **Call me** button on each voicemail message on My Phone rings your phone and plays the message when you answer, for when you'd rather listen on the handset than the computer.
- **Install updates from the console**: `sudo veyra updates install` checks for a new release, downloads and verifies it, and installs it — the same steps as **Install now** on System → Updates, which shows the progress and records it in the history. It prints each step until the installation is done. Useful while developing; on the web interface the confirmation with password and second factor stays.

## 0.27.17 — 2026-10-20

No migration. Deploy the telephony configuration after installing.

### Added
- **Email a voicemail and delete it** (#148): every message in the voicemail inbox (My Phone and the administrator's Voicemail page) has an **Email** button. It sends the message with its recording to the box's address (or your account's; administrators can type another), and with "Delete it from the voicemail box once the email is sent" ticked, removes it to save storage. If the email cannot be sent, the message stays and you see why.

### Fixed
- **"Delete after email" no longer deletes before the email is sent**: a box set to delete messages once emailed lost the message as soon as the phone system queued the email, even when the email server then refused it. The message is now deleted only after the email server has accepted the email; if the email fails or is given up on, the message stays in the box. The setting now also needs "Attach the recording to the email", so the email is a real copy; a box with the recording off keeps its messages. Deploy the telephony configuration after installing so the phone system stops deleting messages itself.

## 0.27.16 — 2026-10-20

No migration.

### Added
- **Edit a user's own phone keys** (#136): a phone's Keys tab now shows "User's keys" — the open slots the user fills on My Phone — and an administrator can change or clear them there, without touching the profile. Locked keys stay locked.

### Fixed
- **Setting one of your keys no longer clears the others**: on My Phone, setting or clearing one key sent only that key, and the phone lost the user's other keys. All of them are kept now. If you set several keys before this release, check them on My Phone.

## 0.27.15 — 2026-10-20

Migration `0064`.

### Added
- **Confirm it is you** (#137): actions that change who can sign in or what the system runs — granting a role, resetting someone's password or second factor, changing the two-factor or single sign-on policy, installing an update, creating or rotating an integration's token, high-availability switchover and failover — ask for your password again (and your authenticator code, if you have one) when you signed in more than 15 minutes ago. The action continues by itself after you confirm. Migration `0064`.

## 0.27.14 — 2026-10-20

No migration. Deploy the telephony configuration after installing.

### Fixed
- **Pages from phones are logged and sent to webhooks** (#139): a page a phone dials (a zone or a page number) now appears in the page log and fires the `page.sent` webhook, like pages started from Veyra. Deploy the telephony configuration after installing.
- **Queue statistics count calls, not visits** (#139): a caller who leaves a queue through its break-out menu and comes back is counted once as offered, answered or abandoned.

## 0.27.13 — 2026-10-20

### Changed
- **Licence warning for streamed hold music**: choosing "An internet radio stream" for a hold music set shows that a station's permission and a music performance licence may be needed, and stream sets carry a "Licence may be needed" badge in the list. No migration.

## 0.27.12 — 2026-10-20

No migration. Deploy the telephony configuration after installing for the stream fallback.

### Added
- **Built-in hold music** (#138): Telephony → Audio → Built-in sounds now has three calm pieces made by Veyra — Calm chords, Warm pads and Soft bells — free to play to callers. Add one to the library, then to a hold music set.
- **A stream falls back to recordings** (#138): a hold music set that plays an internet station can also list recordings; they play whenever the station cannot be reached, and the station is tried again afterwards.

## 0.27.11 — 2026-10-20

Migrations `0062` and `0063`. Deploy the telephony configuration after installing.

### Added
- **Hold music from an internet radio stream** (#138): a hold music set can play a station (an http or https MP3, AAC or Ogg stream) instead of recordings (Telephony → Hold Music → Source). The server decodes it with ffmpeg and reconnects when it drops. Use a station you are licensed to play to callers. Migration `0063`; deploy the telephony configuration after installing.
- **Directed pickup within pickup groups** (#138): an organization can let only phones in the same pickup group answer another phone's ringing call with `**` and the extension (Organizations → organization → "Answer another phone's call"). The default stays: any phone of the organization. Migration `0062`; deploy the telephony configuration after installing.

## 0.27.10 — 2026-10-20

Migration `0061`. Deploy the telephony configuration after installing.

### Added
- **Dial by name: your own names and an operator** (#135): Telephony → Dial by Name adds names callers may spell besides the people with a voicemail box — "Front office" on the office ring group, "Nurse" on the health office — and the number 0 reaches. Migration `0061`; deploy the telephony configuration after installing.

## 0.27.9 — 2026-10-20

Migration `0060`. The installer's call-record format changes (version 2); the update installs it and reloads Asterisk without interrupting calls. Deploy the telephony configuration after installing.

### Added
- **Refused calls in the call history** (#135): calls from a blocked caller show as "Blocked caller", and calls a class of service did not allow (a number or feature the phone may not use) as "Not allowed", instead of answered or failed; the report builder can filter on both. Calls before this release keep their old outcome. Migration `0060`; deploy the telephony configuration after installing.

## 0.27.8 — 2026-10-20

Migrations `0058` and `0059`. Deploy the telephony configuration after installing: the trunk registration fix is in the generated configuration.

### Fixed
- **Registration trunks keep trying after a carrier outage.** Asterisk stops registering a trunk after ten failed attempts, and for good after one rejected password challenge, until the configuration is reloaded; a carrier outage of about ten minutes could leave a trunk unregistered. Veyra's trunks now keep retrying, also after a refusal. Deploy the telephony configuration after installing.

### Added
- **Trust this browser** (#137): an administrator can let users skip the authenticator code on a browser they trust for a number of days (System → Security → Two-factor policy → "Trust a browser for"; off by default). Users tick "Trust this browser" at the code step, and see and forget their trusted browsers on the Account page. Changing or resetting a password, resetting the second factor, or signing out of other sessions forgets them all. Migration `0059`.
- **Trunk registration retries** (#142): a registration trunk sets the seconds between attempts after a failure, after "Forbidden", and optionally the number of attempts before it gives up (Telephony → SIP Trunks). Migration `0058`.

## 0.27.7 — 2026-10-20

### Fixed
- **Update window: nothing is cut off any more.** The installer output now shrinks to the space left in the window and scrolls by itself, so the steps, messages and the end of the output stay visible; "Installer output" folds the output away. On a very short screen the window scrolls as a whole instead of clipping.

## 0.27.6 — 2026-10-20

No migration. Deploy the telephony configuration after installing for the per-queue log-in keys.

### Added
- **Queue log-in key for one queue** (#130): a Toggle key with `queue:<slug>` logs the phone in and out of that queue only, and is lit while it is logged in there (beside `agent`, which toggles every queue). Takes effect at the next deployment.
- **Central console: "Instance update failed" alert** (#120): a managed installation that could not install an update raises an alert on the console with the version and the reason.

## 0.27.5 — 2026-10-20

More audit items. No migration. The Companion changes need the new Companion build; AND Clocks 0.2.0 is updated from System → Modules.

### Added
- **Missed-call emails** (#136): Account → Missed calls → "Email me about missed calls" sends one short email per call to your phone that nobody answered, with who called and when.
- **Add to contacts from a call** (#136): My Phone → Recent calls has "Add to contacts" for an outside caller, so their name shows on later calls and voicemail.
- **Edit rows on module pages** (#115): module pages built from tables can now offer an edit form — click a row to change it. AND Clocks 0.2.0 uses it for clocks (name, address, group, model); update the module under System → Modules. Module API 1.2.
- **Emergency pop-up in the Companion** (#127): when someone dials 911 (or the emergency number), the people the site lists as emergency recipients — by their extension or their email address — get a Companion notification on their computer that stays until dismissed: who called, the building and room, and the site. "Send test notification" on the site's emergency page shows it too, marked TEST. Needs the new Companion build.

### Fixed
- **Saving one setting no longer resets others**: saving presence rules on My Phone, or settings in the Companion, replaced the whole preferences document and could reset the user's own My Phone layout or the other client's settings; only the changed settings are saved now.

## 0.27.4 — 2026-10-20

More audit items. Migration `0057`. Phones pick up the intercom setting at their next configuration check.

### Added
- **Call recordings are encrypted on disk** (#122): every new call and conference recording is stored encrypted with its own key, which is protected by the installation key; recordings made before are encrypted in the background. Listening and downloading work as before. Migration `0057`. Backups keep the recordings encrypted; restoring needs the installation key, as for every other secret.
- **Yealink phones trust Veyra on their own** (#116): like the Poly phones, a Yealink phone pointed at Veyra over plain HTTP (DHCP option 66 on the staging network) now receives only the Veyra certificate authority and the HTTPS address, installs the certificate and continues over HTTPS — no manual certificate upload. The organization's enrollment credential is included when the organization allows it (Organizations → Provisioning credential).
- **Intercom answers on the handset** (#129): the Poly (VVX, Edge E, CCX) and Yealink templates set the phone to answer Veyra's intercom calls on the speaker by itself, with the microphone open; the template variables "intercom_auto_answer" and "intercom_mic_muted" change that per profile or site. Phones pick it up at their next configuration check.

## 0.27.3 — 2026-10-20

More audit items. Migration `0056`. Deploy the telephony configuration after installing: the greeting keys, presence keys and the direct-to-voicemail fix are in the generated dialplan.

### Added
- **Presence keys** (#132): a phone key of the new type "Presence of a colleague" shows whether that colleague is available (off), busy or in a meeting (lit), away or at lunch, or out, as set on My Phone; pressing it calls them. Administrators put them on profiles and phones; users can put them on their own keys. The feature code is `*36` (Telephony → Feature Codes); takes effect at the next deployment.
- **Voicemail greeting keys** (#131): callers who reach a voicemail box can press 1 or 2 while the greeting plays to try the person's follow-me numbers or ring another number of the organization (an extension, ring group or queue), alongside 0 for the operator. Administrators set them in the voicemail box; each user can set their own under Account → Voicemail → Greeting keys. Migration `0056`; takes effect at the next deployment.
- **Built-in sounds** (#114): Telephony → Audio lists bells, chimes and attention tones that come with Veyra — a school bell (short and long), the Westminster chime, two- and three-tone chimes, a soft chime, hi-lo and whoop alerts, a temporal-3 drill tone, "door held open" beeps and a beep. Play any of them, then **Add to library** to use it in a bell schedule, before a page or in a menu. Veyra generates them itself, so they are free to use.

### Fixed
- **Direct to voicemail plays the greeting**: dialling or transferring to `*<extension>` now plays the box's unavailable greeting; before, callers heard only the tone.

## 0.27.2 — 2026-10-20

More audit items. Migration `0055`. The Companion changes need the new Companion build (Settings → Companion).

### Added
- **Conference recordings on the Call Recording page** (#133): recordings of conference rooms with recording on are stored like call recordings (kept 90 days, can be held) and listed with the room's name. Migration `0055`.
- **Reports** (#121): the dashboard's "Calls today" compares with the same weekday last week up to the same time of day; the Reports trunk table shows the most calls up at once on each trunk in the period, to compare with the carrier's channel limit.

### Changed
- **Companion favourites come from My Phone** (#128): the Companion popup shows your favourite contacts from My Phone (star a contact to add it) instead of a separate speed-dial list. The Companion's options page moves its old speed dials to My Phone favourites in one click; until then the popup keeps showing them.

### Fixed
- **Update window: the "Full log on the server" line** no longer overlaps the scrolling installer output; it sits above it.

## 0.27.1 — 2026-10-20

First items from the milestone audit (issues #108–#147). No migration. Note the fix below: after installing, open each extension's Location card and choose its site (or building) so emergency routing and readiness count it.

### Fixed
- **Extensions can be placed at a site.** The site of an extension decides its emergency route, emergency caller ID and the site's emergency readiness, but it could not be set from the interface or the API, so no extension counted toward any site. Extensions now take a site (or a building, which implies its site).

### Added
- **Forgot your password?** (#108): when email delivery is set up, the sign-in page offers "Forgot your password?"; the user enters their address and receives a one-time link to choose a new password. The page answers the same whether or not the address has an account, sends at most one link per account every five minutes, and skips accounts that sign in through Google or Microsoft. Administrators can still issue links as before.
- **Hang up a call** (#109): Active Calls has a Hang up button (with a confirmation) for administrators and technicians (new permission "Hang up calls in progress"); each hang-up is in the audit log.
- **Buildings and departments** (#126): Sites → Buildings lists each site's buildings, with their own street address when it differs from the site's (emergency notifications give that address). Organizations → Departments groups extensions. An extension's new Location card (and the New extension dialog) places it at a site, in a building and room, and in a department; My Phone layout templates can now be assigned to a building or a department by picking it from a list.
- **Emergency readiness in the installer check** (#124): `verify.sh` warns when a site with extensions is not ready for emergency calls and names what is missing (`veyra emergency readiness`).
- **Closed days and moving holidays** (#113): time conditions take holidays as dates every year, date ranges every year (winter break, even across New Year), one-off dates and ranges (a snow day, this year's spring break), and rules such as the fourth Thursday of November or the last Monday of May. The holiday list is now an editor with one row per holiday and says each one in words; the report builder's business-hours filter follows the same holidays.

## 0.27.0 — 2026-10-20 (Milestone 21: provisioning breadth)

Design: [docs/PROVISIONING_BREADTH.md](docs/PROVISIONING_BREADTH.md); report [docs/milestones/MILESTONE_21_REPORT.md](docs/milestones/MILESTONE_21_REPORT.md). Migration `0054`. The new templates are marked experimental until checked on hardware (docs/PROVISIONING_HARDWARE_CHECKS.md).

### Added
- **Provisioning variables** (#76): Provisioning → Variables defines values phones share once — an all-call zone per building, the time server, an admin password — for the installation, an organization, a site or a device profile; each phone takes the nearest one. Line keys use them as `$name` (a page key `$all_call` on one profile pages each building's own zone), templates as `{{ vars.name }}`, and a variable named like a template setting fills that setting for every profile that leaves it empty. Saving a value asks the phones it reaches to re-read their configuration. The device page shows the values a phone resolves and where each comes from, and the configuration preview warns about variables nobody defined.
- **Yealink phones** (#35): official templates for every current Yealink SIP phone — T3x (T30, T30P, T31, T31G, T31P, T31W, T33G, T34W), T4x (T42U, T43U, T44U, T44W, T46U, T48U), T5x (T53, T53W, T54W, T57W, T58W, T58W Pro, VP59), T7x (T73U, T73W, T74U, T74W, T77U), T8x (T85W, T87W, T88) and the CP925, CP935W and CP965 conference phones (their line, voicemail, directory and time; no line keys) — from the same profiles, keys and variables as the Poly phones: every line, BLF, speed dial, transfer and multicast paging keys, voicemail indication, the profile's paging zones as multicast listen addresses, time zone and daylight saving, VLAN, firmware, the daily provisioning check with the device credential. Experimental until checked on hardware.
- **Algo paging endpoints** (#38): one official template for every current Algo SIP device — speakers and horns (8180, 8186, 8188, 8189, 8190, 8196–8199, 8507), display speakers (8410, 8420), paging adapters (8301, 8305, 8312, 8373), intercoms and door controllers (8028, 8028V, 8039, 8063, 8201, 8203), visual alerters (8128, 8138), clocks (8401, 8402) and the 8450 console. The page extension (and a ring extension), the profile's paging zones as multicast listen zones in regular multicast, Poly group paging or both — so speakers and Poly phones play the same page in sync — the emergency zone as the priority zone, time server and zone, VLAN, firmware, and the daily configuration check with the device credential. Veyra serves the checksum file Algo requires beside the configuration. Experimental until checked on hardware.
- **Poly Edge E and CCX** (#39): official templates for the Edge E100–E550 and the CCX 350–700 (Open SIP), on the same settings as the VVX phones; the CCX has no group paging.
- **Redirect services**: the Provisioning page explains how new phones find Veyra (Yealink RPS, Poly ZTP, DHCP option 66 for Algo, Grandstream GDMS) and exports each vendor's MAC addresses with the provisioning URL as CSV for bulk registration.
- **Hardware checklist** (docs/PROVISIONING_HARDWARE_CHECKS.md): the steps that move a template family from experimental to stable.
- **Phone directory** (§5 of the design): phones download the organization's extensions and ring groups as a phone book (Yealink, Poly, Grandstream and CSV formats) with their provisioning credential; Yealink phones are set up to use it (variable "directory_enabled") and Poly phones receive it as their directory automatically.
- **More line key types** (#40): Voicemail, Intercom to an extension, Do Not Disturb (lit while on), Park (a lot, or watch a slot and pick the parked call up — every parking lot now publishes its slots' lamps), and Toggle for a call flow, a time condition override or queue log-in (lit while switched or logged in). They work with the existing Poly templates; a Transfer key is accepted but the Poly phones keep their transfer softkey, and the configuration preview says so.

## 0.26.7 — 2026-10-19

### Changed
- **Updates page: available updates first.** The list of updates (and the install progress) now sits directly under the page title; the last check, the source, the policies, the operating system packages and the history follow below, so starting an installation needs no scrolling (first step of #85).

## 0.26.6 — 2026-10-19

### Fixed
- **Updates: one scroll bar while installing** (#91). The review window no longer scrolls as a whole during an installation: the stages and summary stay in view and only the installer output scrolls.

## 0.26.5 — 2026-10-19

Migration `0053`.

### Added
- **Phones online graph** on the overview: registered phones against phones the engine knows but cannot reach, over the same time ranges as the channel and call graphs, with the current count in the title (samples from 0.26.5 on carry the total; older samples show registered only).

### Security
- Hardening from the first CodeQL review of the public repository: the alert check that reads a peer certificate's expiry no longer accepts TLS 1.0/1.1; the backup unit's job name is validated before it reaches systemctl; prompt recording paths are resolved and checked to stay inside the organization's folder; the CSP hash script matches `<SCRIPT>` tags in any case. The remaining CodeQL alerts were reviewed and dismissed with reasons (React text rendering, server-generated cookies, administrator-only error messages, development tools).

## 0.26.4 — 2026-10-19

### Changed
- **My Phone widgets fit their size** (#92): a widget smaller than its content is no longer cropped. Its title stays put and the content scrolls inside the widget; lists (recent calls, contacts, colleagues, voicemail, faxes) show as many rows as fit with "Show all"; the fax form folds behind a "Send a fax" button in a short widget; contacts show one number in a narrow widget.

## 0.26.3 — 2026-10-19

Migration `0052`; new permissions `fax.read` and `fax.manage`; the installer adds the packages `ghostscript` and `libtiff-tools` and the shared directory `<data>/fax`; `verify.sh` gains `fax-tools`, `fax-engine` and `fax-dir`.

### Added
- **Fax** (#77, Milestone 20 slice H): a **Fax** widget on My Phone sends a PDF (up to 20 MB and 50 pages) to a fax number with an optional cover sheet, over the organization's outbound routes with the user's caller ID; the widget follows each fax (waiting, dialling, sending, sent, failed with the reason, attempts), lets the user cancel a waiting fax, retry a failed one and download the PDF, and the user is emailed when a fax is delivered or given up on (busy and no answer are retried, three attempts in all). **Fax inboxes** ("Fax to email", Telephony → Fax) are a new destination for DIDs, inbound routes, menus, groups and queues: received pages arrive as a PDF at the inbox's recipients and are listed with the organization's faxes. Administrators see every fax of their organizations, retry, cancel and download; who may fax is a class-of-service flag ("May send faxes"), T.38 is offered per trunk ("Fax over T.38"), and the organization page carries the fax header and station ID. Faxes are kept 90 days (System → Retention, class "Faxes"). Everything is audited.

## 0.26.2 — 2026-10-19

### Changed
- **Updates: the installation runs in the same window.** "Install now" no longer closes the review window: it turns into the live progress (stages, installer output, elapsed time) and ends with a **Reload the page** button; closing it leaves the progress callout on the page, and opening the release again while it installs shows the progress too.

## 0.26.1 — 2026-10-19

### Fixed
- **Agent log-in marks reached the engine only from the phone.** Logging an agent in or out, or pausing them, from the queue page or the API wrote the queue member and the lamps but not the `veyra/agent` marks the phone's `*45`/`*46` toggles read: the engine adapter refused store keys with a path and the 0.25.5 change was only logged as a warning. The adapter accepts path keys now, and the test double applies the engine's checks so a refused key fails the suite.

### Changed
- **Updates**: releases older than the one installed are no longer offered. After a check or a successful installation they become *superseded* and leave the list (their download is removed); Veyra's releases are listed newest first.

## 0.26.0 — 2026-10-19 (Milestone 20)

Design: [docs/USER_PORTAL.md](docs/USER_PORTAL.md); report [docs/milestones/MILESTONE_20_REPORT.md](docs/milestones/MILESTONE_20_REPORT.md). Migrations `0047`–`0051`; new unit `veyra-vmstore`; new permission `portal.templates`. Fax (#77) follows as 0.26.x.

### Added
- **Voicemail web inbox** (#31): My Phone shows the messages of your voicemail boxes and of the shared inboxes you are a member of, by folder (New, Old, Work, Family, Friends, Urgent) with caller, time and length; play them in the browser, download, move to a folder (moving to Old marks a message as heard on the phone too), forward to a colleague's box or delete. Administrators have the same on the Voicemail page ("Messages" on a box). Every listening and change is audited. Messages are reached through a new small service, `veyra-vmstore`, that runs as the asterisk user and reads and writes the voicemail spool on the API's behalf over a local socket — the API itself gains no file access; the installer installs it and `verify.sh` checks it (`vmstore`). The generated `voicemail.conf` polls mailboxes (`pollmailboxes=yes`) so the phones' message lamps follow changes made from the web.
- **Voicemail greetings from the web** (#32): the Greetings tab of each voicemail box on My Phone shows the unavailable, busy, name and temporary greetings with their state; play them, upload an audio file (converted for the phone system like prompts), **record one in the browser** with the microphone (preview, then save; up to 60 seconds), or remove one so the standard greeting plays. Administrators do the same on the Voicemail page. Audited.
- **Personal contacts and speed dials** (#60): a Contacts card on My Phone holds each user's own contacts (name, company, up to five numbers, email, notes), favourites first, with a speed-dial slot (1–99) that later goes on a phone key; search, click-to-dial from one of your phones, CSV import (paste or file; "name, company, number" lines or a file exported from here) and export. Audited. Migration `0047`.
- **Recent calls on My Phone** (#60, #33): the user's calls of the last 30 days with the other party named from their contacts, a missed/answered/voicemail filter, call back from their phone, CSV export, and — when the organization allows it with the new setting "Users may play recordings of their own calls" (off by default) — the recording of calls their extension took part in, audited like an administrator's listening. Self-service forwards now respect the extension's class of service: a class without outside forwards refuses an outside number from My Phone as it does from the phone. Caller names on the voicemail inbox also come from the user's contacts. Migration `0048`.
- **Presence** (#60): on My Phone a user sets Available, Away, Busy, In a meeting, At lunch or Out of the office with a short message; each state can switch Do Not Disturb or a forward automatically (the user's own rules, saved with their preferences). A Colleagues card and the directory show everyone's presence, whether their phone is registered and whether they are on a call, with click-to-dial. Migration `0049`.
- **Users set their own phone keys; administrators lock the rest** (#75): a device profile's key list (or a device's own) can leave slots to the user with the new key type "User's choice". On My Phone, a Phone keys card shows each of the user's phones with the administrator's keys locked (the district's all-call key stays where it is) and the open slots editable as a speed dial (a number or one of their contacts) or a busy lamp on a colleague's extension, ring group or queue; saving reprovisions the phone (it checks its configuration within a minute). Existing profiles have no open slots, so nothing changes until an administrator adds some. Administrators see the user's keys on the device page. Audited. Migration `0050`.
- **My Phone is a canvas** (#78): the page is made of widgets — your phone, presence, voicemail, recent calls, contacts, colleagues, phone keys, codes — on tabs you name; "Arrange" lets you drag, resize, add and remove them (arrow buttons do the same from the keyboard), with undo, save and reset; on a phone the widgets stack in reading order. Administrators build **default layouts** under System → Portal layouts and assign them system-wide, per organization, building, department or role (the nearest wins), with widgets a user cannot remove (an announcement from the district, for example); "Push to users" resets the users' own arrangements under a template. New permission `portal.templates` (organization administrators). Migration `0051`.

## 0.25.5 — 2026-10-19

### Fixed
- **In-call codes never reached the phone system.** After a deployment the engine was asked to reload `features.conf` with the console command `features reload`, which current Asterisk no longer has; the console answered "No such command", the deployment counted it as done, and `*1` (record), `*2` (attended transfer) and `##` (blind transfer) stayed at the engine defaults (found on the 0.25.0 live check). The reload is now `module reload features`, and a console command the engine rejects is treated as a failure of the deployment step instead of a silent success. Deploy the configuration once after installing this release to activate the codes.
- **Queue agent state set from the page or the API now agrees with the phone.** Logging an agent in from the queue page did not write the marks the phone's `*45`, `*45<queue>` and `*46` toggles read, so the first press on the phone afterwards repeated the login instead of logging out. The page, the API and the phone now share the same marks.

## 0.25.4 — 2026-10-18

### Changed
- **Install now starts at once.** Approving an installation for "now" used to leave it for the background worker's next housekeeping pass, up to a minute later (measured 50–56 s on the first interface-driven installs). The API now runs the pre-checks and starts the upgrade service in the same request, so the installer begins within a second or two and the progress card moves from the first moment. Nothing was removed: the same checks run, the same root unit does the work, and the worker still starts installations approved for a maintenance window (and remains the fallback). Issue #89, first item.

## 0.25.3 — 2026-10-18

### Changed
- **The installation card shows every stage from the approval on**, not only the installer's output: approved (by whom, when), picked up by the background worker (which checks for approved installations every 60 seconds; the card says how long until its next pass and what it checks), release verified and unpacked by the upgrade service, installer running (current step), finished — with the time since the approval. Nothing in the process changed; the stages that used to pass silently are now visible, so an installation no longer looks stalled while the worker and the upgrade service do their part. `GET /updates/status` carries the stage in a new `pending` object.

## 0.25.2 — 2026-10-18

### Fixed
- **Installation progress is live from the moment you click Install now.** The Updates page only started following an installation once the list showed it as "installing", and the list was not refreshed after the approval, so the progress card appeared only after a reload of the page (found on the 0.25.0 install). The page now watches as soon as an installation is approved ("Waiting for the installer to start" until the background worker picks it up, within a minute), refreshes the list until the installation is over, keeps the installer output open and scrolled to the newest line while it runs, shows the elapsed time, and still reads the API's restart during the upgrade as "Veyra is restarting". Note that the page doing the installing is the one from the version being replaced, so the first installation that shows this from the start is the one after 0.25.2.

## 0.25.1 — 2026-10-18

### Fixed
- **Upgrading to 0.25.0 stopped at "Configuring NGINX"** with `too long parameter ... nginx-security-headers.conf:12`: the Content-Security-Policy header lists a hash for every inline script of the web interface, and with 0.25.0's 81 hashes that one line passed NGINX's 4096-byte limit for a configuration parameter. The installer now hands the hashes to NGINX in chunks (`set $veyra_csp_scripts` directives the header expands), so the list can grow with the interface. A server that hit the failure is running 0.25.0 already (release switched, migrations applied, services restarted) but NGINX still serves the previous header, so pages whose scripts changed are blocked by the browser until this release is installed; `verify.sh` reports `csp-hashes` against the new form.

## 0.25.0 — 2026-10-18 (Milestone 19)

### Added
- **Announcements** (#21): Telephony → Announcements plays a recording and then sends the call on; callers may skip it with any key or replay it with a chosen key. Routes, menu keys, groups and queues can point at an announcement, and announcements can chain. Migration `0042`.
- **Dial-by-name directory** (#22): a destination that lets callers spell a first or last name on the keypad and reach the extension (extensions with a voicemail box are listed).
- **Conference rooms** (#20): Telephony → Conference Rooms creates meet-me rooms with a dialable number, optional participant and administrator PINs, a participant limit, join/leave announcements, hold music while alone, "wait for the administrator" and recording to the server's recordings folder. In the room, `*1` mutes; administrators lock the room (`*2`), drop the last participant (`*3`) or mute everyone (`*8`). A line key with the room's number lights while the room is in use. New managed Asterisk file `confbridge.conf`.
- **Call flows** (#25): Telephony → Call Flows defines day/night switches with a normal and an override destination. Switch from the list or the page, from a phone with `*28<index>` (a BLF key with that code lights while switched; optional PIN) or from the API; the change takes effect at once, no deployment. Migration `0043`.
- **Time-condition override** (#26): a time condition can be forced open or closed from its page (temporary, until the schedule next changes state, or permanent) or from a phone with `*27<index>` (inverts the schedule's current state; dialled again, clears it; optional PIN; BLF lit while forced). Routes consult the override before the schedule; the list shows what callers get.
- **Call parking** (#19): Telephony → Parking defines lots with a park extension (transfer a call to it; the slot number is read back), a range of slots to pick calls up from (a line key with the slot number lights while a call waits), a timeout that rings the parker back and then a destination, and a courtesy tone. New managed Asterisk file `res_parking.conf`. Migration `0044`.
- **Blocked callers** (#27): Telephony → Blocked Callers refuses listed numbers on every inbound route (they hear "not in service", or go to a destination of your choice), optionally withholds anonymous callers, counts blocked calls per number, imports and exports CSV lists, and lets any phone block a number with `*30`, unblock with `*31` or block the last outside caller with `*32`. Number changes take effect at once. Migration `0045`.
- **Queue dynamic agents** (#28): an agent marked "Logs in" is in the queue only while logged in: from the phone with `*45` (all queues) or `*45<queue number>`, from the queue page, or through the API; `*46` pauses and resumes; `*47<queue number>` says how many callers wait. BLF keys `*45*<extension>` and `*46*<extension>` show the state. Static agents work as before. Migration `0046`.
- **Queue break-out menu** (#29): a queue can name an IVR menu whose keys callers press while waiting to leave the queue, for example 1 for voicemail.
- **In-call codes**: during a call, `*1` starts and stops a recording of that call (filed on the Call Recording page), `*2` makes an attended transfer and `##` a blind transfer, for phones and softphones without transfer keys. New managed Asterisk file `features.conf`.
- New feature codes `*28` (call flow toggle), `*27` (time condition override), `*30`/`*31`/`*32` (blocked callers), `*45`/`*46`/`*47` (queue agents), `*1`/`*2`/`##` (in-call), adjustable under Telephony → Feature Codes and allowable per class of service.
- Destination pickers everywhere (inbound routes, IVR menus, ring groups, queues, announcements, call flows) offer the new kinds: announcement, conference room, call flow and directory.

### Fixed
- An inbound route pointed at a shared voicemail inbox could not be saved from the interface (the inbox was dropped from the request); it is sent now.

## 0.24.2 — 2026-10-18

### Added
- **Official update feed**: Veyra releases are published as a signed feed (`stable.json` on the repository's `updates` branch, tarballs as GitHub release assets, Ed25519 key `veyra-official`). The installer trusts the public key and points new and upgraded servers at the feed, so System → Updates finds, verifies, downloads and installs releases without manual setup; `verify.sh` reports the key and the feed address (`release-key`, `update-source`). The 0.24.1 release is the first entry.
- **Extension page tabs** (#81): the extension page has a tab bar across the top (General, Caller ID, Call handling, Follow me, Voicemail, Phones, Groups, Credentials) instead of one long scroll; the active tab is in the link (`?tab=`), a switch that would lose unsaved call-handling or follow-me edits asks first, and the settings form keeps its values across tabs. The same pattern (`useUrlTab`) is ready for other object pages.
- **Phones that may register** (#82): an extension's Phones tab sets how many phones may register it at once (1–16); the engine's limit is the larger of this and the number of provisioned phones, so a softphone can register beside the desk phone without a device record. The API carries `max_registrations`, `provisioned_phones` and `registration_limit`; the Registrations page shows registered phones against the limit; migration `0041`.

### Changed
- The Telephony section of the sidebar shows two linked handsets (a handset in each corner with a line running between them), chosen by the owner over the keypad, which read too faint beside the other icons.

### Security
- The Dependabot finding on `braces` (GHSA-vfj7-8cjw-p6xm, development-only, no fixed release) is gone from the dependency tree: the Next.js lint preset `eslint-config-next`, whose plugin pinned the `fast-glob` that pulled it in, is replaced by the React, hooks, accessibility and TypeScript plugins it composed, with the same rules. `npm audit` on the frontend reports nothing at any level.
- Test fixtures and planning notes no longer carry the pilot site's town, postal code or domain; they use example values.

### Fixed
- The extension page no longer discards edits in progress when its periodic registration refresh runs; the form resets only when another extension loads or the extension was saved.

## 0.24.1 — 2026-10-18

### Fixed
- Migration `0038` named the unique constraint of `classes_of_service` outside the models' naming convention, so `alembic check` (CI on `main` for 0.24.0) reported a drift; migration `0040` renames it, and the test suite now runs the same check so a drift is caught before a push.

### Changed
- The Telephony section of the sidebar uses the keypad icon, so My Phone alone carries the handset (owner request 2026-10-18).

## 0.24.0 — 2026-10-18 (Milestone 18)

Design in [CALL_FEATURES.md](docs/CALL_FEATURES.md); report in [MILESTONE_18_REPORT.md](docs/milestones/MILESTONE_18_REPORT.md).

### Added
- **Registrations** (#73): Telephony → Registrations shows every registered phone with the address the registration came from and the address the phone reports (NAT when they differ), user agent, transport, reachability and expiry; `GET /telephony/registrations`; the Extensions list has a "Registers from" column; `registration.changed` webhooks carry both addresses.
- **Trunk registration state** (#45): trunk status and the `trunk_down` alert reflect the engine's outbound registration (registered, rejected, registering, unregistered) besides reachability; Telephony → Registrations lists the trunks with it.
- **Packet captures** (#74): System → Diagnostics starts a tcpdump capture of all SIP, one extension (by the address its phone registers from), a trunk or an address, optionally with RTP, for a chosen time and size; lists, stops, downloads (audited) and deletes captures; a SIP summary groups the messages by dialog. Root unit `veyra-capture@`, polkit, retention class "captures" (7 days), `sudo veyra capture …`; permissions `diagnostics.read` and `diagnostics.capture`.
- **Diagnostics page** (§2.3): System → Diagnostics also tails the engine's logs (messages, security, queue) with a filter and runs a fixed list of read-only engine queries; every read and query is audited.
- **Outbound caller ID per extension** (#17): number and name presented to the carrier, validated against the organization's DIDs or a per-organization allow list unless the caller holds `routing.write`; an outbound route can force its own number; precedence emergency → forced route → extension → route → trunk default; migration `0033`.
- **Feature codes** (§3.1): Telephony → Feature Codes with FreePBX-style defaults (`*78/*79/*76`, `*72/*73`, `*90/*91`, `*52/*53`, `*21`, `*80`, `*`), each changeable or disabled; `GET/PUT /telephony/feature-codes`.
- **Do Not Disturb** (#14): switch on the extension page and `*78/*79/*76` from the phone, effective at once (the engine keeps its own copy; the worker keeps it in step); a lamp hint `*76<ext>`; callers hear busy or the busy greeting; `GET/PUT /extensions/{id}/state`; migration `0034` (`extension_states`).
- **Call forwarding** (#15): always, on busy and when unanswered, plus the extension's ring time, on the extension page and from the phone, effective at once; forwards to outside numbers leave through the organization's outbound routes with the extension's outbound caller ID; a lamp hint `*72<ext>`.
- **Outside members of ring groups** (#16): a ring group can ring up to ten outside numbers with its members, optionally requiring them to press 1; migration `0039`.
- **Find me / follow me** (#16): legs rung together or in turn, desk phone first if wanted, press-1 confirmation for outside legs, caller ID mode, no-answer destination; `*21` toggles; `GET/PUT /extensions/{id}/follow-me`; migration `0035`.
- **Intercom** (#18): `*80<ext>` rings a phone with the auto-answer headers so it answers on speaker; allow or deny per extension with an organization default; migration `0036`.
- **Classes of service** (#30): Telephony → Classes of Service restricts an organization's phones to chosen outbound routes and feature codes, forbids outside forwards or follow-me legs and intercom, and caps simultaneous outside calls; extensions pick a class on their page; emergency routes always work; migration `0038`.
- **Direct transfer to voicemail and voicemail operator** (#23, #24): `*<ext>` reaches a box's greeting, dialled or as a transfer target; a box's operator extension is reached with 0 during the greeting and `*` opens the box; migration `0037`.

- **My Phone** (§3.9): every signed-in user has a My Phone tab with their own extensions: phone registration, Do Not Disturb, forwards, find me / follow me, voicemail and the codes they can dial; `GET/PUT /me/extensions/{id}/state|follow-me`, `GET /me/feature-codes`. The first slice of the user portal (Milestone 20).

### Changed
- The top bar's deploy control is one pill-shaped split button.
- The multi-tenancy isolation test asserts the statuses it depended on.

## 0.23.1 — 2026-10-16

### Fixed
- **CDR reader skipped a rotated file**: a rotated call-record file was recognised only by a changed inode or a smaller size; a new file that reused the inode and was exactly as long as the stored offset (possible after `logrotate`) was never read. The cursor now also keeps the first 128 bytes of the file and treats a different head as a new file.
- Migration `0030` created `ix_backups_started_at` without the `Backup` model declaring it, so `alembic check` failed in CI.
- Installer scripts: ShellCheck findings in the HA agent and NGINX steps (an unused variable, a flag that shared its name with an array) and the test library's source path.
- CI: the secret scan lacked `pull-requests: read` and failed on every pull request; `actions/setup-node` 7.1.0; Dependabot now also watches `companion/`.

### Changed
- Dependencies, each set installed and tested together (Dependabot #1–#5, #7–#11, #50, #51, #53, #56, #62, #65–#67, #69, #70): fastapi 0.143.0, starlette 1.8.0, sqlalchemy 2.1.4, pydantic 2.14.1, cryptography 50.0.2, websockets 17.2 (the ARI event client's `connect(url, ping_interval=, ping_timeout=)` is unchanged on the asyncio implementation), setuptools ≥ 84; ruff 0.17.0, mypy 2.4.0; next 16.4.0, eslint 10.12.0, eslint-config-next 16.4.0, vite 8.3.4, vitest 5.0.4, @types/node 26.6.5, @types/chrome 0.3.5. TypeScript stays at 6.0.3 until typescript-eslint supports 7 (#47). The frontend build now emits 67 inline-script hashes for the CSP instead of 66.

## 0.23.0 — 2026-10-16 (Milestone 17)

### Added
- **Security review** ([SECURITY_REVIEW_2026.md](docs/SECURITY_REVIEW_2026.md)): the CSP allows scripts by hash instead of `'unsafe-inline'` (the build writes `csp-hashes.txt`, the installer renders it), `Permissions-Policy` and `Cross-Origin-Opener-Policy` headers, the `__Host-` session cookie, sign-in rate limits per account as well as per address, Ubuntu Pro `esm-apps` checks in preflight and verify, a capability bound on the HA agent, a weekly dependency audit in CI, and a test that generated secrets never reach logs or audit details. The security headers are one installer-managed file, `/etc/veyra/nginx-security-headers.conf`, sent once on every response.
- **Emergency calling validation** (§6, [EMERGENCY_CALLING.md](docs/EMERGENCY_CALLING.md)): extensions and devices carry a location (floor/room) and a building; emergency routes can be bound to a site and chain to the installation-wide route for other sites; every emergency call raises `UserEvent(VeyraEmergency)`, which the API turns into an `emergency_calls` record and the site's **on-site notification** (email, a recorded page, responder desk phones that hear the extension, an `emergency.call` webhook); the PSAP's **callback** to the site's ELIN rings the extension that placed the call within the window (default 30 min), else the responder; System → Emergency calling shows **readiness per site** (route, ELIN, civic address, attestation that it is registered with the carrier, locations, recipients, notification test, a carrier test call within a year) and records test calls; `GET /emergency/*`; migration `0031`. Veyra reports readiness against its own checks only; the operator validates with the carrier.
- **Retention** (§4): Settings → Retention sets how long each data class is kept (audit log, call history, alert history, update history, cluster events, firewall events and expired bans, provisioning requests, page log, metrics, central samples) with defaults and minimums (the audit log never below a year; under 30 days needs a typed confirmation); one daily job applies it with one audit entry per class that lost rows; an inventory shows rows, bytes and the oldest record per class plus recordings, voicemail, backups and sessions; `POST /retention/run` applies it now.
- **Installation key rotation** (§3.1): `sudo veyra installation-key rotate` re-encrypts every stored secret (SIP, trunk, voicemail PINs, MFA, provisioning, calendars, firewall feeds, SSO, webhooks, module configuration, revision artifacts, the central and SMTP and update-source and fencing secrets) to a new key in one transaction and keeps the previous key; `installation-key check --ciphertexts` proves every ciphertext decrypts; `verify.sh` runs it.
- **Backups** ([PRODUCTION_HARDENING.md](docs/PRODUCTION_HARDENING.md) §2): System → Backups takes, schedules (daily at a chosen time, run by the worker through a root unit), verifies (every dump is restored into a scratch database and compared), encrypts (age, to the administrator's recipients; Veyra keeps no private key), copies (a mounted directory) and prunes (daily/weekly/pre-upgrade keep policy) backups of the database, `/etc/veyra`, the engine configuration, prompts, hold music, firmware, templates, modules, voicemail and optionally recordings; `sudo veyra backup run|list|restore`; alert rules `backup_failed` and `backup_stale`; dashboard tile; migration `0030`.

## 0.22.0 — 2026-10-16 (Milestone 16)

### Added
- **High availability** ([HIGH_AVAILABILITY.md](docs/HIGH_AVAILABILITY.md)): two nodes, active/passive. System → High availability turns a standalone installation into the primary in place (service name and address, PostgreSQL streaming replication with a slot, `wal_log_hints` and TLS from the Veyra CA, HTTPS certificate reissued for the service name and both nodes) and gives a one-time join token; `install.sh --role secondary --join <url> --token <t>` makes the second server a standby from an encrypted bundle and a base backup (migration `0029`).
- A root **HA agent** (`veyra-ha-agent`, `/run/veyra/ha.sock`, fixed verbs) on every node holds the service address with gratuitous ARP, polls the peer every 10 s over the signed node channel (Milestone 15's message format, node keys), pulls the **file sync** every 30 s on the standby (prompts, hold music, firmware, templates, modules, releases, recordings optionally, voicemail, secrets and TLS; SHA-256 manifests, atomic writes) and runs the role sequences with every step recorded.
- **Switchover** (from either node, preconditions checked and shown, runs on the target: freeze, engine stop, catch-up, release address, promote, epoch, migrations, deploy, address, rejoin by `pg_rewind` or base backup) and **failover** from the standby's own interface (Proxmox fencing or the operator's recorded confirmation). Epoch rules decide at boot and when the peer reappears: a stale primary demotes and rejoins; a primary that cannot reach its peer stays *isolated* without primary duties until *Resume as primary*. Nothing promotes a node without an operator.
- The **standby's interface**: writes answer `503 ha_standby` (a frozen primary `503 ha_switchover`), platform administrators sign in with their authenticator code and an in-memory session, a banner points at the primary; dashboard HA tile; HA alert rules `node_offline`, `replication_broken`, `replication_lag`, `ha_sync_failed`, `node_isolated`, `ha_operation_failed`; `verify.sh` checks `ha-role`, `ha-replication`, `ha-sync`, `ha-peer`; `veyra ha status|switchover|failover|resume|rejoin|standalone|sync-now`.
- HA-aware updates: *Install on the standby* from the Updates page; `upgrade.sh` on a standby skips migrations; the switchover runs them at promotion.

## 0.21.0 — 2026-10-15 (Milestone 15)

### Added
- **Central management** ([CENTRAL_MANAGEMENT.md](docs/CENTRAL_MANAGEMENT.md)): any installation can act as a **central console** (System → Central console) for other Veyra installations. Instances enroll with a one-time token and the console's fingerprint (optionally a CA certificate for a self-signed console) and check in every minute over HTTPS with Ed25519-signed messages, nonces and timestamps; the console never connects to an instance (migration `0028`).
- The console lists instances with status, version, available update, registered phones, calls and alerts; an instance page has the last report, 30-day graphs, open alerts, modules and the command history. Instances can be labelled, revoked and then removed.
- **Policies** set the update policy and maintenance window (and optionally the update source and recipients), firewall allow-list entries (tagged "central", removed again when dropped), alert recipients and a notice banner. A default policy goes to instances enrolled without one.
- **Commands**, for one instance or several at once: check for updates, download an update, approve an update (now or in the window), refresh catalogs. They wait for the next check-in and expire after a day; the instance runs them through its own update rules.
- System → **Central management** on the instance: enroll, check in now, leave, and switches for which sections and commands to accept (refusing a section withdraws what it applied). The console's notice shows as a banner on every page, and the Updates page says when the console manages the update policy.
- Alert rules `instance_offline` (no check-in for the chosen number of minutes, 10 by default) and `instance_failed` on the console; permissions `central.read`/`central.write`.

## 0.20.0 — 2026-10-15 (Milestone 14)

### Added
- **Multi-tenancy** ([MULTI_TENANCY.md](docs/MULTI_TENANCY.md)): every organization gets an engine namespace (its own phone, feature, paging, outbound, IVR, ring group and queue contexts, voicemail context, queue names, hold music classes and folders, pickup group names). The organization that existed before keeps exactly today's names; a dev1 comparison produced byte-identical files (migration `0027`).
- An **isolation verifier** reads every generated `extensions.conf`, `pjsip.endpoints.conf` and `queues.conf` and refuses a revision in which one organization's phones or contexts reach another's phones, contexts, voicemail or queues.
- System → Settings → **Multi-tenancy**: turning it on runs the checks against your configuration plus a test copy of your organization; a second active organization needs it (`409 multi_tenancy_disabled`); turning it off needs one active organization.
- Outbound routes can belong to one organization ("Used by"); routes without one serve every organization.
- A paging zone that shares its multicast address with another organization's zone is flagged.

### Changed
- Numbers (extensions, ring groups, queues, paging zones, pages, shared inboxes) are unique per organization instead of across the installation; `/extensions/next-number` takes `organization_id`.
- With multi-tenancy on, the dashboard call graphs and the active-call and registration counts are for platform administrators only.
- The call history and queue reports read queue and ring group names in any namespace.

### Fixed
- Settings still listed single sign-on under "Coming later".

## 0.19.0 — 2026-10-15 (Milestone 13)

### Added
- **Single sign-on** (System → Sign-in; [INTEGRATIONS.md](docs/INTEGRATIONS.md) §1): Google Workspace, Microsoft Entra ID or any OpenID Connect provider, with PKCE, nonce and signature checks (RS256/ES256), allowed domains (Google's hosted domain too), linking of existing accounts on first use, optional account creation with a chosen role, and "Require single sign-on" (the recovery administrator always keeps the password). One redirect address for every provider (migration `0026`).
- **Companion sign-in through the provider**, silent on managed Chromebooks with the new `ssoProvider` policy key; the extension needs the `identity` permission (no install warning).
- **Integration tokens** (System → Integrations): organization tokens (`vyi_…`) with chosen scopes, optional allowed addresses and expiry, held by a service account so the audit log names the integration; for example a door controller sending a page.
- **Outgoing webhooks**: signed JSON (HMAC-SHA256, `Veyra-Signature`) for calls ringing, answered and ended, new voicemail, pages, bells, alerts, phone registrations, deployments and module events; delivered by the worker with retries, auto-off after three days of failure, delivery log with redeliver, test button, secret rotation with a day of overlap. Destinations on the server itself are refused after name resolution, local networks are allowed.
- The Companion directory lists ring groups and queues.
- `installer/bin/veyra-vmnotify` (Asterisk `externnotify`) and the verify check `vmnotify-command`.

## 0.18.0 — 2026-10-15 (Milestone 12)

### Added
- **Updates from the interface** (System → Updates; [SOFTWARE_UPDATES.md](docs/SOFTWARE_UPDATES.md)): update source with an optional read-only token and email recipients; download of signed releases checked against the signed size and SHA-256; review with checks; install now or in a maintenance window; progress shown live through the restart (migration `0025`).
- Policies "download, install on approval" and "install automatically in a maintenance window" for Veyra itself (chosen categories, only when no call is in progress).
- Root upgrade unit `veyra-upgrade@<version>.service`, startable by the service account through polkit only; it verifies the release again against the official keys and runs the release's own `upgrade.sh`.
- `veyra release build|add|refresh|sign` for publishing releases (archives include the prebuilt interface and a `REVISION` file).
- Upgradable operating system packages listed daily (security updates and Asterisk marked; not applied).

### Fixed
- `uninstall.sh` left the pager and firewall services behind.

## 0.17.0 — 2026-10-15 (Milestone 11)

### Added
- **Module catalog** (Module Manager → Catalog and Sources; [MODULE_CATALOG.md](docs/MODULE_CATALOG.md)): signed catalog indexes (keys in `/etc/veyra/trust/catalog/`) listing modules, versions and compatibility, checked daily; install and update from a catalog with the download checked against the index's checksum and the package against its publisher signature; modules live in `<data>/module-store`, searched before the release's own modules (migration `0024`).
- **Upload** of `.vmod` packages from the interface, with the same checks.
- **Rollback** to the previous version (refused when the newer version changed the module's database).
- **Module settings** generated from a module's `[[config]]` fields; secrets stored encrypted.
- **Restart Veyra services** from the interface after a module update (polkit rule for the service account, Veyra's units only; Asterisk is not restarted).
- `veyra catalog add|sign|verify` for publishing a catalog.

### Fixed
- **Installing the AND Clock Messages module failed in production** (error 500): it uses the `httpx` library, which was only installed for development. `httpx` is now a production dependency, a test checks every bundled module's imports against `requirements.txt`, and a module whose code cannot load is refused with the reason instead of a server error (owner report).
- A restart requested from the interface could restart Veyra's services in a loop (found in the live check before release).

## 0.16.0 — 2026-10-15 (Milestone 10b)

### Added
- **Report builder** (Telephony → Reports → Build; [REPORT_BUILDER.md](docs/REPORT_BUILDER.md)): group calls by one or two of day, week, month, hour, weekday, direction, outcome, answering, called or calling extension, DID, trunk, queue, ring group or caller; measure calls, answered, missed, voicemail, answer rate, average and total ring and talk time, answered within a service level; filter by period (relative periods in the organization's time zone), direction, outcome, extensions, DIDs, trunks, queues, ring groups, caller, talk time and **business hours** from a time condition; show as a table, bars or a line; export CSV.
- **Saved reports** (Reports → Saved): shared with the organization or private, opened in the builder, and **emailed on a schedule** (daily, weekly or monthly at a local hour) with the CSV attached; "Send now" (migration `0023`, permission `reports.write`).
- Calls record the queue and ring group they went through (filled in for existing calls).

### Changed
- Telephony → Reports has tabs: Overview (the 0.15.0 page), Build, Saved.

## 0.15.0 — 2026-10-15 (Milestone 10)

### Added
- **Call history** (Telephony → Call History; [REPORTING.md](docs/REPORTING.md) §3): every call with direction, who called, who answered, ring and talk time and the outcome (answered, missed, busy, voicemail, abandoned, failed), searchable by number, name, extension, period, direction and outcome, with the legs behind each call and CSV export; **Recent calls** on everyone's account page (`/me/calls`). Asterisk writes one CSV line per call record through a managed `cdr_custom.conf` (`cdr.conf` now logs unanswered calls); the worker reads it every few seconds and folds the legs into calls; kept 400 days (migration `0019`).
- **Call recording** (Telephony → Call Recording; §4): policies per organization (inbound, outbound, internal; every call or chosen phones, ring groups, queues and DIDs; an announcement; retention) generated into the dialplan; recordings converted to Ogg Opus after the call, played and downloaded in the browser with every listening written to the audit log, held against deletion, deleted after their retention (migration `0020`). Off until a policy enables it.
- **Reports** (Telephony → Reports; §5): calls per day by direction, the busiest hours by weekday, ring and talk time, inbound answered within 20 s, extensions, trunks, and queue statistics from Asterisk's queue log (migration `0021`).
- **Alerts** (System → Alerts; §6): the telephony engine, trunks, Veyra's services, disk space, the HTTPS certificate, firewall attacks and unregistered phones, raised after a delay, emailed when raised, daily while they last and when cleared; dashboard items "Calls today" and "Alerts" (migration `0022`).
- **Prometheus metrics** at `/api/v1/metrics` for a token with `metrics.read`.

## 0.14.0 — 2026-10-15 (Milestone 9d)

### Added
- **Firewall** (System → Firewall; [FIREWALL_TRUST.md](docs/FIREWALL_TRUST.md)): Veyra's own nftables table `inet veyra`, applied by the new `veyra-firewall` service (CAP_NET_ADMIN only) and never touching other tables. Automatic timed bans from Asterisk security events (unknown accounts, wrong SIP passwords), failed sign-ins and second factors, refused provisioning and NGINX rate limiting, scored per address over a window and doubling on repeat offences; a **permanent allow list** (this server, the SIP local networks and trunk addresses automatically, plus your own entries) that is checked first and never banned, with "would have been banned" events to find misconfigured phones; manual blocks per service and with expiry; per-service "allow list only" policy with confirm-or-revert after 60 s; blocklist feeds (CrowdSec local API as a bouncer, or HTTPS address lists); refusal of changes that would cut off the administrator (`firewall_self_block`). Off after installation and upgrade. Console recovery: `sudo veyra firewall off` (migration `0018`).
- **Phone trust** ([FIREWALL_TRUST.md](docs/FIREWALL_TRUST.md) §6): a Veyra certificate authority issues the HTTPS certificate; plain-HTTP provisioning now serves only a bootstrap (the CA and the HTTPS address, no secrets) to the bootstrap networks, so new Poly phones switch to HTTPS on their own; downgrade protection once a phone provisioned over HTTPS ("Allow bootstrap again" on the device page); per organization, the bootstrap may carry the enrollment credential. `/downloads/veyra-ca.crt` for browsers.

### Changed
- The installer replaces Veyra's own **self-signed certificate** with one issued by the Veyra CA at the next upgrade (an administrator's certificate is kept); browsers warn until `veyra-ca.crt` is installed. The TLS step now also runs on upgrades and renews Veyra-issued certificates within 30 days of expiry.
- `logger.conf` is Veyra-managed (the package's channels plus `security.log`); `VEYRA_PROVISIONING_HTTP_MODE=full` keeps the old plain-HTTP behaviour.

## 0.13.2 — 2026-10-15

### Fixed

- **Overview page scrolled past its end and took the menu with it**: the
  charts' hidden data tables (for screen readers) kept their full height,
  one row per sample, because tables ignore the clipping that hides them;
  they are now clipped inside a hidden block (owner report).

## 0.13.1 — 2026-10-15

### Changed

- **Navigation flyouts in columns** (owner request): pages are grouped
  (for Telephony: Phones and calls, Routing, Call handling, Audio, Paging
  and bells, Coming later) and the flyout shows one column per group with a
  heading, widening to fit up to four columns so a category's pages are
  visible at once; Arrow Left/Right move between columns; the mobile
  drawer shows the same headings ([INTERFACE_REWORK.md](docs/INTERFACE_REWORK.md) §1.2).

## 0.13.0 — 2026-10-15 (Milestone 9c)

### Added
- **AND Clock Messages module** (`veyra.and-clocks`, Modules → install; [modules/veyra-and-clocks](modules/veyra-and-clocks/README.md), [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §6): the first real module. Text messages to Advanced Network Devices clocks and signs, like AND's Clockwise: to all clocks, a group or one clock; colour, flashers, priority and display time with AND's inline markup; sent now or at a set time; a message log; reachability checks; messages shown with bells (`{summary}` = the calendar event's name). The clock's own web request is described once under Clock Delivery (method, path, body template, sign-in; the password is encrypted). Permissions `and_clocks.read`/`send`/`write`.
- **Module API 1.1** ([MODULE_DEVELOPMENT.md](docs/MODULE_DEVELOPMENT.md) §3): periodic tasks run by the worker, which now loads enabled modules and delivers their events; `encrypt`/`decrypt` with the installation key; `organization_timezone`; `password` form fields. Core event `bell.rang`.
- **Calendars and bell schedules** (Telephony → Calendars, Bell Schedules; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §4): subscribe to an iCal feed (Google Calendar's secret address or any feed; the address is encrypted at rest and never shown again), fetched every few minutes with recurring rules expanded; a bell schedule rings a recorded page at the start or end of matching events, once per event, within a tolerance; next rings, ring history and a "Ring now" test. Migration `0015`; permissions `bells.read`/`bells.write`; dependencies `icalendar`, `python-dateutil`, `tzdata`.
- **Paging** (Telephony → Pages and Paging Zones; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §2): zones can be dialled by a number from the shared number space, with a policy of who may page (everyone, listed phones, only Veyra) and a longest page; **pages** combine zones with live audio or a recording from the library, a pre-tone, repeats and a Poly priority, are dialable, startable from the interface and the API (`POST /pages/{id}/send`, permission `paging.send`) for external triggers such as a door-held-open alarm, and logged. The **page sender** service (`veyra-pager`) takes one stream from Asterisk per zone and emits the speakers' multicast after the Poly phones' buffering delay together with the Poly group-page datagram, so phones and speakers play in step (the Poly header itself waits for a capture from the phones; until then the Poly leg carries plain RTP). Migration `0014`.
- **Hold music sets** (Telephony → Hold Music; [PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §3.2): ordered or shuffled sets of library recordings, played as the organization's default when a phone puts a caller on hold, per call queue, and per ring group (which can now play music instead of ringing; existing groups keep ringing). Veyra writes `musiconhold.conf` (new installer stub keeping the built-in class) and copies the recordings to `<data>/moh/`; recordings in a set cannot be deleted. Migration `0017`.
- **Shared voicemail inboxes** (Telephony → Voicemail → New shared inbox; [VOICEMAIL_IVR.md](docs/VOICEMAIL_IVR.md) §3.1): a mailbox that belongs to no phone, with its own number from the shared number space, a name and member phones whose message lamp follows it; dialable directly, a destination of its own kind (`voicemail_box`) for inbound routes, IVR keys and fallbacks, ring group and queue failovers (migration `0016`).
- **Audio library** (Telephony → Audio, the former Prompts page; `/prompts` with `kind`, `license`, `credit` and a `kind` filter): recordings are classed as menu prompt, bell, announcement, greeting or hold music; MP3, OGG, FLAC and M4A uploads are decoded by `ffmpeg` (installer package; WAV only without it, `verify.sh` warns) ([PAGING_RECORDINGS.md](docs/PAGING_RECORDINGS.md) §3; migration `0013`).

### Fixed
- **Bells on time**: the worker ran bell schedules once per housekeeping pass (every 60 seconds), so a bell could ring up to a minute late; calendars, bells and module tasks now run on a 5-second tick (`veyra worker --tick`).
- **Compressed audio uploads**: `ffmpeg` now decodes to a temporary file rather than a pipe; a WAV written to a pipe carries placeholder sizes, which made every MP3, OGG, FLAC or M4A upload fail as "longer than 5 minutes".

### Installer
- Modules shipped with a release are signed with this server's own key (`/etc/veyra/secrets/bundled-modules.key`, trusted from `/etc/veyra/trust/official/bundled-modules.pub`), so they can be installed in production; `verify.sh` checks them (`modules-signed`).

## 0.12.0 — 2026-10-14 (Milestone 9b)

### Changed
- **Navigation**: the sidebar is a rail of six categories that never scrolls; clicking or hovering a category opens a flyout panel with its pages (keyboard: Enter opens, arrows move, Escape closes); in the mobile drawer a category expands inline; the top bar shows a breadcrumb (category › page) ([INTERFACE_REWORK.md](docs/INTERFACE_REWORK.md) §1).

### Added
- **Dashboard graphs**: two cards, Channels (with registered phones) and Calls internal vs external, with a 1 h / 6 h / 24 h / 7 d range, refreshed every 30 s, drawn by a dependency-free SVG chart with a screen-reader table. The worker records one engine reading per iteration (every 30 s, `call_samples`, kept 14 days); `GET /system/metrics/calls` serves it downsampled to at most 300 points per range (migration `0012`).

## 0.11.0 — 2026-10-14 (Milestone 9)

### Added
- **Device provisioning** ([DEVICE_PROVISIONING.md](docs/DEVICE_PROVISIONING.md)): phones registered by MAC address (`/devices`, Provisioning → Devices) fetch their configuration from `https://<host>/provisioning/` with HTTP Basic authentication: an enrollment credential per organization for the first fetch (Organization page), then a credential per phone set by its own configuration. Files are rendered on request from the profile's template; every request is logged, unregistered phones that asked for configuration are listed for one-click registration, and the device page shows status, last request, configuration preview, Reprovision and Reboot (SIP NOTIFY).
- **Device profiles** (`/device-profiles`): a template family or model plus settings, line keys (line, BLF with `**` pickup, speed dial, page), paging-zone memberships and firmware; one profile per building when only the paging differs. The phone's model picks the concrete template under a family.
- **Paging zones** (`/paging-zones`, Telephony → Paging Zones, permissions `paging.read`/`paging.write`): the speakers' multicast address and port paired with the Poly group number (1–24, 25 emergency), kind and codec; rendered into the phones' group paging settings.
- **Sites** (`/sites`, Directory → Sites): buildings with time zone, address and a default emergency caller ID for their extensions.
- **Firmware** (`/provisioning/firmware`, Provisioning → Firmware): upload vendor images (up to 512 MB), assign per profile or phone; served by NGINX; the device page compares the running version.
- **Template editor**: local templates are edited in place (manifest and sources, validated on save); **Customize** creates an editable copy of an official template, with local model templates under a customized family. `/provisioning/models` lists the catalog's manufacturers and models.
- **Templates spec version 2**: structured facts (`device`, `organization`, `lines`, `keys`, `paging`, `server`, `features`) with daylight-saving rules from the zone database; Poly VVX templates 0.2.0 (every line, line keys, BLF, voicemail indication, group paging, DST, VLAN, polling, device credential; the VVX 411 template also serves the VVX 410).
- Extensions carried by several phones get `max_contacts` in the engine; Asterisk `pjsip_notify.conf` is now Veyra-managed (`veyra-check-config`, `veyra-reboot`).
- **Emergency caller ID per extension** (`emergency_caller_id_number` on `/extensions`, Extensions form and page): presented on emergency routes instead of the regular caller ID, ahead of the route's and the trunk's numbers; the Outbound Routes page warns when extensions have none and the emergency route has no number of its own ([TRUNKS_ROUTING.md](docs/TRUNKS_ROUTING.md) §7; migration `0010`, snapshot version 6).

## 0.10.0 — 2026-10-14 (Milestone 8)

### Added
- **Ring groups** (`/ring-groups`, Telephony → Ring Groups): a number from the numbering plan that rings an ordered list of extensions all at once or one after the other, with a ring time, an optional caller-ID prefix shown on the phones, skipping of members already on a call (or call waiting), and a failover destination when nobody answers. Generated `veyra-rg-<slug>` contexts with a loop guard; a `hint` per group so BLF keys follow it. Permissions `groups.read`, `groups.write`.
- **Call queues** (`/queues`, Telephony → Call Queues): a number that holds callers with music on hold or ringing, an optional announcement on joining and a repeated one while waiting (prompts), position announcements, and distributes them to agents (extensions with a penalty) by strategy (ring all, round robin, least recent, fewest calls, random, linear) with per-attempt ring time, retry pause, wrap-up, maximum wait, maximum callers and whether callers may wait with no agent available; a failover destination for every way a caller leaves unconnected. New managed file `queues.conf` (reload `app_queue.so`), installer stub `/etc/asterisk/queues.conf`, and the `asterisk-moh-opsound-wav` package so the default hold music has files; `verify.sh` checks the stub, the `Queue`/`Pickup`/`PickupChan` applications and the music class.
- **Call pickup** (`/pickup-groups`, Telephony → Pickup Groups): pickup groups whose members answer each other's ringing calls with `*8` (named call and pickup groups on the endpoints); directed pickup `**<extension>` of any phone in the caller's organization (also for calls ringing through a group or queue); a `hint` per extension so busy lamp fields and BLF pickup work.
- **Group destinations**: inbound routes (destination and after-hours branch), IVR keys and fallbacks, ring-group failovers and queue failovers can point at a ring group or a queue; IVR direct dialling reaches group and queue numbers; groups and queues in use cannot be deleted (`409 ring_group_in_use`, `409 queue_in_use`). The extension API and page list the groups an extension belongs to; the next-number suggestion and the `409 number_in_use` check cover extensions, ring groups and queues together. Migration `0009`. Design and reference: `docs/RING_GROUPS_QUEUES.md`.

### Installer
- NGINX serves `/provisioning/` (rate-limited) and `/provisioning/firmware/` (from `/var/lib/veyra/firmware`); an opt-in plain-HTTP provisioning block (`VEYRA_PROVISIONING_HTTP=1` in `/etc/veyra/installer.conf`, with a warning); `VEYRA_PUBLIC_HOST` and `VEYRA_PROVISIONING_HTTP` written to `veyra.env`; a Veyra-managed `pjsip_notify.conf` stub; the Asterisk control socket opened to group `asterisk` (`asterisk.conf`, backed up; Asterisk restarts once) so the service account can send NOTIFY requests; `verify.sh` checks `prov-location`, `prov-auth`, `prov-http`, `firmware-dir` and `engine-cli`.
- Package `asterisk-moh-opsound-wav` (hold music for queues) and a Veyra-managed `/etc/asterisk/queues.conf` stub; `verify.sh` checks the stub, the `Queue`, `Pickup` and `PickupChan` applications and the `default` music-on-hold class. When the class is missing after an upgrade (Asterisk started before the music files existed), the installer unloads and loads `res_musiconhold.so`.

## 0.9.0 — 2026-10-13 (Milestone 7)

### Added
- **Voicemail boxes** (`/voicemail`, Telephony → Voicemail, Voicemail card on the extension page): one box per extension with a PIN encrypted at rest (shown once on creation or reset), ring time before voicemail answers, email delivery with the recording attached and optional deletion after sending; unanswered and busy calls land in the box; `*97` (own box) and `*98` (any box) from the phone; message waiting indication on the phone (`mailboxes=` on the endpoint and AOR). Users change their own PIN on the account page (`/me/voicemail`). Permissions `voicemail.read`, `voicemail.write`.
- **Email delivery** (`/system/smtp`, Settings → Email delivery): the SMTP server Veyra sends through (STARTTLS, TLS or unencrypted to a loopback relay; password encrypted with the installation key, write-only), a test message to yourself, queue counts. Asterisk hands voicemail notifications to `installer/bin/veyra-mailqueue`, which writes them into `/var/lib/veyra/mailqueue`; the worker sends them with retries (1, 5, 15, 60 minutes) and gives up after a day (`mail.failed` in the audit log). No mail transport is needed on the server.
- **Prompts** (`/prompts`, Telephony → Prompts): WAV uploads converted to 8 kHz 16-bit mono in pure Python (stereo mixed down, resampled), playback in the browser, replace and rename; **recordings from phones** with `*95` (record, `#` to stop, `1` keep / `2` listen / `3` re-record) appear on the page to be named or discarded. Files live under `/var/lib/veyra/prompts/<organization>/`.
- **IVR menus** (`/ivr`, Telephony → IVR Menus): prompt, keys `0`–`9`, `*`, `#` mapped to an extension, a voicemail box, another menu or hang-up, direct extension dialling, timeout and retry limits with separate fallbacks for timeouts and invalid keys, an optional custom invalid-key prompt; the page lists why a menu will not work (`problems`). Generated `veyra-ivr-<slug>` contexts with a loop guard. Permissions `ivr.read`, `ivr.write` (also cover prompts).
- **Typed destinations**: inbound routes (destination and after-hours branch) and IVR keys point at an extension, the voicemail of an extension or an IVR menu; the API returns a label and a `missing` flag, the generator renders missing targets as congestion, and boxes or menus in use cannot be deleted (`409 voicemail_in_use`, `409 ivr_in_use`, `409 prompt_in_use`).
- The installer manages `/etc/asterisk/modules.conf` (package list plus `noload` for `app_voicemail_odbc.so`, `app_voicemail_imap.so`, `cdr_radius.so`, `cel_radius.so`): on Ubuntu the ODBC voicemail module failed to load beside `app_voicemail.so` and unregistered the `VoiceMail` applications; `verify.sh` checks that the application is registered. Asterisk restarts once when the file changes.
- New managed file `voicemail.conf` (sensitive; reload `app_voicemail.so`), installer stub `/etc/asterisk/voicemail.conf`; `/var/lib/veyra` becomes `veyra:asterisk` with `prompts/` and `mailqueue/` shared with Asterisk, and the service account joins group `asterisk` so the worker can read what Asterisk writes there; `verify.sh` checks them. Migration `0008`. Design and reference: `docs/VOICEMAIL_IVR.md`.

### Changed
- Audit details redact keys containing `pin` as well as passwords, secrets, tokens and keys.
- The worker drains the mail queue and keeps the per-organization prompt folders on every iteration.
- `python-multipart` added for multipart uploads (pure Python).

## 0.8.1 — 2026-10-13

### Added
- **Managed deployment of the Companion** (`docs/COMPANION.md` §5.1): the installer signs the extension into `veyra-companion.crx` with a server-held key (stable extension ID), NGINX serves it at `/downloads/veyra-companion.crx`, and the API serves the update manifest at `/api/v1/companion/update.xml`; Settings → Companion extension deployment shows the ID, update URL, install-source pattern, policy JSON and the Google Admin Console steps; the account page gains an *Add to Chrome* button and clearer manual steps. `GET /companion/info`. Setting `VEYRA_COMPANION_DIR`; installer variable `VEYRA_PUBLIC_HOST` overrides the host name used for the packaged host permission.
- The extension reads policy-provided settings (`chrome.storage.managed`: `serverUrl`, `dialPrefix`), preloading and locking the server address.

## 0.8.0 — 2026-10-13 (Milestone 6b)

### Added
- **Veyra Companion** browser extension (Chrome/Edge, Manifest V3) under `companion/`: sign in with Veyra credentials and the second factor, click-to-dial from a popup, the context menu or `tel:` links (the desk phone rings first), directory search, incoming and missed-call notifications, speed dials and settings stored in the user's profile (`docs/COMPANION.md`).
- The installer packages the extension as `veyra-companion.zip`, served at `/downloads/veyra-companion.zip`; the account page's Connected apps card links to it with the install steps.
- **Scoped bearer tokens** (ADR 0015): `POST /auth/companion/login` and `/verify` reuse the web sign-in checks and issue a `vyc_…` token limited to `calls.originate`, `calls.read`, `directory.read` and own-account routes; tokens expire 30 days after last use (180 days at most), are listed and revoked on the account page ("Connected apps"), by administrators (`/users/{id}/tokens`) and by `veyra sessions revoke`. Migration `0007`.
- `GET /me/extensions`, `GET/PUT /me/preferences`, `GET /directory` (new permission `directory.read` for every role).
- **Call-event stream**: the API keeps one WebSocket to Asterisk's ARI events and serves `WS /events/calls` (ticket from `POST /events/ticket`) with `call.ringing`, `call.dialing`, `call.answered` and `call.ended` for the caller's own extensions; the engine page reports the listener state. NGINX proxies the WebSocket path. New dependency `websockets`.

### Development
- `tools/fakephone.py` answers digest challenges when it places a call, so it can dial as a registered phone.

## 0.7.0 — 2026-10-13 (Milestone 6)

### Added
- **SIP trunks** (`/trunks`, Telephony → SIP Trunks): registration and IP-authenticated carrier connections with write-only passwords encrypted at rest, codec and caller-ID options, channel caps and live reachability from the engine's qualify ping. Generated `pjsip.trunks.conf` (the installer's `pjsip.conf` stub includes it).
- **Inbound routes** (`/routing/inbound`, Telephony → Inbound Routes): DIDs to extensions per organization, optionally restricted to one trunk, with North American `1`/`+1` aliases, a caller-ID name prefix and a catch-all (`any`) route per trunk or shared.
- **Outbound routes** (`/routing/outbound`, Telephony → Outbound Routes): dial patterns (prefix, match, prepend) to an ordered list of trunks with failover on CHANUNAVAIL/CONGESTION, per-route caller ID, drag-free reordering, and emergency routes that are always evaluated first; warnings when no emergency route exists.
- **Time conditions** (`/routing/time-conditions`, Telephony → Time Conditions): weekly ranges and yearly holidays in a time zone, used by inbound routes to pick an in-hours or after-hours destination; `open_now` in the API.
- Loop detection: calls arriving from a trunk may not leave through a trunk; trunk channel caps enforced with `GROUP_COUNT`.
- Permissions `trunks.read`, `trunks.write` (platform), `routing.read`, `routing.write`. Migration `0006`.
- Design and reference: `docs/TRUNKS_ROUTING.md`; emergency routing status in `docs/EMERGENCY_CALLING.md`.

### Changed
- Phone endpoints carry `set_var=VEYRA_ORG=<organization>` for later per-tenant routing; `veyra-internal` now includes `veyra-outbound` between the feature codes and the invalid-number catch-all.

### Development
- `tools/fakephone.py` can act as a carrier (`--no-register`, `--call`, `--from-user`, `--header`, `--hangup-after`) and bind to a chosen address (`--local-ip`).

## 0.6.0 — 2026-10-13 (Milestone 5)

### Added
- Live registration state per extension (badge in the list and on the page, refreshed every 15 s) from the engine's endpoint status.
- Telephony → **Active Calls**: channels that are up, with the owning extension and real durations, scoped to the caller's organizations (`GET /calls`, permission `calls.read`).
- **Click-to-dial**: "Call from this phone" on the extension page and `POST /calls/originate` ring the extension first and place the call when answered (ARI originate); users dial from their own extensions (`calls.originate`), administrators from any extension they manage. Internal numbers and feature codes until trunks exist.
- **Deploy when no calls are active**: a drop-down on the Deploy changes button (and `{"mode": "when_idle"}` on apply/deploy, `veyra config deploy --when-idle`); the deployer waits while the engine reports active calls, up to `VEYRA_DEPLOY_IDLE_TIMEOUT_MINUTES` (30), then deploys and records the wait; the top bar shows "Waiting for N calls to end". Migration `0005`.

### Changed
- Active call durations are computed from the channel creation time (they were reported as 0).

### Fixed
- Feature codes `*43` (echo test) and `*60` (speaking clock) were unreachable from phones: the invalid-number catch-all lived in `veyra-internal` itself and Asterisk matches a context's own patterns before its includes. The catch-all now lives in `veyra-invalid`, included after `veyra-features`. Takes effect on the next generated and deployed revision.

### Development
- `tools/fakephone.py`: a standard-library SIP phone for exercising registration, calls, click-to-dial and deploy-when-idle on a server without a handset (`docs/DEVELOPMENT.md` §3b).

## 0.5.0 — 2026-10-12 (Milestone 4b)

### Added
- Two-factor authentication (`docs/MFA_DESIGN.md`): authenticator apps (TOTP, RFC 6238) with ten single-use recovery codes; sign-in answers 202 and opens a 5-minute pre-authentication session that can reach only the second-step routes; codes accept one step of clock drift and are never accepted twice; five wrong codes lock the attempt. Enrolment with a server-rendered QR code or manual key, device labels, recovery codes shown once with download and copy; devices removed and codes regenerated behind the password. Account page card, sign-in second step with inline enrolment, grace notice in the shell.
- Two-factor policy (`/auth/mfa/policy`, Settings → Two-factor policy): which roles must use it (Platform and Organization Administrators by default) and how many days they have (14); saving re-evaluates every user and is audited. Administrators reset a user's factors from the user page (`POST /users/{id}/mfa/reset`); `veyra users mfa-reset <email>` on the server is the escape hatch for the recovery administrator.
- `GET /auth/session` and `GET /users/{id}` report the two-factor status (`mfa`, `mfa_enabled`). NGINX rate-limits code verification like sign-in.
- Migration `0004`: `mfa_methods`, `mfa_recovery_codes`, `users.mfa_required_at/mfa_grace_until`, `sessions.mfa_verified_at/mfa_failures` (existing sessions stay valid).
- Roadmap: click-to-dial API (Milestone 5) and the Veyra Companion browser extension (Milestone 6b).

### Changed
- **Deploy changes** now appears after any save that may affect the engine (extensions, SIP settings) and stays until a deployment runs, whether or not the generated files differ; the engine status reports who saved and when (`pending_since`, `pending_by`).
- Dependency: `segno` 1.6.6 for QR codes.

## 0.4.0 — 2026-10-12 (Milestone 4)

### Added
- Installation key (`/etc/veyra/secrets/installation.key`, ADR 0014): a 256-bit key generated by the installer (also on upgrade, never replaced) that encrypts secrets at rest with AES-256-GCM and purpose binding. `veyra installation-key generate|check`; `verify.sh` checks it; `VEYRA_INSTALLATION_KEY_FILE`.
- Extensions (`docs/EXTENSIONS.md`): `/extensions` CRUD scoped by organization, optional assigned user, caller ID, enable/disable, delete; SIP user name `<org>-<number>`; server-generated SIP secrets stored encrypted, shown and rotated only through audited endpoints (`extension.secret_reveal`, `extension.secret_rotate`); global search finds extensions.
- Numbering plan (`/telephony/numbering`): length, range and reserved leading digits (`0`, `9`, `911`, `933` by default), enforced on create and renumber; `GET /extensions/next-number` suggests the lowest free number; a numbering step in the setup wizard.
- Extensions pages: list with search and organization filter, create dialog with "Suggest next free", detail page with SIP credentials (show, copy, rotate), delete with typed confirmation, numbering plan card; notices when changes are waiting to be deployed or the installation key is missing.
- `GET /telephony/engine` reports `changes_pending` and `installation_key_present`; the engine page shows both.
- **Deploy changes** button in the top bar for platform administrators whenever changes are pending (`POST /telephony/apply` generates and deploys in one step, discards a no-change revision, reports generation problems); other users see a "changes pending" badge.
- The running version is shown next to the logo (the installed release name in its tooltip); `GET /auth/session` carries `version` and `release`.
- Versioning scheme adopted (see the top of this file); version 0.4.0 marks Milestone 4.
- Migration `0003`: `extensions.sip_secret_changed_at`.

### Changed
- Configuration snapshots now contain the enabled extensions of active organizations with decrypted SIP secrets; the generator refuses duplicate numbers; sensitive revision files are stored encrypted in `config_revisions.artifacts` and decrypted by the deployer (a deployer without the key fails the revision and restores the previous files).
- The `Extensions` navigation entry is live (needs `extensions.read`) instead of "coming later".

### Fixed
- The logo appeared twice side by side on the sign-in, setup and account pages, and the emblem showed next to the wordmark in the sidebar: inline styles overrode the CSS that hides the unused artwork.
- `upgrade.sh` now records `upgrade_status: complete`, so a failure marker from an earlier attempt does not linger in the install state.

## 0.1.0-dev.0 (Milestone 3)

### Added
- Telephony engine integration (`docs/TELEPHONY_ENGINE.md`): Asterisk configuration generated from the database (PJSIP transports and endpoint templates, dialplan with `*43` echo test and `*60` speaking clock, RTP settings) into `/etc/asterisk/veyra/`, which Veyra-managed stub files include.
- Configuration revisions: generate, preview diffs, deploy, discard, and roll back by redeploying an older revision (`/telephony/revisions`, `veyra config`). Failed deployments restore the previous files.
- `veyra-deployer` service: the only process that writes engine files; targeted module reloads over ARI (`res_pjsip.so`, `pbx_config.so`, `res_rtp_asterisk.so`) and post-reload verification.
- SIP and media settings (`/telephony/settings`, System → Telephony Engine): bind address, ports, TLS, NAT addresses, local networks, RTP range, codecs, language, with validation.
- Engine status (`/telephony/engine`): version, start and reload times, module status, endpoint and channel counts; `/system/health` now reports real `registrations` and `active_calls` counts. The setup wizard shows the engine state.
- Installer: Asterisk stubs replace the package samples (backed up), `/etc/asterisk/veyra` is `2750 veyra:asterisk`, the deployer unit is installed and verified; upgrades reload Asterisk only when its managed files changed and never restart it.

## 0.1.0-dev.0 (Milestone 2)

### Added
- Sessions: `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others`; administrators: `GET/DELETE /users/{id}/sessions`. "Your account" page with profile, password change and active sessions; the user page shows a user's sessions with "Sign out everywhere".
- Password reset links (ADR 0011): `POST /users/{id}/password-reset-link`, public `/reset-password/` page, `POST /auth/password-reset/check` and `POST /auth/password-reset`; `veyra users reset-password` and `veyra users unlock` on the server; `POST /users/{id}/unlock` and an "Unlock now" button.
- Forced password change: passwords set by an administrator (on creation or reset) are temporary unless `require_password_change` is false; the user is taken to the account page and can reach nothing else until they choose a password. `password_changed_at` and `must_change_password` on users (migration `0002`).
- Password policy: at least four distinct characters, no weak words however padded, no personal information (name, email local part), new password must differ from the current one.
- Fetch-metadata check: mutations labelled `cross-site` or `same-site` by the browser are refused (`403 cross_site_request`). `Clear-Site-Data` on sign-out. NGINX rate limits the password-reset endpoints like sign-in.
- Worker purges expired and revoked sessions and used reset tokens after the retention period (`VEYRA_SESSION_RETENTION_DAYS`, default 30); `veyra sessions purge` and `veyra sessions revoke`.
- MFA design (`docs/MFA_DESIGN.md`, ADR 0012): TOTP with recovery codes first, passkeys second, pre-auth session at sign-in; implementation scheduled later.

### Changed
- `UserOut` includes `locked_until`, `password_changed_at` and `must_change_password` (administrators only see these through the users API; the sign-in form stays generic).
- The user menu links to the account page instead of a password dialog.

## 0.1.0-dev.0 (Milestone 1)

### Added
- Approved branding artwork (raster exports supplied by the owner) replaces the placeholder SVGs: compact and full logos for light and dark backgrounds, emblem, app icon, favicons, touch icon, a web manifest, and the owner's ASCII wordmark for the CLI and installer. The branding board is kept in `docs/branding/`.
- First real installations: veyra-dev1 (Ubuntu 26.04) installed, verified and upgraded; Ubuntu 24.04 installed, verified, uninstalled and reinstalled in an LXD container. Reports in `docs/installations/`.
- ADR 0010: Asterisk is installed from the Ubuntu archive (22.5.2 on 26.04, 20.6.0 on 24.04), not built by Veyra.
- Installer: reinstalling after `uninstall.sh` is recognised and reported as a reinstall over kept data.

### Fixed
- Installer: NGINX is restarted instead of reloaded when its listen sockets change (the package default site's wildcard sockets blocked Veyra's address-specific listeners, so HTTPS never came up), and the step verifies an HTTPS request before reporting success.
- Installer: `verify.sh` no longer flags the venv's symbolic links as world-writable code.
- Installer: failures that exit through `die` are recorded in the state file (`failed:<step>`); the original `started_at` survives resumed runs.
- Installer: the HTTP redirect no longer reveals the NGINX version; unknown paths return 404 instead of 200; IPv6 setup URLs are bracketed; the self-signed certificate lists a hostname once when it equals the FQDN; a missing Node.js is reported as missing rather than as version 0; the upgrade summary names releases when the version number is unchanged.

### Changed
- Installer: release names carry a `-dirty` suffix when installed from a source tree with uncommitted changes.

## 0.1.0-dev.0 (Milestone 0)

### Added
- Architecture and design documentation: architecture, HA, engine evaluation (Asterisk selected), module development, provisioning templates, update management, installation, development, networking, database schema, licensing evaluation, emergency calling notes and ADRs 0001–0009.
- Backend foundation (FastAPI, SQLAlchemy, Alembic, PostgreSQL): tenancy and identity schema, local authentication (Argon2id, server-side sessions, CSRF, rate limiting, lockout), scoped RBAC, append-only audit log, first-run setup with a console token, health and HA status APIs, global search.
- Module framework: manifest specification and validator, Ed25519-signed packages with trust levels, per-module migrations, lifecycle (install/enable/disable/update/uninstall with data retention), event bus, health checks, declarative UI views, and the `veyra.example-notes` example module.
- Provisioning template framework: specification, inheritance, sandboxed rendering, validation, preview with secret masking, import/export, and experimental Poly VVX 411/450 templates.
- Update management foundation: per-component policies, channels, signed update metadata verification, update checks and history.
- Telephony adapter interface with an Asterisk ARI health check.
- `veyra` CLI with color/monochrome/ASCII terminal branding.
- Frontend foundation: Next.js static export, design system, application shell and pages backed by the API.
- Installer: `preflight.sh`, `install.sh`, `verify.sh`, `upgrade.sh`, `uninstall.sh`, systemd/NGINX/Asterisk templates.
- CI: backend tests (PostgreSQL), lint and type checks, frontend lint/typecheck/test/build, ShellCheck, dependency audit, secret scan; Dependabot.
