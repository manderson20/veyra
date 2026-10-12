# Milestone 5: Completion Report (draft)

**Milestone:** 5 — SIP registration and internal calling (live registrations, active calls, click-to-dial API, deploy mode)
**Date:** 2026-10-12 (in progress)
**Branch:** `milestone-5` (pushed to `manderson20/veyra`; not merged to `main`)
**Version:** 0.6.0-dev
**Status:** Software complete and tested. The live part needs the owner: a phone registered against dev1, an internal call between two extensions, a click-to-dial call, and a "deploy when idle" while a call is up (§3, §4).

## 1. Scope (approved 2026-10-12)

Per the Milestone 4b report §7: live registration status per extension,
active calls view, first phone registered and an internal call between two
extensions on dev1, the click-to-dial API (originate from a user's
extension), and the deploy-mode drop-down on the Deploy changes button.

## 2. Results

| Task | Result | Where |
|---|---|---|
| Registration status | Done. Extension responses carry `registration: {registered, channels}` from the engine's endpoint status (one engine call per request); badges in the list and on the page, refreshed every 15 s; null when the engine cannot report. | `backend/veyra/api/v1/extensions.py`, `frontend/src/app/(app)/extensions/` |
| Active calls | Done. `GET /calls` lists channels with the owning extension and real durations (parsed from the channel creation time), scoped to the caller's organizations; platform administrators see every channel. Telephony → Active Calls page refreshing every 5 s. New permission `calls.read`. | `backend/veyra/api/v1/calls.py`, `telephony/asterisk/adapter.py`, `frontend/src/app/(app)/calls/page.tsx` |
| Click-to-dial API | Done. `POST /calls/originate {extension_id, number}`: ARI `POST /channels` rings `PJSIP/<endpoint>` and, when answered, runs the dialplan at the number in `veyra-internal`; the phone's display shows the dialled number as caller ID. Own extensions with `calls.originate` (every role), any managed extension with `extensions.write`; refuses disabled extensions, the phone's own number, letters, a stopped engine; audited with from/to. "Call from this phone" dialog on the extension page. | `backend/veyra/api/v1/calls.py`, `telephony/asterisk/ari.py`, `frontend/src/components/extensions/ClickToDial.tsx` |
| Deploy mode | Done. `now` (default) or `when_idle` on apply and deploy, `veyra config deploy --when-idle`; the deployer holds a when-idle revision while the engine reports active calls, logs the wait, and after `VEYRA_DEPLOY_IDLE_TIMEOUT_MINUTES` (30) deploys anyway with a note in the revision log. Split button with a drop-down in the top bar; "Waiting for N calls to end" badge while held. Migration `0005`. | `backend/veyra/configmgmt/service.py`, `api/v1/telephony.py`, `frontend/src/components/shell/ApplyChanges.tsx` |
| Documentation | Telephony engine, extensions, API, schema and changelog updated. | `docs/` |

## 3. Testing (veyra-dev1, 2026-10-12, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (85 files) |
| Backend pytest against PostgreSQL 18.6 | **199 passed** (6 new: channel parsing helpers; registration in responses; scoped active calls; click-to-dial permissions, validation, failures and audit; deploy-when-idle wait, deploy after calls end, timeout, `now` ignores calls; CLI `--when-idle`) |
| `alembic check` | No drift |
| Frontend lint / typecheck / vitest | Clean / clean / **22 passed** |
| Frontend `npm run build` | Passed; `/calls` exported |
| **Owner's `upgrade.sh` to this milestone on dev1** | *Pending* |
| **A real phone registered against dev1 (extension 22214 or a second one), shown as Registered** | *Pending the owner* |
| **Internal call between two extensions, visible under Active Calls with a running duration** | *Pending the owner (needs two phones or a softphone)* |
| **Click-to-dial from the extension page: the desk phone rings, then dials** | *Pending the owner* |
| **Deploy when idle while a call is up: top bar shows the wait, deployment follows when the call ends** | *Pending the owner* |

## 4. Not verified

* Everything in §3 marked pending: no phone or softphone exists on the
  server. The API paths are covered by tests with a fake engine.
* Registration details beyond on/off (contact address, user agent) are not
  exposed by ARI's endpoint resource; they would need AMI or the console.

## 5. Known limitations

* Click-to-dial reaches internal numbers and feature codes only until SIP
  trunks exist (Milestone 6).
* "When idle" deploys anyway after the timeout (decision to confirm with the
  owner; the alternative is to keep waiting and show it).
* Registration and call data are polled (15 s / 5 s), not pushed; ARI
  events over a WebSocket are a later refinement.
* Active calls cannot be hung up from the interface yet.

## 6. Open items

* Dev1 verification with real phones (§3).
* veyra-dev2 is not provisioned (deferred).

## 7. Proposed Milestone 6 (for approval)

SIP trunks and routing: trunk objects (registration and IP-authenticated),
trunk status, DIDs and inbound routing to extensions, outbound routing
with dial patterns and trunk selection, time conditions, loop detection,
and emergency-number handling notes; generated `pjsip` trunk sections and
the `veyra-from-trunk` and outbound contexts.
