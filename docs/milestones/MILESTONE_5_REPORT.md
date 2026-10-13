# Milestone 5: Completion Report

**Milestone:** 5 — SIP registration and internal calling (live registrations, active calls, click-to-dial API, deploy mode)
**Date:** 2026-10-12 to 2026-10-13
**Branch:** `milestone-5` (pushed to `manderson20/veyra`; merged to `main`)
**Version:** 0.6.0
**Status:** Complete. Installed on veyra-dev1 (release `af1d3443a9`, revision 5) and verified from the server with a software phone (§3). Approved by the project owner on 2026-10-13 (merged to `main`). The owner's checks with a real desk phone on dev1 are still to come and will be appended to §3 as an addendum.

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

## 3. Testing (veyra-dev1, 2026-10-12/13, final tree)

| Suite | Result |
|---|---|
| Backend ruff (lint and format) | Clean |
| Backend mypy | No issues (84 files) |
| Backend pytest against PostgreSQL 18.6 | **200 passed** (7 new: channel parsing helpers; registration in responses; scoped active calls; click-to-dial permissions, validation, failures and audit; deploy-when-idle wait, deploy after calls end, timeout, `now` ignores calls; CLI `--when-idle`; feature codes not shadowed by the catch-all) |
| `alembic check` | No drift |
| Frontend lint / typecheck / vitest | Clean / clean / **22 passed** |
| Frontend `npm run build` | Passed; `/calls` exported |
| **Owner's `upgrade.sh` to this milestone on dev1 (2026-10-13 09:18 UTC)** | Passed: backups taken, release `0.6.0-dev-2b0e5a2ffb` activated, migration 0005 applied, Asterisk left running (no managed file changed), all verify checks OK, 0.1.0 release pruned. |
| **Registration (software phone, `tools/fakephone.py`, on dev1, 09:27 UTC)** | Passed: REGISTER with digest auth accepted; after the first qualify ping the contact is `Avail`, ARI reports the endpoint `online` and the adapter returns `registered=True`. Until that ping (up to 60 s) the badge reads unregistered (§5). |
| **Click-to-dial through the production adapter (09:28 UTC)** | Passed: `adapter.originate(<endpoint>, "*43", context=veyra-internal)` rang the phone (INVITE with caller ID `*43`), the phone answered after 3 s, then the dialplan ran. Active calls showed the channel as `Ringing` (1 s, 3 s) then `Up` (6 s) with the owning endpoint, and empty after hangup. |
| **Deploy when idle during a call (09:29–09:30 UTC)** | Passed: with a call held `Up`, `veyra config deploy 4 --when-idle` left revision 4 `deploying`; the deployer logged "waits for 1 active call(s) to end (0:29:58 left)"; hanging up over ARI made it deploy within seconds (audit `telephony.config_deploy` by deployer, revision 4 `deployed`). |
| **Dialplan: feature codes from a phone** | **Failed, fixed.** The `*43` call hit `veyra-internal`'s catch-all ("no such extension", `pbx-invalid`, hangup after 4 s) because Asterisk matches a context's own patterns before its includes. The catch-all moved to `veyra-invalid`, included after `veyra-features`; regression test added. **Verified live on dev1** after the owner's second upgrade (09:40 UTC, release `af1d3443a9`) and `veyra config generate --deploy` (revision 5, `extensions.conf` changed): a `*43` click-to-dial call now runs `Playback(demo-echotest)` in `*43@veyra-internal` and stays Up until hung up. |
| **A real desk phone registered against dev1, shown as Registered** | *Pending the owner (on site later on 2026-10-13)* |
| **Internal call between two extensions under Active Calls** | *Pending the owner (needs a second extension and phone)* |
| **"Call from this phone" in the browser: desk phone rings, then dials** | *Pending the owner* |
| **Deploy-when-idle from the top bar: waiting badge, deployment after hangup** | *Pending the owner (CLI path verified above)* |

## 4. Not verified

* The rows in §3 marked pending: a real handset, a second extension, and the
  browser side of click-to-dial and deploy-when-idle. The engine paths behind
  them were exercised remotely with `tools/fakephone.py` (§3) and the API
  paths are covered by tests with a fake engine.
* The waiting badge in the top bar was not seen live (the CLI path and the
  deployer log were); `pending_wait` is unit-tested.
* Registration details beyond on/off (contact address, user agent) are not
  exposed by ARI's endpoint resource; they would need AMI or the console.

## 5. Known limitations

* Click-to-dial reaches internal numbers and feature codes only until SIP
  trunks exist (Milestone 6).
* "When idle" deploys anyway after the timeout. Owner decision (2026-10-13):
  keep the 30-minute default; `VEYRA_DEPLOY_IDLE_TIMEOUT_MINUTES` stays
  configurable.
* Registration and call data are polled (15 s / 5 s), not pushed; ARI
  events over a WebSocket are a later refinement.
* Active calls cannot be hung up from the interface yet.
* A phone that has just registered shows as unregistered until the engine's
  first qualify ping (`qualify_frequency` 60 s): ARI's endpoint state follows
  contact reachability, not the REGISTER. A later refinement could read
  contacts directly or subscribe to ARI events.
* The fix for the shadowed feature codes changes the generated dialplan only;
  an installed server needs one generated and deployed revision to pick it
  up (`sudo veyra config generate --deploy`).

## 6. Open items

* Dev1 verification with a real phone (§3). Dev1 already runs the tree with
  the dialplan fix (revision 5 deployed).
* veyra-dev2 is not provisioned (deferred).

## 7. Proposed Milestone 6 (approved 2026-10-13)

SIP trunks and routing: trunk objects (registration and IP-authenticated),
trunk status, DIDs and inbound routing to extensions, outbound routing
with dial patterns and trunk selection, time conditions, loop detection,
and emergency-number handling notes; generated `pjsip` trunk sections and
the `veyra-from-trunk` and outbound contexts.

## 8. Owner decisions (2026-10-13)

* Milestone 5 approved; version 0.6.0; `main` fast-forwarded to this branch.
* The "when idle" deployment keeps the 30-minute default timeout (§5).
* Milestone 6 as proposed in §7 approved and started on branch `milestone-6`
  (version 0.7.0-dev).
* Owner request: **call pickup groups** (pick up a call ringing on another
  phone from your own) added to the roadmap under Milestone 8 with ring
  groups and queues.
