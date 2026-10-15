# API

The management API is versioned under `/api/v1`. The authoritative reference
is the generated OpenAPI document:

* `https://<server>/api/openapi.json`
* `https://<server>/api/docs` (interactive)

Conventions:

* **Authentication:** session cookie from `POST /api/v1/auth/login`. Mutations must send `X-CSRF-Token` with the value of the `veyra_csrf` cookie.
* **Errors:** RFC 9457 `application/problem+json`, with `code`, `detail`, `errors[] {field, message}` and `request_id` (also in the `X-Request-ID` header).
* **Lists:** `?limit=` (≤ 200) and `?offset=`, returning `{items, total, limit, offset}`; `?q=` search where supported.
* **Authorization:** enforced on every endpoint. Objects outside the caller's scope return 404.
* **Audit:** every mutation is recorded, including denied and failed attempts.
* **Forced password change:** while `must_change_password` is true in the session document, every route outside `/auth/` answers `403 password_change_required`.
* **Second factor pending:** after `POST /auth/login` answers 202, every route except the MFA challenge, verify, TOTP enrolment and logout answers `403 mfa_required` until `POST /auth/mfa/verify` (or enrolment) succeeds; the pre-authentication session expires after five minutes.
* **Fetch metadata:** a mutation whose `Sec-Fetch-Site` header says `cross-site` or `same-site` is refused with `403 cross_site_request` before any handler runs; requests without the header fall through to the CSRF token check.
* **Bearer tokens:** a request with `Authorization: Bearer vyc_…` is authenticated by the token alone ([ADR 0015](adr/0015-bearer-tokens.md)): cookies are ignored, the CSRF and fetch-metadata checks do not apply, and permissions are the intersection of the user's roles and the token's scopes (Companion tokens: `calls.originate`, `calls.read`, `directory.read`, own-account routes).

| Area | Paths |
|---|---|
| Auth | `/auth/login` (200 session, or 202 second factor pending), `/auth/logout`, `/auth/session`, `/auth/password`, `/auth/sessions[/{id}]`, `/auth/sessions/revoke-others`, `/auth/password-reset/check`, `/auth/password-reset` (the last two are public and rate limited) |
| Companion | `/auth/companion/login` (200 token, or 202 challenge), `/auth/companion/verify`, `/auth/companion/logout`, `/auth/tokens[/{id}]`, `/auth/tokens/revoke-all`; `/users/{id}/tokens` (administrators); bearer tokens per [ADR 0015](adr/0015-bearer-tokens.md) and [COMPANION.md](COMPANION.md) |
| Two-factor | `/auth/mfa/challenge`, `/auth/mfa/verify` (rate limited), `/auth/mfa/totp/{begin,confirm}`, `/auth/mfa/methods[/{id}/remove]`, `/auth/mfa/recovery-codes/regenerate`, `/auth/mfa/policy`; `/users/{id}/mfa/reset` (see [MFA_DESIGN.md](MFA_DESIGN.md)) |
| Setup | `/setup/status`, `/setup/initialize` |
| Directory | `/organizations[/{id}]`, `/users[/{id}]`, `/users/{id}/roles[/{assignment}]`, `/users/{id}/unlock`, `/users/{id}/password-reset-link`, `/users/{id}/sessions`, `/roles`, `/search` (organizations, users, extensions) |
| System | `/system/ping` (public), `/system/health`, `/system/info`, `/system/metrics/calls?range=1h\|6h\|24h\|7d` (channel and call history for the dashboard graphs, [INTERFACE_REWORK.md](INTERFACE_REWORK.md) §2), `/ha/status`, `/audit` |
| Modules | `/modules`, `/modules/ui-extensions`, `/modules/{id}`, `/modules/{id}/{install,enable,disable,update,uninstall}`, module routes under `/api/v1/ext/<prefix>/` |
| Updates | `/updates/policies[/{component}]`, `/updates/check`, `/updates/checks/latest`, `/updates/available`, `/updates/history` |
| Provisioning | `/provisioning/variables`, `/provisioning/models` (manufacturers and models of the catalog), `/provisioning/templates[/{key}[/preview,/export]]`, `/provisioning/templates/{validate,import}`, `PUT`/`DELETE /provisioning/templates/{key}` (local templates, editor), `/provisioning/templates/{key}/customize` (editable local child; a family also gets local model templates), `/provisioning/firmware[/{id}]` (multipart upload of vendor images; see [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §3.4, §7) |
| Devices | `/devices[/{id}]` (phones by MAC with profile, lines, key and value overrides, status from the request log, `problems`), `/devices/unregistered` (phones seen with a valid credential but not registered), `/devices/{id}/preview` (rendered files, secrets masked), `/devices/{id}/reprovision` (`check_config` or `reboot` via SIP NOTIFY), `/device-profiles[/{id}]` (template family or model plus values, line keys, paging memberships, firmware; `409 profile_in_use`), `/organizations/{id}/provisioning-credential[/rotate]` (enrollment credential, password shown once); see [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) |
| Paging zones | `/paging-zones[/{id}]` (speakers' multicast group plus the Poly group number; since 9c also a dialable `number` from the shared number space, `allowed` policy with `members`, `max_seconds`; `409 zone_in_use`, `409 poly_group_in_use`, `409 number_in_use`; permissions `paging.read`/`paging.write`; see [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §5, [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §2) |
| Pages | `/pages[/{id}]` (zones, live or recorded audio, number, pre-tone, repeat, priority, `allowed`/`members`, `problems`, `last_sent_at`), `POST /pages/{id}/send` (`paging.send`; starts a recorded page now, optional `audio_id`/`zones`/`repeat` overrides for integrations), `/pages/log` (what was sent, by whom); see [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §2 |
| Calendars | `/calendars[/{id}]` (iCal subscriptions; the address is stored encrypted, only scheme and host are shown), `POST /calendars/{id}/poll`, `/calendars/{id}/events` (next 48 h); permissions `bells.read`/`bells.write`; see [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §4 |
| Bell schedules | `/bell-schedules[/{id}]` (calendar → recorded page, title pattern, start/end trigger, tolerance, `next_rings`, `problems`), `/bell-schedules/{id}/rings` (history), `POST /bell-schedules/{id}/ring` (test) |
| Sites | `/sites[/{id}]` (locations of an organization with time zone, address and the default emergency caller ID; `409 site_in_use`; permissions `organizations.read`/`organizations.write`) |
| Telephony | `/telephony/engine`, `/telephony/settings`, `/telephony/numbering`, `/telephony/apply` and `/telephony/revisions/{id}/deploy` (both take `{"mode": "now"\|"when_idle"}`), `/telephony/revisions[/{id}]`, `/telephony/revisions/{id}/discard` (see [TELEPHONY_ENGINE.md](TELEPHONY_ENGINE.md)) |
| Extensions | `/extensions[/{id}]` (with the extension's `ring_groups`, `queues` and `pickup_groups`, and `emergency_caller_id_number`), `/extensions/next-number` (free across extensions, ring groups and queues), `/extensions/{id}/sip-credentials[/rotate]` (see [EXTENSIONS.md](EXTENSIONS.md)) |
| Calls | `/calls` (active channels), `/calls/originate` (click-to-dial) |
| Me | `/me/extensions` (own extensions with registration), `/me/preferences` (Companion speed dials and settings), `/me/voicemail` and `/me/voicemail/{id}/pin` (own voicemail boxes and PIN change) |
| Directory | `/directory?q=` (extensions and people in the caller's organizations; permission `directory.read`, every role) |
| Events | `/events/ticket` (one-time ticket), WebSocket `/events/calls?ticket=` (call events for the caller's own extensions) |
| Trunks | `/trunks[/{id}]` (SIP trunks with live status; see [TRUNKS_ROUTING.md](TRUNKS_ROUTING.md)) |
| Routing | `/routing/inbound[/{id}]` (DIDs; destinations are an extension, a voicemail box, an IVR menu, a ring group or a queue), `/routing/outbound[/{id}]`, `/routing/outbound/order`, `/routing/time-conditions[/{id}]` |
| Voicemail | `/voicemail[/{id}]` (one box per extension, or a shared inbox with its own number, name and member phones; the PIN is returned once on creation), `/voicemail/{id}/reset-pin` (see [VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §3) |
| Prompts | `/prompts[/{id}]` (multipart WAV upload, converted to 8 kHz mono), `/prompts/{id}/audio` (GET streams, PUT replaces), `/prompts/recordings[/{file}/audio\|/adopt]` (recordings made from phones with `*95`; see [VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §4) |
| Call history | `/calls/history` (`?from=&to=&organization_id=&direction=&outcome=&q=&extension_id=&min_seconds=&recorded=`), `/calls/history/{id}` (legs, `recording_id`), `/calls/history/export.csv` (`calls.history.export`), `/me/calls`; see [REPORTING.md](REPORTING.md) §3 |
| Recording | `/recording-policies[/{id}]` (`recording_policies.read/write`; changes need a deployment), `/recordings` (`recordings.read` for an organization, `recordings.read_own` for one's own calls), `/recordings/{id}/audio` (`?download=true`; audited), `/recordings/{id}/hold`, `DELETE /recordings/{id}` (`recordings.manage`); §4 |
| Reports | `/reports/calls`, `/reports/queues` (`?organization_id=&from=&to=`; `reports.read`); §5. Report builder ([REPORT_BUILDER.md](REPORT_BUILDER.md)): `POST /reports/run` and `/reports/run.csv` (a definition: `group_by`, `measures`, `filters`, `period`, `show_as`, `sort_by`, `sort_desc`, `limit`, `sl_seconds`), `/reports/options`, `/saved-reports[/{id}]` (`reports.write` to save, share and schedule), `/saved-reports/{id}/run`, `/run.csv`, `/send` |
| Monitoring | `/alerts` (`?state=open|raised|cleared|all`), `/alert-rules[/{key}]` (`alerts.write`), `/metrics` (Prometheus text; `metrics.read`); §6 |
| Firewall | `/firewall/status`, `/firewall/settings` (PUT; limiting a service to the allow list must be confirmed with `POST /firewall/confirm` within 60 s), `/firewall/rules[/{id}]` (allow and block; automatic entries `409 automatic_rule`), `/firewall/bans` (`?active=`, `/{id}/lift`, `/{id}/block`), `/firewall/events` (`?address=&source=&since=&would_ban=`), `/firewall/feeds[/{id}]` (`/{id}/refresh`); `409 firewall_self_block` refuses changes that would cut off the caller; permissions `firewall.read`/`firewall.write` (platform administrators); see [FIREWALL_TRUST.md](FIREWALL_TRUST.md) §7. Devices gain `https_seen_at`, `allow_bootstrap` and `POST /devices/{id}/allow-bootstrap`; organizations `bootstrap_includes_credential` |
| Hold music | `/hold-music[/{id}]` (sets of library recordings; assigned with `moh_class_id` on organizations, queues and ring groups; see [PAGING_RECORDINGS.md](PAGING_RECORDINGS.md) §3.2) |
| IVR | `/ivr[/{id}]` (menus with key map, fallbacks and `problems`; see [VOICEMAIL_IVR.md](VOICEMAIL_IVR.md) §5) |
| Ring groups | `/ring-groups[/{id}]` (number, ordered members, strategy, failover destination, `problems`, `in_use_by`; `409 ring_group_in_use`; see [RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §2) |
| Queues | `/queues[/{id}]` (number, agents with penalties, strategy, announcements, limits, failover; `409 queue_in_use`; see [RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §3) |
| Pickup groups | `/pickup-groups[/{id}]` (members that may answer each other's calls with `*8`; see [RING_GROUPS_QUEUES.md](RING_GROUPS_QUEUES.md) §4) |
| Email delivery | `/system/smtp` (GET/PUT, platform settings permission; password write-only), `/system/smtp/test` (sends a test message to the caller) |

Outside `/api/v1`: `GET`/`PUT /provisioning/<file>` is the phone-facing provisioning server (HTTP Basic authentication with the enrollment or the device credential; [DEVICE_PROVISIONING.md](DEVICE_PROVISIONING.md) §3), and `/provisioning/firmware/<id>/<file>` is served by NGINX.

Planned (later milestones): paging from Veyra, call history and others.
