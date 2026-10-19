# Milestone 6: Completion Report

**Milestone:** 6 — SIP trunks and routing (trunks, DIDs and inbound routing, outbound routing with dial patterns and trunk selection, time conditions, loop detection, emergency-number handling notes)
**Date:** 2026-10-13
**Branch:** `milestone-6` (pushed to `manderson20/veyra`; merged to `main`)
**Version:** 0.7.0
**Status:** Software complete and verified on veyra-dev1 with a software carrier (§3). Approved by the project owner on 2026-10-13 (merged to `main`); a real carrier trunk has not been tested yet (§4).

## 1. Scope (approved 2026-10-13)

Per the Milestone 5 report §7: trunk objects (registration and
IP-authenticated), trunk status, DIDs and inbound routing to extensions,
outbound routing with dial patterns and trunk selection, time conditions,
loop detection, emergency-number handling notes; generated `pjsip` trunk
sections and the `veyra-from-trunk` and outbound contexts. Design and
reference: [TRUNKS_ROUTING.md](../TRUNKS_ROUTING.md).

## 2. Results

| Task | Result | Where |
|---|---|---|
| Trunks | Done. `sip_trunks` with registration or IP authentication, write-only password encrypted with the installation key (purpose `trunk.sip_secret:<id>`), match addresses, codecs, channel cap, caller-ID header, DTMF, qualify and registration intervals. `GET/POST /trunks`, `GET/PATCH/DELETE /trunks/{id}`; `409 trunk_in_use` lists the routes that reference it. Status (`online`/`offline`/`unknown`) from the engine's endpoint state. Telephony → SIP Trunks list and detail pages. | `backend/veyra/api/v1/trunks.py`, `core/models/routing.py`, `frontend/src/app/(app)/trunks/` |
| Generated trunk configuration | Done. New managed file `pjsip.trunks.conf` (sensitive when it carries a password): endpoint (`context=veyra-from-trunk-<slug>`, `set_var=VEYRA_TRUNK`), AOR with the carrier contact and qualify, `identify` with the match addresses, and in registration mode `auth` and `registration` sections. The installer's `pjsip.conf` stub includes the file. | `telephony/asterisk/generator.py` (`_trunks`), `installer/templates/asterisk/pjsip.conf` |
| Inbound routing | Done. `inbound_routes`: DID as the carrier sends it plus a canonical form (ten digits for North American numbers), optional trunk restriction, extension destination, time condition with an after-hours destination, caller-ID name prefix, `any` catch-all per trunk or shared. Uniqueness per trunk restriction (NULLs not distinct). Dialplan: shared `veyra-from-trunk`, per-trunk `veyra-from-trunk-<slug>` including the shared DIDs and a per-trunk fallback; `1`/`+1` aliases; deleted destinations leave the route flagged, not broken. Telephony → Inbound Routes. | `api/v1/routing.py`, `generator.py` (`_inbound_contexts`), `frontend/src/app/(app)/routing/inbound/` |
| Outbound routing | Done. `outbound_routes` with `{prefix, match, prepend}` patterns, an ordered trunk list (`outbound_route_trunks`), per-route caller ID, evaluation order (`PUT /routing/outbound/order`), emergency flag. Dialplan: `veyra-outbound` includes one `veyra-out-<slug>` per route (emergency first); each pattern strips the prefix, prepends, then tries the trunks in order with failover on CHANUNAVAIL or CONGESTION, trunk default caller ID unless the route overrides, `GROUP_COUNT` channel caps, "all circuits busy" at the end. `veyra-internal` includes `veyra-outbound` after the feature codes and before the catch-all. `GET /routing/outbound` returns `warnings`. Telephony → Outbound Routes with reordering. | `api/v1/routing.py`, `generator.py` (`_outbound_contexts`), `frontend/src/app/(app)/routing/outbound/` |
| Time conditions | Done. `time_conditions` per organization: time zone (organization default), weekly ranges, yearly holidays; `open_now` computed server-side; `409 time_condition_in_use` on delete. Rendered as `GotoIfTime(times,days,*,*,tz?label)` per contiguous weekday span and per holiday. Telephony → Time Conditions. | `api/v1/routing.py`, `telephony/routing.py`, `frontend/src/app/(app)/routing/time-conditions/` |
| Loop detection and limits | Done. Trunk calls set `VEYRA_HOPS=1`; non-emergency outbound routes refuse them (`Hangup(21)`); trunk channel caps via `GROUP()`/`GROUP_COUNT`; the generator refuses duplicate slugs, DIDs routed twice in one scope and unsafe pattern characters. | `generator.py` |
| Emergency handling | Routing part done (§7 of the design): emergency routes evaluated first, direct dialling of `911`/`933`, route caller ID (ELIN), 120 s timeout, caps and loop check ignored, WARNING log line, interface warning when no emergency route exists. Notification, dispatchable location and callback remain for Milestone 17; status recorded in `docs/EMERGENCY_CALLING.md`. | `generator.py`, `docs/EMERGENCY_CALLING.md` |
| Permissions and audit | `trunks.read` (organization administrators, technicians), `trunks.write` (platform), `routing.read`, `routing.write`; audit actions `trunk.*`, `inbound_route.*`, `outbound_route.*` (including `reorder`), `time_condition.*`; every write raises the Deploy changes flag. | `core/security/permissions.py` |
| Database | Migration `0006`: five tables; `alembic check` clean. | `migrations/versions/0006_trunks_routing.py`, `docs/DATABASE_SCHEMA.md` |
| Documentation | `TRUNKS_ROUTING.md` (design and reference), API, schema, engine and emergency docs, changelog. | `docs/` |

## 3. Testing (veyra-dev1, 2026-10-13, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (88 files) |
| Backend pytest against PostgreSQL 18.6 | **229 passed** (29 new: trunk sections for both modes and their validation; outbound contexts with emergency ordering, failover, caps and loop check; pattern validation; inbound shared, restricted, alias, catch-all and time-condition rendering; duplicate DIDs; routing helpers and `is_open`; API CRUD, validation, uniqueness, in-use conflicts, organization scoping, ordering and warnings; apply + deploy writing `pjsip.trunks.conf` and the routing contexts with the password absent from readable artifacts) |
| `alembic check` | No drift (migration `0006`) |
| Frontend lint / typecheck / vitest | Clean / clean / **28 passed** (6 new: navigation order and gating, routing helpers) |
| Frontend `npm run build` | Passed; `/trunks`, `/trunks/view`, `/routing/inbound[/view]`, `/routing/outbound[/view]`, `/routing/time-conditions[/view]` exported |
| **Owner's `upgrade.sh` to this milestone on dev1 (11:12 UTC)** | Passed: release `0.7.0-dev-1f8ab5a1e6`, migration 0006, the new `pjsip.conf` stub installed and PJSIP reloaded, all verify checks OK. Revision 7 (first with the new file layout) deployed cleanly. |
| **Live on dev1: trunk, DID and route objects deployed (revision 8)** | Passed: an IP trunk `fakecarrier` (127.0.0.1:5082, match 127.0.0.1/32), DID `5735550100` → 22214 with a time condition and caller-ID prefix, and route `8XXXX` → trunk, created through the models and deployed; `pjsip show endpoint trunk-fakecarrier` shows the contact and identify match; `dialplan show` shows `veyra-from-trunk` with the DID and its `1`/`+1` aliases, the per-trunk context with both includes, the fallback, and `veyra-out-test-out`. |
| **Trunk status** | Passed: after the qualify ping the contact is `Avail`, ARI reports the endpoint online and the adapter returns `registered=True` for `trunk-fakecarrier` (shown as *Online*). |
| **Inbound call: software carrier → DID → extension (11:16 UTC)** | Passed: the carrier's INVITE to `5735550100` was identified as the trunk, ran the time condition (open), rang the software phone registered as 22214 with caller ID `"Main: 5735551234"`, was answered; Active Calls listed both channels (trunk leg attributed to `trunk-fakecarrier`, phone leg to the extension); the carrier's BYE ended both. |
| **Outbound call: click-to-dial 22214 → 81234 through the route (11:16 UTC)** | Passed: the phone rang and answered, the route stripped the prefix and dialled the carrier, which rang with caller ID `5735550100` (the trunk default) and answered; Active Calls showed both legs; hanging up over ARI ended the carrier leg. |
| **Clean-up** | Test objects removed, revision 9 deployed: no trunk endpoints or routing contexts remain. |

## 4. Not verified

* A real carrier registration (no carrier account is available to the
  project yet). The registration sections follow the Asterisk PJSIP
  reference; the first real trunk will be the test. IP identification,
  inbound and outbound calls were verified with a software carrier.
* TLS trunks (no certificate chain to a carrier available).
* The browser pages were not exercised by the owner yet (lint, type check,
  tests and build pass).

## 5. Known limitations

* Trunk *registration* state is not exposed by ARI; the status shows
  reachability from the qualify ping only (design §11). Reading
  `pjsip show registrations` through a read-only console channel is the
  proposed follow-up.
* Inbound destinations are extensions only until ring groups, IVRs and
  voicemail exist; outbound routes apply to every organization until
  Milestone 14.
* Holidays repeat yearly (`MM-DD`); `GotoIfTime` cannot express a year. *(Resolved in 0.27.1, #113.)*
* Emergency calling is **not certified** (`docs/EMERGENCY_CALLING.md`).
* Calls are identified as a trunk by source address first (Asterisk's
  default `endpoint_identifier_order`), so a phone that shares a trunk's
  address is treated as that trunk; this surfaced in the live test and was
  avoided by binding the test phone to another address. Real phones and
  carriers do not share addresses in normal deployments.
* Outbound calls carry the trunk default or route caller-ID *number*; the
  caller-ID *name* is left as the phone sent it.

## 6. Open items

* Owner's live checks with a real carrier when one is available, and a
  look at the four new pages in a browser.
* veyra-dev2 is not provisioned (deferred).

## 7. Proposed Milestone 6b (approved 2026-10-13)

**Veyra Companion** browser extension (owner request, roadmap row 6b):
Chrome/Edge first; sign in with Veyra credentials including the second
factor; click-to-dial any number from any page (the desk phone rings, then
the call is placed through the Milestone 5 API and the Milestone 6 routes);
directory lookup; incoming caller-ID pop-up (needs a server push channel:
ARI events relayed over a WebSocket or server-sent events, scoped to the
user's extensions); personal speed dials and quick buttons stored in the
user's Veyra profile. Backend additions: a per-user API token or session
flow usable from an extension, the event stream, and a `user_preferences`
store. Alternative order if preferred: Milestone 7 (voicemail and IVR) first.

## 8. Owner decisions (2026-10-13)

* Milestone 6 approved; version 0.7.0; `main` fast-forwarded to this branch.
* Milestone 6b (Veyra Companion) as proposed in §7 approved and started on
  branch `milestone-6b` (version 0.8.0-dev).
* The owner asked which carrier the test used: none; the live test used the
  project's software carrier (`tools/fakephone.py` in carrier mode), so the
  first real carrier remains an open verification item.
