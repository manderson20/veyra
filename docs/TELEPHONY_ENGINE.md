# Telephony engine integration

How Veyra configures and observes Asterisk. Delivered in Milestone 3; the
objects that fill the configuration (extensions, trunks, routes) arrive in
the milestones after it.

## 1. Principles

* **The database is the source of truth** ([ADR 0003](adr/0003-database-authoritative-config.md)).
  Nobody edits Asterisk files by hand; Veyra generates them.
* **Generation is a pure function** of a *snapshot* of the database
  (`veyra/telephony/snapshot.py`). The same data always produces the same
  bytes, so "no change" is detected by content hash.
* **Only the deployer writes to the engine.** The API process creates
  revisions and asks for deployments; the `veyra-deployer` service (a
  separate process, the only one with write access to
  `/etc/asterisk/veyra`) performs them.
* **Reloads are targeted.** A dialplan change reloads `pbx_config.so`; a SIP
  change reloads `res_pjsip.so`; RTP settings reload `res_rtp_asterisk.so`.
  Asterisk is never restarted by a deployment and calls in progress are not
  disturbed.
* **Every deployment is reversible.** Deploying an older revision again is
  the rollback. A failed deployment restores the previous files itself.

## 2. Files

The installer replaces the package's sample `pjsip.conf`, `extensions.conf`,
`rtp.conf`, `voicemail.conf`, `queues.conf` and `pjsip_notify.conf` with Veyra-managed stubs (the `pjsip.conf`
stub includes the three generated PJSIP files) (the samples are backed up
beside them as `*.veyra-backup-<timestamp>`). Each stub only `#tryinclude`s
the generated files:

| Stub in `/etc/asterisk/` | Generated file in `/etc/asterisk/veyra/` | Content | Reload |
|---|---|---|---|
| `pjsip.conf` | `pjsip.transports.conf` | UDP, TCP and optional TLS transports from the SIP settings, NAT addresses, local networks | `res_pjsip.so` |
| `pjsip.conf` | `pjsip.endpoints.conf` | Endpoint, auth and AOR templates; one endpoint, auth and AOR section per enabled extension of an active organization ([EXTENSIONS.md](EXTENSIONS.md)); `max_contacts=<n>` on the AOR when more than one registered phone carries the extension ([DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §2); `mailboxes=<number>@veyra` on the endpoint and AOR of extensions with a voicemail box (MWI); `named_call_group`/`named_pickup_group` with the extension's pickup groups ([RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §4). **Sensitive** when it contains SIP secrets: never shown in diffs, stored encrypted in the revision | `res_pjsip.so` |
| `pjsip.conf` | `pjsip.trunks.conf` | Per enabled trunk: endpoint, AOR, identify and, in registration mode, auth and registration sections ([TRUNKS_ROUTING.md](TRUNKS_ROUTING.md) §8). **Sensitive** when it carries a trunk password | `res_pjsip.so` |
| `extensions.conf` | `extensions.conf` | `[veyra-features]` (`*43` echo test, `*60` speaking clock, `*95` prompt recording, `*97`/`*98` voicemail, `*8` group pickup, `**<extension>` directed pickup within the organization), `[veyra-internal]` (a `hint` and one `Dial(PJSIP/<endpoint>,30)` per extension, or `Dial(...,<ring_seconds>)` followed by `VoiceMail()` for extensions with a box; ring group and queue numbers jumping to their contexts; includes `veyra-features`, `veyra-outbound`, then `veyra-invalid`), `[veyra-invalid]` (invalid-number handling; kept out of `veyra-internal` because Asterisk matches a context's own patterns before its includes, which would shadow the feature codes), `[veyra-outbound]` and one `[veyra-out-<slug>]` per outbound route, `[veyra-from-trunk]` (shared DIDs) and `[veyra-from-trunk-<slug>]` plus `-fallback` per trunk ([TRUNKS_ROUTING.md](TRUNKS_ROUTING.md) §3-§4), one `[veyra-ivr-<slug>]` per enabled IVR menu ([VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §5), one `[veyra-rg-<slug>]` per ring group and `[veyra-queue-<slug>]` per queue ([RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §2, §3) | `pbx_config.so` |
| `rtp.conf` | `rtp.conf` | RTP port range, strict RTP | `res_rtp_asterisk.so` |
| `voicemail.conf` | `voicemail.conf` | `[general]` (formats, limits, sender, `mailcmd` into Veyra's mail queue), `[zonemessages]` per organization time zone, `[veyra]` with one mailbox line per enabled box ([VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §3.2). **Sensitive**: carries PINs in clear | `app_voicemail.so` |
| `queues.conf` | `queues.conf` | `[general]` and one `[veyra-<slug>]` per enabled queue with its strategy, timers, limits, announcements and static `member =>` lines ([RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §3) | `app_queue.so` |
| `pjsip_notify.conf` | `pjsip_notify.conf` | NOTIFY types for device management: `veyra-check-config` (`Event: check-sync;reboot=false`) and `veyra-reboot` (`reboot=true`), sent with `pjsip send notify <type> endpoint <endpoint>` by the Devices page ([DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §3.5) | `res_pjsip_notify.so` |

`/etc/asterisk/veyra` is `2750 veyra:asterisk`: the deployer (user `veyra`)
writes, Asterisk (group `asterisk`) reads, files are `0640`. `verify.sh`
checks the directory, the stubs and the deployer service.

The service account also uses the Asterisk command line (`asterisk -rx`)
for the one operation ARI does not offer, sending a NOTIFY to a phone; the
installer opens the control socket to group `asterisk` for that
(`asterisk.conf`: `astctlpermissions = 0660`, `astctlgroup = asterisk`).

`ari.conf`, `http.conf`, `manager.conf` and `modules.conf` are still
installed by the installer, not generated: they hold the ARI credential and
the module selection (only `app_voicemail.so` of the voicemail backends, no
RADIUS accounting) and never change between deployments; a change to them
restarts Asterisk during the upgrade.

## 3. Settings

SIP and media settings live in `system_settings` under `telephony.sip`
(`veyra/telephony/settings.py`, `GET/PUT /api/v1/telephony/settings`,
platform administrators only): bind address, UDP/TCP/TLS ports, external
signaling and media addresses, local networks, RTP range, codecs, default
language. Validation covers addresses, CIDRs, codec names and cross-field
rules (SIP ports outside the RTP range, both NAT addresses or neither,
local networks required with NAT). Saving settings changes nothing on the
engine until a revision is generated and deployed.

## 4. Revisions and deployment

```
POST /telephony/revisions          generate + validate   -> validated | failed
POST /telephony/revisions/{id}/deploy                    -> deploying (queued)
      veyra-deployer: write files atomically -> reload scopes -> verify -> deployed
                      on failure: restore previous files -> reload -> failed
POST /telephony/revisions/{id}/deploy  on a superseded revision = rollback
POST /telephony/revisions/{id}/discard on a validated revision
POST /telephony/apply                  generate + deploy in one step ("Deploy changes")
```

`apply` is what the **Deploy changes** button in the top bar calls (the
equivalent of "Apply Config" elsewhere). It appears for platform
administrators whenever `changes_pending` is true, generates a revision and
queues it; a revision identical to the deployed one is discarded instead,
and a generation problem is reported without queuing anything. The
revision list on the engine page is the place to review a diff before
applying.

**Deploy modes** (`{"mode": "now" | "when_idle"}` on `apply` and `deploy`,
`veyra config deploy --when-idle`, the drop-down on the button):

* `now` (default): the deployer writes and reloads at once. Reloads are
  targeted and never restart Asterisk, so calls in progress continue; this
  is safe for extension and dialplan changes.
* `when_idle`: the deployer holds the queued revision while the engine
  reports active channels and checks again every poll. It gives up waiting
  after `VEYRA_DEPLOY_IDLE_TIMEOUT_MINUTES` (30) and deploys anyway, noting
  the wait and the number of active calls in the revision log. Suggested
  for SIP transport changes (bind address, ports, TLS), the one category
  where a reload can briefly drop registrations. The engine status reports
  `pending_mode`, `pending_requested_at` and `pending_active_calls`; the top
  bar shows "Waiting for N calls to end".

* A revision stores its files in `config_revisions.artifacts` (sensitive
  files encrypted with the installation key, the others in clear), the
  content hash, the parent (the revision that was deployed when it was
  generated), who created it and, after deployment, a short log in
  `validation_errors`. The deployer decrypts sensitive files when it writes
  them; a deployer without the key fails the revision and restores the
  previous files.
* The API returns file contents and unified diffs to platform
  administrators only; organization administrators with `config.read` see
  the metadata. Sensitive files report only "changed".
* `deploy` is refused while another deployment is queued, when the engine
  is not running, and for revisions in any state but `validated` or
  `superseded`.
* The deployer polls every two seconds (`veyra deployer --interval`). Its
  log: `journalctl -u veyra-deployer`.
* Static validation (`generator.validate`) checks file names, section
  headers and key/value lines before anything is written. There is no
  "asterisk -C"-style dry run for includes, so the post-reload verification
  (`GET /asterisk/modules/{name}` must report `Running`, ARI must answer)
  is the authoritative check. Dialplan contexts cannot be listed through
  ARI; `sudo asterisk -rx "dialplan show veyra-internal"` shows them.

* `GET /telephony/engine` reports `changes_pending`, `pending_since` and
  `pending_by`: any save that may affect the engine (extensions, SIP
  settings) raises a flag that stays until a deployment runs, like "Apply
  Config" elsewhere, even when the generated files turn out identical; the
  flag also clears when an apply finds nothing to change. A database that
  differs from the deployed revision counts as pending too. The Extensions
  pages show a notice and the top bar shows the red **Deploy changes**
  button. Also reported: `installation_key_present`.

Console equivalents: `veyra config status`, `veyra config generate
[--deploy]`, `veyra config deploy <sequence>`.

## 5. Status

`GET /telephony/engine` reports the engine's state, version, start and
last-reload times, the status of the modules Veyra depends on, how many
PJSIP endpoints exist and are registered, and how many channels are up.
`GET /system/health` carries the two counts as `registrations` and
`active_calls` (`null` when the engine cannot report them, never a made-up
number). The engine page under System shows all of this and refreshes
every 15 seconds. Endpoint status comes from ARI `/endpoints`; channel
counts from `/channels`. Since Milestone 5 the extension list and page show
each phone's registration state from the same data, `GET /calls` lists the
channels that are up (with their owning extension and real durations, scoped
to the caller's organizations; Telephony → Active Calls refreshes every five
seconds), and `POST /calls/originate` is click-to-dial: ARI `POST /channels`
rings the extension's endpoint and, once answered, runs the dialplan at the
dialled number in `veyra-internal`, so the call is placed without typing on
the handset. Standard users may dial from their own extensions
(`calls.originate`); administrators from any extension they manage.

Since Milestone 6b the API process also holds one WebSocket to ARI's event
stream (`/ari/events?app=veyra&subscribeAll=true`, never putting channels
into Stasis) and turns channel events for phone endpoints into call events
for the Companion ([COMPANION.md](COMPANION.md) §4). `GET /telephony/engine`
reports the listener under `events` (`disabled`, `connecting`, `connected`,
`reconnecting`, connected clients, events seen).

## 6. Security notes

* ARI stays on loopback with a generated credential; the adapter refuses
  any other URL.
* The deployer unit is sandboxed like the API (`ProtectSystem=strict`) with
  exactly one extra writable path, `/etc/asterisk/veyra`.
* Every value that reaches a generated file is validated against an
  allow-list pattern (section names, numbers, display names, addresses);
  newlines, brackets and semicolons cannot be injected.
* SIP secrets reach `pjsip.endpoints.conf` from the snapshot, which decrypts
  them with the installation key; the revision stores that file encrypted
  ([EXTENSIONS.md](EXTENSIONS.md) §4, [ADR 0014](adr/0014-installation-key.md)).
  The file on disk is `0640 veyra:asterisk`, readable by Asterisk only.

## 7. Development

```
export VEYRA_TELEPHONY_ENGINE=asterisk VEYRA_ASTERISK_CONFIG_DIR=/tmp/veyra-asterisk
mkdir -p /tmp/veyra-asterisk
veyra config generate --deploy && veyra deployer --once
```

With `VEYRA_TELEPHONY_ENGINE=none` the API reports "not configured" and
generation is refused (409 `not_available`). Tests use a fake adapter
(`backend/tests/fake_adapter.py`) that runs the real generator without an
engine.
