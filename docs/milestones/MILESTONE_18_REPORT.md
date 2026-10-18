# Milestone 18 Report — Diagnostics and extension call features

Branch `milestone-18` (from `main` at 0.23.1). Design:
[CALL_FEATURES.md](../CALL_FEATURES.md). Status: **built 2026-10-18, awaiting
live checks and approval** (becomes 0.24.0). Issues: #73, #74, #17, #14, #15,
#16, #18, #23, #24, #30, #45 under milestone "M18 — Diagnostics and extension
call features"; progress comments on each.

## 1. Scope (roadmap row 18)

The first half of the FreePBX gap work ([FREEPBX_GAP_ANALYSIS.md](../FREEPBX_GAP_ANALYSIS.md)
§4 item 1): diagnostics the owner asked for (where phones register from,
packet capture, a diagnostics page), then the extension call features
(outbound caller ID, Do Not Disturb, call forwarding, find me / follow me,
intercom, direct transfer to voicemail, voicemail operator, class of
service, a feature-code page) and trunk registration state.

## 2. Results

* **Registrations** (#73, §2.1): Telephony → Registrations lists every
  registered phone with the address the registration came from and the
  address the phone reports (NAT when they differ), user agent, transport,
  reachability and expiry, from the PJSIP contact store and
  `pjsip show contacts` joined by hash; `GET /telephony/registrations`;
  Extensions gains "Registers from"; `registration.changed` webhooks carry
  both addresses. With `rewrite_contact` the stored URI is the source and
  `x-ast-orig-host` the phone's own address (found live).
* **Packet captures** (#74, §2.2): System → Diagnostics starts a tcpdump
  capture of all SIP, one extension (by the address its phone registers
  from), a trunk or an address, optionally RTP, for a chosen time and size;
  lists, stops, downloads (audited, one-time privacy notice) and deletes
  captures; a SIP summary groups messages by dialog. Root unit
  `veyra-capture@<id>` through polkit, a runner that rebuilds the filter from
  validated fields and enforces the limits, retention class "captures",
  `sudo veyra capture start|stop|list|delete`, `verify.sh` `capture-unit`.
* **Diagnostics page** (§2.3): log tails (messages, security, queue) with a
  filter and a fixed list of read-only engine queries, every read and query
  audited.
* **Trunk registration state** (#45): trunk status and the `trunk_down`
  alert reflect the engine's registration (registered, rejected,
  registering, unregistered) besides reachability; the Registrations page
  lists the trunks.
* **Outbound caller ID per extension** (#17, §3.5): number and name sent to
  the carrier, validated against the organization's DIDs or an allow list
  unless the caller holds `routing.write`; routes can force their number;
  precedence emergency → forced route → extension → route → trunk default;
  migration 0033.
* **Feature codes** (§3.1): Telephony → Feature Codes with FreePBX-style
  defaults, changeable or disabled, stored as overrides; the generator
  refuses collisions.
* **Do Not Disturb** (#14, §3.2): extension page switch and `*78/*79/*76`,
  effective at once (the engine keeps a copy in its database, the worker
  keeps it in step, a UserEvent brings the phone's change back), lamp hint
  `*76<ext>`; `extension_states` table, migration 0034.
* **Call forwarding** (#15, §3.3): always, on busy, when unanswered, the
  extension's ring time; from the page and `*72/*73`, `*90/*91`, `*52/*53`;
  outside targets leave through the organization's outbound routes with the
  extension's outbound caller ID; three chained forwards at most.
* **Find me / follow me** (#16, §3.4): legs together or in turn, desk phone
  first, press-1 confirmation for outside legs, caller ID mode, no-answer
  destination; `*21`; migration 0035. Ring groups ring outside numbers too
  (migration 0039).
* **Intercom** (#18, §3.6): `*80<ext>` with the auto-answer headers; allow
  or deny per extension with an organization default; migration 0036.
* **Direct transfer to voicemail and the operator** (#23, #24, §3.7):
  `*<ext>` reaches the greeting (exact entries per box); a box's operator
  extension on 0, `*` opens the box; migration 0037.
* **Classes of service** (#30, §3.8): allowed outbound routes and feature
  codes, outside forwards and follow-me, intercom, a cap on simultaneous
  outside calls; static dialplan guards on `VEYRA_COS`; a phone without a
  class may do everything; emergency routes always work; migration 0038.

Deviations from the design are noted in CALL_FEATURES.md under each
section ("Built …"): feature codes as a settings document rather than a
table; extension state reconciled by the worker instead of seeded at
deployment; class-of-service guards generated statically; the
`cos.denied` call-history counter, `allow_from_group`, the voicemail
locater keys and the phone-side auto-answer template option are deferred
(Milestones 20 and 21).

## 3. Testing (final tree, 2026-10-18)

Backend: full suite green on every commit (526 tests at 26c13ef; new
files `test_registrations.py`, `test_captures.py`, `test_features.py`).
Frontend: 51 vitest tests, typecheck, lint and build clean (70 CSP hashes).
Installer: `test_lib.sh` 70 tests (capture unit, polkit cases). mypy
clean.

### Live checks on dev1 (2026-10-17/18)

Done: registrations with a test phone (contact vs source address,
truncated listing joined by hash); packet capture end to end (start via
polkit, SIP summary of a real registration exchange, stop, download,
delete, console list, audit trail; a capture started within the first few
seconds misses traffic, the page says so); outbound caller ID endpoint
variables; Do Not Disturb through the API (AstDB key, lamp state, list)
and deployment 71 carrying the codes; forwards through the API (keys and
lamp). The owner installed every build on dev1 and confirmed the deploy
button fix.

Done after the owner installed cdcac7e (schema 0039): follow-me
configured on 22214 (sequential, desk first, a member extension and an
outside number, confirmation, no-answer destination) and switched on
through the state (engine key `fmfm`), intercom denied on 22215, an
operator on 22215's box, a class "Classroom" assigned to 22215, and a ring
group with an outside number; the generated configuration carried
`VEYRA_COS`, the follow-me branch with the `U(veyra-fm-confirm^s)`
option and the `Local/…@veyra-fm-out` leg, the `*2122214` lamp hint, the
`*22215` direct-voicemail entry, the intercom context with 22214 allowed
and 22215 refused, the forward guard (`LEN(${VEYRA_CF}) > 5`) and
`cosdenied` blocks, the ring group's outside leg, and the box's
`operator=yes|exitcontext=veyra-vmx-22215` with its exit context. The
diagnostics log tail (messages, security with a filter) and an engine
query (`core show uptime`) answered; a shell-like argument was refused
with 422. The call-limit guard renders only inside outbound route blocks
and dev1 has no outbound routes, so it was not seen live.

Pending: a deployment of this configuration and the phone-side codes
dialled from a real phone (`*76`, `*72<number>`, `*21`, `*80<ext>`,
`*<ext>`, 0 during a greeting); trunk registration state (dev1 has no
registration trunk).

## 4. Not verified

Carrier behaviour on the outbound caller ID and on forwarded or follow-me
legs (dev1 has no trunk); the press-1 confirmation against a real mobile;
auto-answer on Poly and Yealink phones (the template option is Milestone
21); multi-organization isolation of the new contexts beyond the automated
checks.

## 5. Known limitations

A capture started while the unit is loading misses the first seconds;
class-of-service refusals are not counted in the call history; the
intercom header is sent but phones honour it only when configured; the
`vm_direct` code `*` relies on exact entries, so a new box needs a
deployment before `*<ext>` works for it; the built-in organization and
site administrator roles hold `routing.write` and so bypass the DID check
for outbound caller ID.

## 6. Open items

Owner upgrade and live checks (§3); the owner's decision on binding the
built-in administrator roles to the DID check; Dependabot alert for
`braces` (dev-only, no fix upstream yet).

## 7. Next milestone

Milestone 19, call-flow features (#19–#22, #25–#29): parking, conferences,
announcements, directory, call flow toggle, time-condition override,
blacklist, queue agents, queue break-out. New owner requirements filed for
later milestones: #75 (user portal: user-set phone keys with
administrator-locked keys, Milestone 20) and #76 (provisioning variables
control plane, Milestone 21).

## 8. Owner decisions

None blocking. Approval of this milestone bumps the version to 0.24.0 and
turns the changelog's Unreleased section into the release entry.
