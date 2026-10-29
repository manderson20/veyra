# Provisioning hardware checks

Every official template is `experimental` until a check like the one below
has been recorded for at least one model of its family
([PROVISIONING_BREADTH.md](PROVISIONING_BREADTH.md) §7, issue #34). The
check takes about an hour per device. Record the result at the end of this
file (date, model, firmware, outcome, notes); a passed check moves the
family's templates to `stable` in the next release.

## Before you start

1. A spare device, factory reset, on the voice VLAN.
2. A device profile for it with: one line, a BLF on a colleague, a speed
   dial, a page key (phones), the building's paging zones subscribed, a
   firmware image (optional), and one of each new key type you want to try
   (voicemail, DND, park with a slot, a call-flow toggle).
3. The device registered under Provisioning → Devices with its MAC, model,
   profile and extension.
4. The organization's enrollment credential at hand (Organizations →
   organization → Provisioning credential).
5. Open the device's Configuration tab: the preview must show no error and
   no missing-variable warning.

## Phones (Poly VVX/Edge E/CCX, Yealink)

| # | Step | Expected |
|---|---|---|
| 1 | Point the phone at the provisioning URL (DHCP option 66/160, the vendor redirect service, or typed on the phone) with the enrollment credential | Provisioning → Requests shows the phone's files with result `ok` |
| 2 | Wait for the reboot | The line registers (Telephony → Registrations) and shows the extension's name |
| 3 | Look at the keys | Every key in the profile's order with its label |
| 4 | Call the BLF colleague from a third phone | The BLF lamp blinks; pressing it picks the call up |
| 5 | Press the speed dial | The number is called |
| 6 | Press the page key | The zone's speakers and phones play the page |
| 7 | Page the zone from another phone | This phone plays it, in sync with the speakers |
| 8 | Leave a voicemail for the extension | The message lamp lights; the voicemail key calls `*97` |
| 9 | Press the DND key | DND turns on, the lamp lights; again: off |
| 10 | Park a call on the watched slot | The park key lights; pressing it picks the call up |
| 11 | Switch the call flow from the web | The toggle key lights; pressing it switches back |
| 12 | Check the time and date after a DST change date (or compare the rule in the configuration) | The clock follows daylight saving |
| 13 | Change a provisioning variable the phone uses | Within a minute the phone re-reads its configuration (NOTIFY) and shows the change |
| 14 | Upload and assign a newer firmware image | The phone upgrades on its next check |
| 15 | Phone book (Yealink: Directory → Remote phone book; Poly: Directory) | The organization's extensions are listed |
| 16 | From another phone dial the intercom code and this extension (`*80<ext>`) | The phone answers on the speaker by itself with a tone; the microphone is open unless the profile sets "intercom_mic_muted" |

### Grandstream notes (GRP26xx, GXP21xx)

- Point the phone at Veyra: web interface → Maintenance → Upgrade and
  Provisioning: *Config Upgrade Via* HTTPS, *Config Server Path*
  `<server>/provisioning`, HTTP/HTTPS user name and password = the
  organization's enrollment credential; or DHCP option 66
  `https://<server>/provisioning`. Provisioning → Requests should show
  `cfg<mac>.xml` with `ok` (`cfg<mac>`, `cfg<model>.xml` and `cfg.xml` show 404:
  expected).
- After the first fetch: Maintenance → Security → Trusted CA certificates
  lists the Veyra CA; *Validate Server Certificates* can then be turned on
  with the template variable `validate_server_certificate`.
- Step 15 (phone book): check the phone downloads it (Phonebook → the
  organization's names). If it does not, the firmware refuses credentials in
  the phonebook path: note it in the results.
- Step 14 (firmware): upload the image under Grandstream's own file name
  (`grp26xxafw.bin`, `grp26xxbfw.bin`, `grp2600fw.bin`, `gxp2170fw.bin`…);
  the phone asks for its file name in the image's folder.
- The GXP's first keys are *line keys* with their own key codes: check a BLF
  and a speed dial placed on keys 1–3 work as well as on later keys.

## Grandstream ATAs (HT801/HT802, HT812/HT814/HT818)

| # | Step | Expected |
|---|---|---|
| 1 | Point the ATA at Veyra (web interface → Maintenance → Upgrade and Provisioning, as for the phones below, or DHCP option 66) | Provisioning → Requests shows `cfg<mac>.xml` with `ok` |
| 2 | After the reboot: Status page | Each port with an extension registered (HT81x: profile 1, and profile 2 when a port is a fax machine (T.38)); ports without an extension disabled |
| 3 | Analog phone on port 1: call another extension, then dial `*97` | The call connects; voicemail answers (feature codes reach Veyra, not the ATA) |
| 4 | Leave a voicemail for the port's extension | Stutter dial tone, and the lamp on a phone with visual MWI |
| 5 | Extension with a hotline number: lift the handset | Dials the hotline after the warm-line delay |
| 6 | Fax machine on a port whose extension is **not** a fax machine (T.38): send a fax to a fax number through the trunk, and receive one | Both arrive (G.711 pass-through); the port's fax mode is *Pass Through* |
| 7 | Turn on **Fax machine (T.38)** on that extension, deploy, check-sync the ATA; with the trunk's T.38 on, send and receive a fax | Both arrive; `pjsip show channel` shows T.38 (udptl) on both legs |
| 8 | Same with the trunk's T.38 off | Both still arrive (Asterisk declines T.38; the ATA stays on G.711) |

### Grandstream ATA notes

- The ATA's own star codes (*Local Call Features*) are off, so `*69`,
  `*72`, `*78` and the rest go to Veyra; turn them back on with
  `local_call_features` only if a site relies on the ATA's codes.
- Fax lines: plug the fax machine straight into the ATA (no splitter), keep
  ECM on in the fax machine, and check the result report. A failed G.711 fax
  usually means jitter or packet loss on the path; T.38 end to end (step 7)
  is the fix where the carrier supports it.
- Line 3 and later on an HT802 (or lines past the HT812/HT814's ports) are
  not configured; the file says so in a comment.

## Algo speakers, horns and adapters

| # | Step | Expected |
|---|---|---|
| 1 | Set the device's provisioning to the server (DHCP option 66 or the static server in its web page, method HTTPS) | Provisioning → Requests shows `algom<MAC>.conf` and `algom<MAC>.md5` with result `ok` |
| 2 | After the reboot, open the device's web page | SIP page extension registered; multicast mode *Listener*; the zones listed |
| 3 | Page each zone from a phone | The device plays the pages of its zones only |
| 4 | Page the emergency zone | The device plays it as the priority zone, over a running page |
| 5 | With multicast format *both*: page from a Poly phone's page key | The speaker and the Poly phones play together |
| 6 | Call the page extension | The device answers and plays the call |
| 7 | Change a variable the device uses | The device takes it at its next sync (or at once after a check-sync) |

## Results

| Date | Model | Firmware | Outcome | Notes |
|---|---|---|---|---|
| | | | | |
