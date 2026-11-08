# Multi-tenancy for an MSP

Design for hosting several separate customers on one Veyra server. Owner's
request of 2026-11-07, after an audit of 0.27.86. Milestone 14
([MULTI_TENANCY.md](MULTI_TENANCY.md)) isolated the dialplan. This design
closes the gaps outside it (Part A), adds what an MSP needs day to day
(Part B), and sets out the larger choices for the owner to make (Part C).

**Status:** approved 2026-11-07, with the owner's decisions in §13 and the
organization switcher in §10a. Built in the slices of §12.

**Rule for this work:** while multi-tenancy is **off**, nothing changes for a
single-organization installation. The golden generator tests stay
byte-for-byte the same, and a district sees no new steps. Every new rule
below applies when the switch is on, or to output with more than one
namespace.

## 0. Summary

| # | Finding (audit of 0.27.86) | Re-checked on `main` (e552822) | Fix |
|---|---|---|---|
| 1 | Active calls match by caller number | **Confirmed**, and covers hang-up and recording too | §2 |
| 2 | Any organization administrator can claim any DID | **Confirmed**, plus a cross-context gap in the verifier | §4 |
| 3 | Caller ID is not limited for organization administrators | **Confirmed**, with two more fields than the audit named | §5 |
| 4 | E911 is not separated by customer | **Confirmed**, plus a wrong-organization 911 notification | §6 |
| 5 | The activation check is weaker than it looks | **Confirmed** | §3 |
| 6 | Organization administrators cannot apply their own changes | **Confirmed** | §7 |
| 7 | No per-customer limits | **Confirmed** | §8 |
| 8 | No usage by organization | **Confirmed**; the call records already hold what billing needs | §9 |
| new | 911 event resolves the caller by extension number | **New**, found during the re-check | §6.4 |

Two of the audit's claims turned out narrower than written:

- **The caller ID allow list is safe.** It is edited through
  `PATCH /organizations/{id}`, which needs `organizations.write`, a
  platform-only permission. Organization administrators cannot widen it.
- **Site emergency caller IDs are platform-set.** They are edited through
  `/sites` (also `organizations.write`). The organization's `emergency.manage`
  covers only attestation, the responder, the callback window and
  recipients. The open path is the **extension's** emergency caller ID (§5).

Custom dialplan is already platform-only (`destinations._check_custom`). It
stays outside the verifier on purpose: a platform administrator writes it,
and it may cross organizations by design. §3.3 adds a warning when an
organization's object sends calls into it.

## 1. Re-checking the findings

### 1.1 Active calls (`api/v1/calls.py`)

`active_calls` (lines 107–123) builds `by_number = {e.number: e}` from the
caller's visible extensions. A channel is visible when its endpoint **or its
caller number** matches. `hangup` (250–251) and `record` (333–334) use the
same fallback. With extension 1001 in organizations A and B, A's
administrator sees B's call from B's 1001, labelled with A's extension name,
and can end it or record it. `monitor` (401) matches by endpoint only and is
not affected. The existing test `test_active_calls_are_scoped`
(`tests/test_api_calls.py:97`) uses 1001 and 2001, so it cannot catch this.

What the fallback was for: trunk legs and Local channels carry no phone
endpoint. Outbound trunk legs show the presented number. Inbound legs show
the outside caller. Local hops show the dialled number. Matching these by
number was always a guess, and with overlapping numbers it is wrong.

### 1.2 DIDs (`api/v1/routing.py`, `generator._inbound_contexts`)

- `create_inbound` (line 990) needs only `routing.write`, which `org_admin`
  and `site_admin` hold. Any DID, including `any`, is accepted.
- The database's unique key is `(trunk_id, did_canonical)` with nulls not
  distinct (`models/routing.py:109`). The generator's key is the same
  (`generator.py:3206`). So `(NULL, 5551234567)` for A and
  `(trunk T, 5551234567)` for B both exist. On trunk T the explicit
  extension in `veyra-from-trunk-T` wins over the included shared context,
  so the call goes to B. On every other trunk it goes to A.
- The verifier's rule 3 compares organizations only **inside one context**.
  The case above spans two contexts, so it passes.
- An `any` route on one trunk catches every unrouted number on it, and a
  shared `any` catches every trunk.

### 1.3 Caller ID (`api/v1/extensions.py`)

`check_outbound_caller_id` (line 300) returns at once when the user holds
`routing.write` for the organization (line 306). Every organization
administrator does. The list of "own" numbers it checks is the
organization's inbound routes, which an organization administrator can
create freely (§1.2).

Two more fields reach the carrier and have no check at all:

- **`emergency_caller_id_number`** on an extension. It is presented on
  emergency routes, and it is the key of the PSAP callback (§1.4).
- **`caller_id_number`** on an extension. When the extension has no
  outbound caller ID, and neither the route nor the trunk has a number,
  `CALLERID(num)` is left as the extension's own caller ID number on the
  trunk leg (`_outbound_caller_id`, `generator.py:1113`).

Outbound route caller IDs need `trunks.write` (platform-only), so only the
MSP sets them. A shared route's number does apply to every organization's
calls, though (§5.2).

### 1.4 E911 (`generator._outbound_contexts`, `emergency/service.py`)

- Emergency routes are shared, which is right: every organization needs
  one.
- Presented number: the extension's emergency caller ID, or the site's
  ELIN (resolved in the snapshot, `snapshot.py:554`). Without one, the
  route's number or the trunk's `default_caller_id` (`generator.py:3141`)
  is presented, and that can be another customer's number and address.
- The callback key is `veyra_ecb/<ELIN>` (`generator.py:3123`), written in
  the shared route context. The callback lookup maps each ELIN to one site
  (`elins[canonical] = site`), and the last site silently wins. If an
  organization administrator sets an extension's emergency caller ID to B's
  ELIN, A's 911 call writes B's callback key. The PSAP's callback to B's
  ELIN then rings `<A's extension number>` **in B's context**, which is a
  stranger's phone or nothing.
- Nothing checks that an emergency caller ID is one of the organization's
  own numbers.

### 1.5 Twin and verifier (`core/tenancy.py`, `asterisk/isolation.py`)

- `_with_twin` (`tenancy.py:96`) copies `extensions`, `voicemail_boxes`,
  `ring_groups`, `queues` and `ivr_menus`. The snapshot also has
  organization-owned `announcements`, `call_flows`, `caller_block_policies`,
  `classes_of_service`, `conference_rooms`, `disa_lines`, `fax_inboxes`,
  `parking_lots`, `shared_mailboxes`, `time_conditions`, `sites`,
  `inbound_routes`, `paging`, `recording`, `hold_music` and the
  organization's `directory_entries`. None of these are copied.
- `verify` (`isolation.py:101`) reads `extensions.conf`,
  `pjsip.endpoints.conf` and `queues.conf`. MULTI_TENANCY.md §5 says it also
  reads `voicemail.conf`. It does not.

### 1.6 Deploy (`permissions.py:92`, `configmgmt/service.py`)

- `config.deploy` is `platform_only`.
- The pending-changes flag is one installation-wide row
  (`telephony.pending_change`) with who and what, but not which
  organization.
- `_generate` turns any `GenerationError` into the revision's errors. One
  organization's bad object fails the revision for everyone, and the
  message does not say whose object it is.

### 1.7 Limits and usage

- Trunks count channels with `GROUP(veyra_trunk)` and keep emergency
  channels in reserve (issue #171). Nothing counts by organization.
- `call_records` already has `organization_id`, `direction` (internal,
  inbound, outbound) and `trunk_id`. The organization is taken from the
  phone on either side, then from the DID's route. The DID lookup is a loose
  suffix match (`cdr.py:226`), which is not good enough for billing (§9).
- The report builder has CSV export but no `organization` grouping.

### 1.8 New: the 911 notification names the wrong caller

The emergency route sends `UserEvent(VeyraEmergency, Extension:
${CALLERID(num)}, Site: ${VEYRA_SITE}, …, Channel: ${CHANNEL})`.
`emergency/service.py:112` finds the extension with
`Extension.number == <number>` and narrows to an organization **only when
the phone has a site**. For a phone without a site, `limit(1)` can pick
another organization's 1001. The notification then gives that
organization's recipients a wrong name and location, and the right
organization's recipients hear nothing.

## Part A: security fixes

These must ship before a second customer goes live.

## 2. Active calls

One helper, `call_owner(call, ctx) -> organization_id | None`, used by list,
hang-up, record and monitor:

1. **The channel's endpoint** is a phone: that extension's organization.
2. **The channel's endpoint is a trunk, or it is a Local channel**: the
   organization of a phone channel **in the same bridge** (ARI
   `GET /bridges` lists each bridge's channels; one call per request, not
   per channel).
3. **Not yet bridged** (ringing inbound, a Local hop): the channel variable
   `VEYRA_ORG`. Today it is set on phones (`set_var` on the endpoint) and
   on DISA, but it does not reach trunk legs: the endpoint's `set_var` has
   no `__`, so a dialled channel does not inherit it. In output with more
   than one namespace, the endpoint sets `__VEYRA_ORG` instead, and inbound
   route bodies gain `Set(__VEYRA_ORG=<slug>)`. Single-organization output
   keeps today's lines. The adapter reads the
   variable through ARI's `channelvars` (ari.conf `[general]`), if the
   installed Asterisk supports it, or through one `GET /variable` call per
   unattributed channel, at most 50 per request.
4. Otherwise **unknown**: only platform administrators see it.

Never by caller number. The name shown next to a call is taken only from an
extension of the call's own organization.

Tests: two organizations with **the same numbers and slugs** (1001 calling
1002 in both, and the same ring group and queue slugs). For each of list,
hang-up, record and monitor: A's administrator sees and acts on A's
channels only, gets 404 for B's, and is never shown A's name on B's call.
Trunk legs follow their bridge peer. A platform administrator sees
everything.

## 3. A complete activation check and verifier

### 3.1 A generic twin

The snapshot module declares what each top-level key holds:

```python
SNAPSHOT_KEYS = {
    "extensions": OrgList(),              # items carry "organization"
    "announcements": OrgList(),
    ...
    "sites": OrgList(),
    "inbound_routes": OrgList(org_field="organization_slug", did_field="did"),
    "paging": Nested(copy_paging),        # zones and Poly groups per organization
    "recording": OrgList(org_field="organization_id"),
    "hold_music": Nested(copy_hold_music),
    "organizations": Organizations(),     # copies the row, with directory_entries
    "trunks": Shared(), "outbound_routes": Shared(), "smtp": Shared(), ...
}
```

`_with_twin` walks this table:

- It copies every `OrgList` item of the first organization.
- It rewrites the organization fields (slug, id and namespace), every
  `endpoint_name`, and every id of a copied object. A table from old id to
  new id keeps the twin's references (a route's ring group, a ring group's
  members) inside the twin.
- DIDs of copied inbound routes and ELINs of copied sites get a reserved
  prefix (`0000…`) so they stay unique, as DIDs must.

**The guard test:** build a snapshot from a fixture that has one of every
feature. It fails when the snapshot has a key that `SNAPSHOT_KEYS` does not
list, and when an `OrgList` key has items whose twin copies are missing. A
new feature is then covered as soon as its key is listed, and forgetting to
list it fails the suite.

### 3.2 Verifier additions

`verify(files, *, strict, owners=None)` also reads:

| File | What it checks |
|---|---|
| `voicemail.conf` | Each mailbox context is one organization's. Every `copy_to` and shared inbox reference stays in it. Endpoint `mailboxes=` match it (today's check). |
| `confbridge.conf` | Bridge, user and menu profile names carry the namespace. Every `ConfBridge(room,bridge,user,menu)` in an organization's context names its own profiles. |
| `res_parking.conf` | Each lot's name, `context` and `parkext` context are one organization's. `Park`/`ParkedCall` arguments in an organization's context name its own lots. |
| `musiconhold.conf` | Class names carry the namespace, and `directory=` is under that organization's folder. `MusicOnHold`/`m()`/`CHANNEL(musicclass)` in an organization's context name its own classes. |
| `paging.json` | Every zone's members are endpoints of the zone's organization. Poly group numbers are unique per organization. |
| `extensions.conf` hints | `exten => N,hint,…` in an organization's context lists only its own endpoints and its own `Custom:veyra-*-<slug>-…` states. |
| `extensions.conf` device states | Every literal `Custom:veyra-…-<slug>-…` and `DEVICE_STATE(Custom:…)` in an organization's context uses its own slug. Shared contexts use only `${VEYRA_ORG}`. |
| `extensions.conf` AstDB | Every literal `DB(<family>/<key>)` in an organization's context uses its own slug (or namespace) as the first key. Shared contexts use `${VEYRA_ORG}`. Covers `veyra_ecb`, blacklist, last caller, DISA, DND, call forward and follow-me. |
| `extensions.conf` DIDs | With `owners` (from the number inventory, §4): every DID in **any** from-trunk context goes to the organization that owns the number, across the shared and per-trunk contexts together. |

**Slug to namespace:** the verifier already learns each organization's slug
from the endpoints' `VEYRA_ORG`. It now also takes the mapping from the
twin and `organizations` (passed in by `run_checks`), so an organization
without phones is checked too.

**Leak tests:** a hand-made leak for each new row: a foreign mailbox in a
copy list, a ConfBridge with another organization's profile, a parking lot
in another context, a hold music class or directory outside the folder, a
paging member of another organization, a hint with a foreign endpoint, a
foreign `Custom:` state, a foreign AstDB key, and a DID routed to a
non-owner across two contexts. Each must fail, and generated output for two
and three organizations with the same numbers and slugs must pass.

### 3.3 Custom dialplan

It stays outside the verifier. When an organization's object (a route, IVR
key or call flow) sends calls into custom dialplan, the activation result
lists it as a **warning**: "organization A uses custom context X, which the
isolation check cannot see into". It is not an error.

## 4. Number inventory

### 4.1 Table `organization_numbers`

| Column | |
|---|---|
| `id` | uuid |
| `organization_id` | FK, not null |
| `first` | canonical number (`routing.canonical_did`), digits only, not null |
| `last` | same length as `first`; equal to it for a single number |
| `trunk_id` | FK, null: arrives on any trunk |
| `label` | e.g. "Main line", "Fax", "Block from Acme Telecom" |
| `source` | `manual`, `migration`, `auto` (§4.4) |
| `created_at`, `created_by` | |

- **No number belongs to two organizations:**
  `EXCLUDE USING gist (int8range(first::bigint, last::bigint, '[]') WITH &&)`.
  A carrier number is unique worldwide, so this holds across trunks too.
- At most 10,000 numbers in one range, as a sanity limit.
- Platform administrators manage it under **Organizations → [org] →
  Numbers** and in onboarding (§10). It is audited. Organization
  administrators can read their own list.

### 4.2 The rules, while multi-tenancy is on

- A user who is not a platform administrator can create or change an inbound
  route only for a number assigned to their organization. When the number
  is tied to a trunk, the route must be for that trunk or for any trunk.
- A number is routed by **one organization only**, whatever the trunk
  restriction. The routing API checks the owner, and the inventory makes two
  owners impossible.
- **`any` is platform-only**, unless the trunk is dedicated to the
  organization (C4, approved).
- The verifier's DID check (§3.2) proves the generated output follows the
  inventory.

### 4.3 Migration

- Fill the table from existing inbound routes (except `any`), and from site
  and extension emergency caller IDs that are 10 digits or longer, with
  `source = migration`.
- **Conflicts** (the same number in two organizations' routes, possible
  through §1.2): the number goes to the organization of the shared
  (trunk-less) route, or to the older route. The other is listed under
  **System → Health → Number conflicts** for a platform administrator to
  decide. Existing routes keep working, but turning multi-tenancy on is
  refused while a conflict is open.
- The migration is numbered after #422's 0093 and 0094.

### 4.4 While multi-tenancy is off

Nothing changes for the user. Creating an inbound route for an unassigned
number assigns it to the organization (`source = auto`). Health still lists
conflicts, so the inventory is clean on the day the switch is turned on.

## 5. Caller ID

### 5.1 Who may present what

The **owned numbers** of an organization are its inventory numbers plus its
caller ID allow list. The allow list stays platform-managed, as today.

| Field | Who sets it | Rule while multi-tenancy is on |
|---|---|---|
| Extension outbound caller ID | `extensions.write` | an owned number; any number only for platform administrators |
| Extension emergency caller ID | `extensions.write` | an owned **inventory** number (not the allow list: the PSAP callback must ring back here) |
| Extension caller ID number | `extensions.write` | free (internal), but never sent to a trunk (§5.2) |
| Site emergency caller ID (ELIN) | platform | an inventory number of the site's organization |
| Organization main number (new) | platform | one of its inventory numbers |
| Outbound route caller ID | platform | an organization route: that organization's owned number. A shared route: refused while on (§5.2). |
| Trunk default caller ID | platform | unchanged; used only per §5.2 |

`check_outbound_caller_id` loses the `routing.write` exemption and checks
the inventory instead of inbound routes. Only a platform-scope principal
skips the check. While multi-tenancy is off, today's behaviour stays.

### 5.2 What a trunk leg presents

While there is more than one namespace, the snapshot resolves a phone's
outside number as:

1. its outbound caller ID;
2. else its organization's **main number** (new column `main_number`);
3. else the organization route's own caller ID.

It never resolves to a shared route's caller ID, a trunk's default, or the
extension's internal number, because any of those can be another customer's.
The generator passes the result as `VEYRA_OUT_CID`, so
`_outbound_caller_id` keeps its shape.

**Every organization has a main number (owner, 2026-11-07).** While
multi-tenancy is on:

- an organization cannot be created without one (§10);
- its last inventory number and its main number cannot be removed;
- turning the switch on is refused until every existing organization has
  one.

The main number is the organization's default outbound caller ID. Its calls
leave through the shared outbound routes, or through its dedicated trunk
(C4) when it has one.

Step 3 then never comes up empty in practice. If it does anyway (data
changed outside the API), the outside call is refused ("all circuits
busy"), logged, and raises an alert. It is never sent under another
customer's number. This never applies to 911 (§6).

### 5.3 Turning the switch on

The activation check lists every extension, site, route and organization
that breaks §5.1, with a link to each. They are warnings, not a refusal,
except where §6 requires them for 911.

## 6. E911 per customer

### 6.1 What a 911 call presents

While there is more than one namespace, the snapshot resolves each phone's
`VEYRA_EMERGENCY_CID` as:

1. the extension's emergency caller ID (owned, §5.1);
2. else its site's ELIN (owned);
3. else its organization's **emergency number** (new
   `emergency_caller_id_number`, an inventory number; defaults to the main
   number).

Step 3 is required for every organization (owner, 2026-11-07, §6.2), so the
emergency route never reaches the trunk default or the route's number.
**A 911 call is never refused.** If step 3 is somehow empty (data changed
outside the API), the call goes out with today's behaviour. `Log(ERROR)`
records it, and a critical alert is raised.

### 6.2 Rules

- **An organization must have an emergency number** (owner, 2026-11-07).
  While multi-tenancy is on, an organization cannot be created without one
  (§10), and it cannot be cleared.
- Turning multi-tenancy on is **refused** until every existing organization
  has one. With the main number (§5.2), these are the caller ID rules that
  block the switch.
- A save that would leave the emergency number outside the organization's
  inventory is refused, for example removing that number from the
  inventory.
- A site without its own ELIN is a **warning** on the readiness page:
  "Acme's Main Street site presents the organization's emergency number;
  register that number at the site's address, or give the site its own".

### 6.3 Callback key

- In output with more than one namespace, the key becomes
  `veyra_ecb/<slug>/<ELIN>`. It is written as
  `DB(veyra_ecb/${VEYRA_ORG}/${VEYRA_EMERGENCY_CID})` and read in the
  from-trunk body with the site's own slug.
- Single-organization output keeps `veyra_ecb/<ELIN>`.
- The ELIN-to-site map refuses two sites with the same ELIN instead of
  letting the last one win. The inventory already makes that impossible
  across organizations, and this is defence in depth.

### 6.4 The 911 event

- The event gains `Org: ${VEYRA_ORG}` and `Endpoint: ${CHANNEL(endpoint)}`.
  This line is in the shared route, so it is again only written when there
  is more than one namespace.
- `record_emergency` resolves the extension by endpoint, then by number
  **within the event's organization**, and never by number alone.
- Recipients already filter by `call.organization_id`
  (`emergency/service.py:213`).
- Test: two organizations with the same numbers, a phone without a site in
  each; both organizations' notifications name their own caller.

### 6.5 The emergency page

The platform view gets an **Organizations** table: each organization, its
911 number source (extension, site, organization or MSP fallback), its
sites' readiness, and its last test call. An organization administrator
sees their own row only.

## Part B: running it as an MSP

## 7. Organization administrators apply their own changes

- **Permission:** `config.deploy` gains an organization scope. At platform
  scope it is today's permission. At organization scope (default role
  `org_admin`, only while multi-tenancy is on; owner decision 3), the user
  may apply when **their** organization has pending changes.
- **What it does:** it generates and deploys the whole configuration, which
  is the only kind of deploy Asterisk has. Other organizations' saved
  changes go live with it. The dialog says so: "Applying reloads the
  telephony server for every organization." The mode is fixed to **when
  idle** for organization scope.
  Platform administrators can still choose now.
- **Rate limit:** organization scope only, one apply per organization per 5
  minutes, and 12 per hour across all organizations. A refusal answers 429
  with when to try again. Audited with the organization.
- **Pending changes per organization:** `mark_changed` gains an
  organization. The flag becomes one row per organization plus one for
  shared objects. Each organization's banner shows its own row and any
  generation error that names it.
- **Errors name the organization:** `GenerationError` gains `organization`
  and `object` (e.g. `ring group office`). The generator fills them from
  the item being written, so the revision's errors read "Acme, ring group
  office: …".
- **Isolating a failure (approved):**
  - Each successful revision stores each organization's slice of the
    snapshot, encrypted with the installation key, because it holds SIP
    secrets.
  - When generation fails with an error that names one organization, Veyra
    generates again with that organization's slice taken from its last good
    revision.
  - If that passes, the revision deploys, and that organization's banner
    says "your last changes were held back: …".
  - An error in a shared object (a trunk or a shared route) still stops
    everyone, as it must.

## 8. Limits per organization

New table `organization_limits` (one row per organization; MSP plans extend
it later):

| Column | |
|---|---|
| `max_outside_calls` | concurrent calls through any trunk, in plus out; null = no limit |
| `max_extensions`, `max_devices` | null = no limit |
| `plan_id` | reserved for MSP plans (null) |

- **Dialplan:**
  - Outbound route steps add
    `Set(GROUP(veyra_org)=<slug>)` and
    `GotoIf($[${GROUP_COUNT(<slug>@veyra_org)} > N]?busy)` per
    organization, next to the existing `GROUP(veyra_trunk)`.
  - Inbound route bodies add the same, and an inbound call over the limit
    gets busy.
  - The lines are written only for organizations with a limit, so other
    output is unchanged.
- **Emergency calls are never counted or refused:**
  - Emergency routes set neither group.
  - The PSAP callback path (ELIN bodies) sets none either.
- **Extensions and devices:**
  - The API refuses a create over the limit with `409 limit_reached`. That
    covers bulk import, provisioning auto-create and the onboarding page.
  - Lowering a limit below today's count is allowed and shown ("12 of 10;
    no new ones").
- Only platform administrators see and set limits. Organization
  administrators see their own on the organization page.

## 9. Usage by organization

- **Data:**
  - `call_records` gains `is_emergency`, set when the folded call left
    through an emergency route. A new `CDR(veyra_route)` or the route's
    patterns tell.
  - The DID-to-organization lookup uses the inventory, matched exactly in
    canonical form, instead of the suffix match.
- **Report:**
  - The report builder gains an `organization` grouping and filter. Both
    are platform-only, because organization administrators already see only
    their own organization.
  - A built-in report, **Usage by organization**: organization × trunk ×
    month, with outside calls (inbound and outbound separately), total
    minutes, and billable minutes (each call rounded up to a whole minute).
  - Emergency calls are a separate column and never billable.
  - CSV export comes from the builder.
- **Peak concurrent outside calls** per organization per month is computed
  from start and end times. It is shown on the usage page, not in the
  builder.
- **Internal calls** are already in `direction`. They show as a count only,
  so MSP plans can build on them.

## 10. Organization onboarding

**Organizations → Add organization** becomes a guided page for platform
administrators. Each step saves on its own, shows done or to do, and can be
left and resumed:

1. **Organization and numbers:** name, slug, time zone, its DIDs and
   ranges (§4), the main number and the emergency number. The namespace is
   shown. While multi-tenancy is on, the organization is not created
   without a main number and an emergency number (§5.2, §6.2).
2. **Trunk:** the shared outbound routes it uses, or a dedicated trunk
   (C4), optional.
3. **First administrator:** an email invitation, or a temporary password
   (the existing users API), with the `org_admin` role in the new
   organization.
4. **Phones:** the provisioning credential for the organization.
5. **Emergency:** a site with its civic address and ELIN (one of step 1's
   numbers). Shows the readiness result.
6. **Limits** (§8), optional.
7. **Check:** runs the isolation check (§3) and the §5 and §6 rules with
   this organization included, and lists what is left.

Step 1 still needs multi-tenancy to be on, or this to be the first
organization. The page links to the switch.

**As built (slice 9):** step 1 is the **New organization** dialog, which
creates the organization with its numbers, main number and emergency number
in one save (`POST /organizations` takes `numbers`, `main_number`,
`emergency_caller_id_number`; required while multi-tenancy is on). Steps 2
to 6 are on **Organizations → organization → Set up**
(`GET /organizations/{id}/onboarding`); step 7 is
`POST /organizations/{id}/onboarding/check` (platform administrators). Step
3 adds the administrator with a temporary password; an email invitation is
not built, as Veyra has no invitation mail yet.

## 10a. Working in one organization

Owner's request, 2026-11-07:

> "If there are multiple organizations, you must choose which organization
> you are working in (and have an organization switcher on the top menu)
> so the settings you are working with only apply to that organization.
> Almost like having a dedicated Veyra server per client … while the
> system-wide settings would show everything, pending permissions. User
> roles should have an option to give them permissions for which clients
> they can view (per client)."

### 10a.1 Today

- Lists (extensions, ring groups, devices and so on) show every
  organization the user can see, mixed together.
- Each dialog has an **Organization** field.
- Role assignments are already scoped: a role is granted for the platform,
  for one organization, or for one site (`role_assignments.scope_type`).
  Someone can hold Technician in clients A and C only, as two assignments.
  The users page does not make this easy to see or set.

### 10a.2 The organization switcher

- **Top bar.** A switcher shows the organization being worked in: its
  name, plus its colour once branding (C1) exists. It is shown only when the
  user can see more than one organization. A single-organization
  installation never sees it.
- **Choices:** each organization the user holds a role in, and, for users
  with platform-scope permissions, **System (all organizations)**.
- **In an organization**, Veyra behaves like that client's own server:
  - Every list shows only that organization, without an Organization
    column.
  - Every dialog's Organization field is gone; new objects belong to the
    current organization.
  - The menu shows only that organization's pages: extensions, groups,
    queues, routing, devices, provisioning, reports, users, voicemail,
    emergency, its numbers and limits (read-only), and so on.
  - System pages (trunks, system settings, firewall, updates, modules, HA,
    backups, the number inventory of every client, usage, onboarding) are
    not in the menu. They are one click away under **System**.
  - The pending-changes banner and **Apply** are that organization's (§7).
- **In System**, the user sees what they see today: every organization's
  objects with an Organization column, and the system-wide pages, as far as
  their permissions allow.
- **Enforced by the server, not just the menu.** The browser sends the
  current organization in a header (`X-Veyra-Organization`). The API
  narrows the user's permissions to that organization for the request,
  even for a platform administrator. While working in A, a write to B's
  object answers 404, as if B did not exist. "System" sends no header and
  keeps today's behaviour.
- **One tab, one client.** The choice is kept per browser tab, so an MSP
  technician can have client A in one tab and client B in another without
  mixing them up. A link or bookmark carries it as `?org=<slug>`. A new tab
  opens in the organization of the tab it came from, or else the user's
  last one.
- **Which page after switching:** the same page in the new organization
  (Extensions in A becomes Extensions in B). An open object (extension
  1001 of A) is closed and goes back to its list.
- **Searching across clients** stays in System.

### 10a.3 Choosing the clients a user can see

- **Users → user → Access** lists the user's roles, one row per role, with
  where it applies:
  - **All organizations**: platform scope (only for platform
    administrators to grant);
  - **These organizations**: pick one or several clients;
  - **These sites** of one organization (today's site scope).
- Saving writes one role assignment per client. Removing a client removes
  its assignment and ends the user's open sessions' access to it at once.
- **Typical MSP set-up:**
  - MSP staff: Technician (or a custom role) in the clients they look after;
  - a customer's own IT person: Organization Administrator in their
    organization only;
  - the MSP owner: Platform Administrator.
- An organization administrator can grant roles only within their own
  organization, as today. Only a platform administrator can give someone
  access to several clients.
- Custom roles work the same way, so the MSP can make a "Client support"
  role with exactly the permissions it wants and grant it per client.
- **What a user may grant is still limited by what they hold:** no one can
  grant a permission they do not have in that organization.

### 10a.4 Built as

- Backend:
  - the header and the narrowed principal (`Principal.narrowed(org_id)`);
  - `GET /me/organizations`, the switcher's list;
  - the access editor's API (role, scope, several organizations in one
    save).
- Frontend:
  - the switcher;
  - the per-tab organization;
  - lists and dialogs reading the current organization instead of asking;
  - the menu split into the organization and System;
  - the Access tab.
- Tests:
  - a platform administrator working in A cannot change B's objects;
  - a technician in A and C sees only A and C in the switcher, and gets 404
    for B;
  - a user without a header gets today's behaviour;
  - one organization: no switcher.

## Part C: for the owner to decide (not built)

### C1. Branding, portal hostname and SMTP sender per organization

- Branding and sender: an `organization_branding` row (logo, colours,
  product name, "from" name and address).
- Portal hostname: a hostname per organization, with its own certificate
  (Let's Encrypt, M22).
- The sign-in page picks the branding from the hostname.
- Email keeps one SMTP server, with the sender per organization. That needs
  SPF and DKIM for each customer's domain, or a sender on the MSP's domain
  with "on behalf of".
- Effort: medium. **Recommended next**, because customers see it first.

### C2. Sign-in providers per organization

- Providers get an optional `organization_id`. The sign-in page offers the
  providers of the hostname's organization (C1).
- A user from a provider can only join that provider's organization.
- Depends on C1. Effort: medium.

### C3. Extension length per organization

- The numbering plan (length, range, reserved numbers) moves to the
  organization, with the installation's as the default.
- Feature codes and `**<ext>` patterns are already per organization.
- The risk is the reserved emergency numbers (911, 933), which must stay
  blocked whatever the length.
- Effort: medium. Only if a customer needs it.

### C4. Trunks owned by one organization (bring your own carrier)

**Approved (owner, 2026-11-07): built with slice 3.**

- `sip_trunks.organization_id`: null is shared (today), set means dedicated.
- A dedicated trunk:
  - may have that organization's `any` catch-all;
  - is used only by that organization's routes;
  - has its own limits;
  - may have its trunk default caller ID used by §5.2 and §6.1.
- Organization administrators still cannot edit trunks: credentials and
  firewall rules stay with the MSP.
- Effort: small once Part A is in.

### C5. PostgreSQL row-level security

- Every tenant table gets a policy on `organization_id = current_setting('veyra.org')`.
  The API sets it per request.
- The engine, workers and the platform-admin paths use a role that bypasses
  it.
- It protects against a missed filter in the API, not against a compromised
  server.
- The cost: every query path needs the setting, and background jobs that
  span organizations need the bypass role. That is a broad, risky change.
- **Recommended later** (after 1.0). The two-organization API tests in this
  work cover the same ground more cheaply now.

### C6. HA, backups and restoring one organization

- HA already replicates everything and needs nothing new for tenants.
- Backups are whole-installation.
- An MSP will be asked to restore one customer's deleted ring group or
  voicemail without rolling back the others.
- Proposed:
  1. an **organization export** (JSON of its rows, plus its prompts, hold
     music and voicemail files);
  2. an **import into an existing organization** that recreates deleted
     objects and never touches other organizations;
  3. recordings and voicemail restored per mailbox from the whole backup.
- A full per-organization restore (rewind one customer) is much harder
  because of shared objects, and is not proposed.

## 11. Testing

- **The fixture:** a shared `two_orgs` fixture creates organizations A and
  B with **identical** numbers, slugs and names: extensions 1001 and 1002,
  ring group 600, queue `support`, conference 800, parking, an IVR, a
  paging zone and a site each. Every API test of this work uses it.
- **Golden:** the single-organization output stays byte-for-byte the same.
  Every new dialplan line is gated on more than one namespace or a limit
  being set.
- **Verifier:** two and three organizations pass, and each hand-made leak in
  §3.2 fails. The `SNAPSHOT_KEYS` guard test (§3.1).
- **Backend checks:** ruff, mypy, pytest and `alembic check`. Frontend:
  lint, typecheck, vitest and build.
- **Live on dev1**, with the owner's agreement, after the pull request:
  1. turn the switch on;
  2. create a temporary organization whose extension has the same number as
     one of dev1's;
  3. dial across with ARI Local channels in both directions;
  4. check the active calls list as each organization's administrator;
  5. remove the temporary organization and turn the switch off.
- **Test: issues** on Project #7 for each slice.

## 12. Slices

On this branch, each with tests:

1. **Active calls** (§2).
2. **Twin and verifier** (§3).
3. **Number inventory, inbound routes and dedicated trunks** (§4, C4),
   migration.
4. **Caller ID** (§5), migration (main number).
5. **E911** (§6), migration (organization emergency number,
   `is_emergency`).
6. **Deploy** (§7): organization scope, per-organization pending, errors
   that name the organization, and isolating one organization's failure.
7. **Limits** (§8), migration.
8. **Usage** (§9).
9. **Onboarding** (§10).
10. **Working in one organization** (§10a): the switcher, the narrowed
    API, and per-client access on the users page.
11. **Docs:** an admin guide `docs/guides/host-several-organizations.md`,
    MULTI_TENANCY.md updated, CHANGELOG.

## 13. Owner decisions (2026-11-07)

1. **Dedicated trunks:** yes. A trunk can belong to one organization and
   may then have its `any` catch-all (C4, slice 3). A shared trunk's `any`
   stays platform-only.
2. **911 number:** every organization must have an emergency number of its
   own. While multi-tenancy is on, an organization cannot be created
   without one (§6.2). There is no MSP-wide fallback number.
3. **Applying changes:** organization administrators apply their own
   changes, when idle, rate-limited and audited (§7). An installation
   setting "Organization administrators: apply / request only" keeps the
   other choice open. Apply runs targeted module reloads, not a restart, so
   calls in progress stay up.
4. **Outside calls:** every organization must have a main number, its
   default outbound caller ID, and uses the shared routes or its dedicated
   trunk (§5.2).
5. **Isolating generation failures:** yes, as recommended (§7, slice 6).
6. **Billable minutes:** each call rounded up to a whole minute.
7. **Publishing:** this branch stays on the development server, not on
   GitHub, until the security fixes (slices 1–5) are built. It is then
   pushed with them.
