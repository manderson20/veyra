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

The installer replaces the package's sample `pjsip.conf`, `extensions.conf`
and `rtp.conf` with Veyra-managed stubs (the samples are backed up beside
them as `*.veyra-backup-<timestamp>`). Each stub only `#tryinclude`s the
generated files:

| Stub in `/etc/asterisk/` | Generated file in `/etc/asterisk/veyra/` | Content | Reload |
|---|---|---|---|
| `pjsip.conf` | `pjsip.transports.conf` | UDP, TCP and optional TLS transports from the SIP settings, NAT addresses, local networks | `res_pjsip.so` |
| `pjsip.conf` | `pjsip.endpoints.conf` | Endpoint, auth and AOR templates; one endpoint per extension (Milestone 4). **Sensitive** when it contains SIP secrets: never shown in diffs | `res_pjsip.so` |
| `extensions.conf` | `extensions.conf` | `[veyra-features]` (`*43` echo test, `*60` speaking clock), `[veyra-internal]` (extensions, invalid-number handling), `[veyra-from-trunk]` (refuses calls until inbound routing exists, Milestone 6) | `pbx_config.so` |
| `rtp.conf` | `rtp.conf` | RTP port range, strict RTP | `res_rtp_asterisk.so` |

`/etc/asterisk/veyra` is `2750 veyra:asterisk`: the deployer (user `veyra`)
writes, Asterisk (group `asterisk`) reads, files are `0640`. `verify.sh`
checks the directory, the stubs and the deployer service.

`ari.conf`, `http.conf` and `manager.conf` are still installed by the
installer, not generated: they hold the ARI credential and never change
between deployments.

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
```

* A revision stores its files in `config_revisions.artifacts`, the content
  hash, the parent (the revision that was deployed when it was generated),
  who created it and, after deployment, a short log in `validation_errors`.
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
counts from `/channels`.

## 6. Security notes

* ARI stays on loopback with a generated credential; the adapter refuses
  any other URL.
* The deployer unit is sandboxed like the API (`ProtectSystem=strict`) with
  exactly one extra writable path, `/etc/asterisk/veyra`.
* Every value that reaches a generated file is validated against an
  allow-list pattern (section names, numbers, display names, addresses);
  newlines, brackets and semicolons cannot be injected.
* SIP secrets in `pjsip.endpoints.conf` (from Milestone 4) are stored in the
  revision artifacts in the database. Encrypting artifacts with the
  installation key is part of Milestone 4's secret handling.

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
