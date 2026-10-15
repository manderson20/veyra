# Multi-Tenancy (Milestone 14)

Design for Milestone 14 (roadmap row 14, 0.20.0): telephony isolation
between organizations, the tests that prove it, and the switch that
activates multi-tenancy only after they pass.

## 0. Where Veyra stands

Every tenant-owned row already carries `organization_id`. The API filters
every list and every object by the caller's organizations, and answers 404
outside them (ARCHITECTURE.md §6). Endpoint names already carry the
organization (`<org slug>-<number>`).

**Calls are not isolated.** The generated configuration has one dialplan
context (`veyra-internal`), one voicemail context (`veyra`), one queue
namespace, one hold music namespace and one set of pickup group names. A
phone of organization A can dial organization B's extensions, queues and
voicemail. Today, a platform administrator can create a second organization
without any warning. Numbers are unique across the installation, which hides
part of the problem.

The installation row has `multi_tenancy_enabled`, which nothing reads yet.

## 1. Goals

1. Each organization gets its own **engine namespace**: contexts, voicemail
   context, queue names, hold music classes, pickup group names, page
   playback and recording paths. A phone reaches only its own
   organization's objects, plus what the installation shares on purpose:
   trunks through outbound routes, the "invalid number" context and the
   recording helper.
2. **Numbers are per organization.** Two organizations can both have
   extension 1001, ring group 600 and voicemail box 1001.
3. An **isolation verifier** reads the generated files and proves goal 1
   for every revision. A revision that lets one organization's context
   reach another organization's objects is refused.
4. **Activation**: a second active organization is possible only after a
   platform administrator turns on multi-tenancy, and turning it on runs
   the verifier first.
5. **No change for a single-organization installation.** Today's
   organization keeps today's names, so dev1's voicemail messages,
   queue statistics, call history and recordings stay where they are.

## 2. Engine namespace

New column `organizations.engine_namespace` (up to 16 characters of
`[a-z0-9]`, unique, set when the organization is created, never changed):

* **Migration:** the oldest existing organization gets the empty namespace
  `""`. Every other existing organization gets one derived from its slug
  (shortened, made unique).
* **New organizations** get a namespace derived from the slug. The empty
  namespace is never handed out again.

Every engine name is built by one function:

| Object | Empty namespace (today) | Namespace `acme` |
|---|---|---|
| Phone context | `veyra-internal` | `veyra_acme-internal` |
| Feature codes | `veyra-features` | `veyra_acme-features` |
| Paging / page playback | `veyra-paging`, `veyra-page-play` | `veyra_acme-paging`, `veyra_acme-page-play` |
| Outbound | `veyra-outbound`, `veyra-out-<route>` | `veyra_acme-outbound`, `veyra-out-<route>` (shared, §4) |
| IVR / ring group / queue contexts | `veyra-ivr-<slug>`, `veyra-rg-<slug>`, `veyra-queue-<slug>` | `veyra_acme-ivr-<slug>`, `veyra_acme-rg-<slug>`, `veyra_acme-queue-<slug>` |
| Voicemail context | `veyra` | `veyra_acme` |
| Queue name (`queues.conf`) | `veyra-<slug>` | `veyra_acme-<slug>` |
| Hold music class / folder | `veyra-<slug>`, `<moh>/<slug>` | `veyra_acme-<slug>`, `<moh>/acme_<slug>` |
| Pickup group names | `<slug>` | `acme_<slug>` |

Today's names never contain `_`, and a namespace never contains `-`, so a
name of one organization can never equal a name of another, whatever the
slugs. Ring group, queue, menu and hold music slugs stay unique across the
installation (a second organization's "Office" gets `office-2`); numbers do
not (§3).

Endpoint names stay `<org slug>-<number>`; they are already unique. The
call history and queue reports read the queue and ring group from these
names and learn the namespace prefix (REPORT_BUILDER.md §1); queue log
rows name a namespaced queue `<ns>_<slug>`. Prompts,
recordings and hold music files already live under per-organization
folders.

## 3. Numbers per organization

* Extensions: the unique key (`organization_id`, `number`) already exists.
  The installation-wide check (an advisory lock in the API) becomes
  per-organization.
* Ring groups, queues, shared voicemail inboxes, paging zones and pages
  have globally unique `number` columns. Migration `0027` replaces them
  with (`organization_id`, `number`). The shared number space
  (EXTENSIONS.md §3, `/extensions/next-number`) is computed per
  organization.
* The **numbering plan** (length and range) stays installation-wide.
* **DIDs stay unique across the installation**: a call from a trunk must
  land in exactly one organization.

## 4. Shared parts

* **Trunks** belong to the installation. Platform administrators manage
  them, as today.
* **Outbound routes** get an optional `organization_id`. Empty means every
  organization (today's behaviour); set means that organization only. Each
  organization's `veyra-<ns>-outbound` includes the routes that apply to
  it, in the global order. Emergency routes stay shared.
* **Inbound routes** already belong to an organization. The shared
  from-trunk context sends each DID to its organization's contexts.
* **Feature codes** (`*43`, `*60`, `*95`, `*97`, `*98`, `*8`, `**<ext>`)
  are generated per organization. `*98` asks for a box in the caller's own
  voicemail context only, and `**<ext>` reaches only the caller's own
  phones, so the `VEYRA_ORG` comparison is no longer needed (it stays as
  defence in depth).
* **Paging**: zones and Poly group numbers are per organization (Poly's
  limit of 24 groups applies per organization). Multicast addresses are
  network-wide. Two organizations using the same address on the same
  network would hear each other, so saving a zone with another
  organization's address gives a warning.

## 5. The isolation verifier

`veyra/telephony/asterisk/isolation.py` reads the generated
`extensions.conf`, `pjsip.endpoints.conf`, `voicemail.conf` and
`queues.conf`. It knows which namespace owns each context, endpoint,
mailbox context and queue, and checks:

1. every phone endpoint's `context=` is its own organization's phone
   context, and its `mailboxes=` are in its own voicemail context;
2. from each organization's contexts, every `include`, `Goto`, `Gosub`,
   `GotoIf` and `GosubIf` target, every `Dial(PJSIP/…)`, `PickupChan`,
   `Queue`, `VoiceMail`, `VoiceMailMain` and `Page` argument names only
   that organization's objects, a trunk endpoint, or a shared context
   (`veyra-invalid`, `veyra-record`, `veyra-out-<route>`);
3. queue members in `queues.conf` are the queue's own organization's
   endpoints, and pickup group names carry the namespace;
4. the from-trunk contexts send each DID only to the organization that
   owns its inbound route.

The verifier runs inside `generator.validate` for every revision as soon as
more than one namespace exists. A failure makes the revision invalid, so
nothing reaches Asterisk. The test suite builds installations with two and
three organizations that use the same numbers, slugs and names. It checks
that the verifier passes on generated output and fails on hand-made leaks:
an include, a `Goto`, a `Dial` to the other organization's phone, a foreign
mailbox and a foreign queue member.

## 6. Activation

* `installation.multi_tenancy_enabled` (exists, false by default):
  * While it is **off**, creating or reactivating a second active
    organization answers `409 multi_tenancy_disabled`.
  * An installation that already has several active organizations keeps
    working; System → Health and the Organizations page show a warning
    until it is turned on.
* **Turning it on** (`POST /system/multi-tenancy`, platform administrators,
  audited):
  1. Veyra generates the configuration from the current database, then runs
     the verifier with a synthetic second organization that has the same
     numbers as the first, so the proof does not depend on how many
     organizations exist yet.
  2. Only when this passes is the switch set.
  3. The answer lists the checks.
* **Turning it off** is allowed only with one active organization left.
* While multi-tenancy is on, organization administrators see only their own
  organization in every installation-wide view that shows call data. The
  dashboard graphs and the active-calls count become platform-only. Per
  organization graphs are a later step.

## 7. Interface

* **System → Settings → Multi-tenancy** card:
  * the switch;
  * the result of the last check;
  * a plain statement of what is shared (trunks, outbound routes marked
    "all organizations", the numbering plan).
* **Organizations** page:
  * the namespace of each organization;
  * a warning while several organizations are active without
    multi-tenancy;
  * "Add organization" explains the switch when it is off.
* **Outbound routes**: an "Organization" field ("All organizations" or
  one).
* Paging zone dialog: the multicast warning (§4).

## 8. Out of scope

* **PostgreSQL row-level security** (DATABASE_SCHEMA.md "Planned").
  Proposed for Milestone 17 hardening, because all of Veyra's processes are
  trusted and query through one access layer (§10 question 2).
* Per-organization sign-in providers, SMTP servers, numbering plans,
  firewall rules and dashboard graphs.
* Billing, quotas and per-organization limits on channels.
* Moving an organization's data between namespaces.

## 9. Testing

* **Unit:**
  * namespace derivation (uniqueness, length, empty only by migration);
  * every name builder;
  * the verifier on good output and on each kind of leak.
* **Generator:**
  * two and three organizations with identical numbers and slugs;
  * the single-organization output stays byte-for-byte what it was before
    M14 (the golden tests keep passing unchanged).
* **API:**
  * the same numbers in two organizations;
  * `next-number` per organization;
  * outbound routes per organization;
  * the `multi_tenancy_disabled` refusal;
  * activation with its checks;
  * turning it off refused with two organizations;
  * organization administrators not seeing the other organization's
    calls.
* **Live on dev1**, with the owner's agreement, since it adds a temporary
  second organization:
  * turn on multi-tenancy;
  * create "Test B" with an extension that has the same number as one of
    dev1's;
  * use ARI Local channels to dial from each organization's context to the
    other's numbers, expecting the "invalid number" announcement or the
    own-organization phone;
  * remove the test organization and turn the switch off again.

## 10. Open questions for the owner

1. **What is multi-tenancy for in your case?** Hosting other districts or
   schools on one Veyra server, or separating buildings of the district?
   Buildings are already handled by **sites**: one organization, shared
   numbers and voicemail, per-site emergency caller ID. Multi-tenancy is
   for organizations that must not reach each other.
2. **Row-level security:** move it to M17 (proposed) or do it now?
3. **Outbound routes:** shared by default with an optional organization
   (proposed), or per organization only?
4. **Trunks:** stay installation-wide and managed by platform
   administrators (proposed), or can an organization have its own trunk?
