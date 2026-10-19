# SIP trunks and call routing

How Veyra connects to carriers and routes calls in and out. Delivered in
Milestone 6. Ring groups, queues and pickup groups (Milestone 8), voicemail
and IVR (Milestone 7) add further destinations later; the objects here are
designed so those slot in without changing the model.

## 1. Objects

| Object | Scope | Purpose |
|---|---|---|
| **Trunk** (`sip_trunks`) | Installation (platform administrators) | A SIP connection to a carrier or another PBX: how to reach it, how to authenticate, how to recognise its calls |
| **Inbound route** (`inbound_routes`) | Organization | Where a call arriving on a DID goes: an extension now; ring groups, IVRs and voicemail later. Optionally differs by time condition |
| **Outbound route** (`outbound_routes`) | Installation | Which dialled numbers leave through which trunks, in which order, with which caller ID |
| **Time condition** (`time_conditions`) | Organization | Named opening hours (weekly ranges plus holidays) in a time zone, referenced by inbound routes |

Everything is stored in the database and reaches Asterisk only through a
generated and deployed revision ([TELEPHONY_ENGINE.md](TELEPHONY_ENGINE.md)
§4). Every save that may affect the engine raises the **Deploy changes**
flag. A new generated file, `pjsip.trunks.conf`, holds the trunk sections;
the installer's `pjsip.conf` stub includes it (upgrade installs the new
stub before the new code runs).

## 2. Trunks

| Field | Notes |
|---|---|
| `name` | Display name, unique |
| `slug` | Section and context name part (`trunk-<slug>`), derived from the name on creation: lower-case letters, digits and hyphens, at most 40 characters, unique. Stable while the trunk exists |
| `auth_mode` | `registration` (Veyra registers to the carrier with a user name and password) or `ip` (the carrier trusts the server's address; calls are matched by the carrier's addresses) |
| `host`, `port`, `transport` | Carrier SIP server (host name or address), port (default 5060), `udp`, `tcp` or `tls` |
| `username`, `auth_username`, `password` | Registration mode. The password is write-only in the API, encrypted at rest with the installation key (purpose `trunk.sip_secret:<id>`), and decrypted only into the snapshot. `has_password` is returned instead |
| `from_user`, `from_domain` | Optional overrides for the From header on outbound calls (carriers often require the account number) |
| `outbound_proxy` | Optional `host[:port]`; generated as `sip:host:port;lr` |
| `match_addresses` | Addresses or CIDRs whose calls are recognised as this trunk. Defaults to the host. Required to be non-empty for `ip` mode |
| `codecs` | Optional override of the installation codec list |
| `max_channels` | Optional cap on simultaneous calls through the trunk (outbound; enforced with Asterisk `GROUP_COUNT`) |
| `default_caller_id` | Number sent as caller ID on outbound calls when the route does not override it |
| `caller_id_header` | `pai` (P-Asserted-Identity, default), `rpid` (Remote-Party-ID) or `none` |
| `status` (read-only) | `state` `online`/`offline` from the qualify ping, or, for a registration trunk whose registration the engine reports as anything but registered, `rejected`, `registering` or `unregistered` (Milestone 18, issue #45); `reachable`; `registration`, the engine's own word. The `trunk_down` alert fires on a refused registration even when the host answers pings. Telephony → Registrations lists the trunks with the same state |
| `dtmf_mode` | `rfc4733` (default), `inband`, `info`, `auto` |
| `fax_t38` | `false` (default); `true` offers T.38 fax relay to the carrier (`t38_udptl=yes`, redundancy error correction, NAT), audio fax when it declines ([USER_PORTAL.md](USER_PORTAL.md) §9) |
| `qualify_frequency` | Seconds between OPTIONS pings (default 60; 0 disables). Drives the reachability status |
| `register_expiry` | Registration lifetime in seconds (default 3600; registration mode) |
| `is_enabled` | Disabled trunks stay in the database but are left out of the generated configuration and the routes skip them |

**Status.** `GET /trunks` and `GET /trunks/{id}` carry `status: {state,
reachable}` from the engine's endpoint resource (ARI `/endpoints`): `online`
when the qualify ping is answered, `offline` when not, `unknown` when the
engine cannot report or qualify is disabled. This works for both modes
because the trunk's AOR has a static contact for the carrier. The outbound
*registration* state itself is not exposed by ARI (§11).

**Deleting** a trunk that an outbound route or an inbound route references
answers `409 trunk_in_use` with the route names; remove it from the routes
first.

## 3. Inbound routing (DIDs)

| Field | Notes |
|---|---|
| `organization_id` | The organization that owns the DID |
| `did` | The number as the carrier sends it in the Request-URI: digits with an optional leading `+`, 2 to 20 characters. Unique per trunk restriction (one shared route and one per trunk may exist for the same number; the trunk's own wins on that trunk). `any` is accepted as the catch-all for calls whose DID matches no other route |
| `trunk_id` | Optional: only calls arriving on this trunk match. Without it the DID matches on every trunk |
| `description` | Free text |
| `destination_type`, `destination_extension_id` | `extension` today (the type field exists so ring groups, IVRs and voicemail can be added without a schema change). A route whose extension was deleted keeps its row with no destination and answers with congestion until fixed; the interface flags it |
| `time_condition_id`, `after_hours_extension_id` | Optional. With a time condition, calls inside the ranges go to the destination and calls outside go to the after-hours extension (required when a time condition is set) |
| `caller_id_prefix` | Optional text prepended to the caller's name on the phone display (for example `Main: `), letters, digits, space and `. ' & ( ) - :` |
| `is_enabled` | |

**North American aliases.** A ten-digit DID also matches when the carrier
sends it as `1NXXNXXXXXX` or `+1NXXNXXXXXX`, and vice versa, unless another
route claims that exact form. Uniqueness is checked on the canonical ten
digits, so `5731234567` and `+15731234567` cannot both exist with the same
trunk restriction. Other lengths
match exactly.

**Dialplan.** Each trunk endpoint enters `veyra-from-trunk-<slug>`, which
holds the routes restricted to that trunk and includes the shared
`veyra-from-trunk` with the unrestricted ones. A matched DID sets
`VEYRA_DID`, marks the call as having arrived from a trunk
(`VEYRA_HOPS=1`, §6), applies the caller-ID prefix, evaluates the time
condition with `GotoIfTime` in the condition's time zone and jumps to the
extension in `veyra-internal`. Unknown DIDs and calls without one get
`Hangup(1)` (unallocated number) unless an `any` route exists.

## 4. Outbound routing

| Field | Notes |
|---|---|
| `name`, `slug` | Display name and derived context name (`veyra-out-<slug>`), unique |
| `position` | Evaluation order; `PUT /routing/outbound/order` reorders. Emergency routes always come first regardless of position |
| `is_emergency` | Marks the route as carrying emergency numbers (§7) |
| `patterns` | One or more `{prefix, match, prepend}`: the caller dials `prefix` + `match`; the prefix is stripped and `prepend` added before the number is sent. `match` uses Asterisk pattern letters: `X` any digit, `Z` 1–9, `N` 2–9, `.` one or more remaining characters, `[15-7]` sets. Example: prefix `9`, match `NXXNXXXXXX`, prepend `1` sends `1` + ten digits for `9` + ten digits |
| `trunks` | Ordered list of trunks; the next one is tried when the previous answers CHANUNAVAIL or CONGESTION (busy and no-answer do not fail over). At least one trunk |
| `caller_id_number`, `caller_id_force` | Optional number for calls on this route. Precedence on a trunk leg (Milestone 18, [CALL_FEATURES.md](CALL_FEATURES.md) §3.5): the extension's emergency caller ID on an emergency route → this number when `caller_id_force` is set → the extension's `outbound_caller_id_number` (with its outbound name) → this number → the trunk's `default_caller_id` → the caller's number as the carrier receives it |
| `description`, `is_enabled` | |

**Matching order.** Asterisk picks the best pattern *within* a context and
searches *includes* in order, so each route has its own context and
`veyra-outbound` includes them in evaluation order (emergency routes
first, then by position). `veyra-internal` includes `veyra-outbound` after
the extensions and feature codes and before the invalid-number catch-all, so
an outbound pattern can never shadow an extension. Reserved numbering-plan
prefixes (`0`, `9`, `911`, `933` by default) keep extensions out of the way
of dialling prefixes.

**Dialplan** per route (`veyra-out-<slug>`): set `VEYRA_ROUTE`, refuse
calls that arrived from a trunk (§6), compute the number to send, then for
each trunk in order: skip it when `max_channels` is reached, set the caller
ID, `Dial(PJSIP/<number>@trunk-<slug>,60)`, and continue to the next trunk
only on CHANUNAVAIL or CONGESTION. When every trunk failed the caller hears
"all circuits are busy" and congestion tone.

## 5. Time conditions

| Field | Notes |
|---|---|
| `organization_id`, `name`, `description` | |
| `timezone` | IANA name (`America/Chicago`); defaults to the organization's time zone |
| `ranges` | List of `{days: ["mon", …], start: "HH:MM", end: "HH:MM"}`; `end` is exclusive at minute resolution. Overnight ranges are entered as two ranges |
| `holidays` | Days that count as closed all day, one string each: `MM-DD` (every year), `MM-DD..MM-DD` (every year, may cross New Year), `YYYY-MM-DD` and `YYYY-MM-DD..YYYY-MM-DD` (once: a snow day, this year's winter break), `N-ddd-MM` or `last-ddd-MM` (the first to fourth or last weekday of a month every year: `4-thu-11` is Thanksgiving, `last-mon-05` Memorial Day; not `last-…-02`) |

`GET` responses carry `open_now` computed by the server in the condition's
time zone, so the interface can show "open" or "closed" without guessing.
The dialplan uses `GotoIfTime(times,days,mdays,months,timezone?label)` for
each range and yearly holiday (a weekday rule is a weekday within a
seven-day span of the month), and a comparison of
`${STRFTIME(${EPOCH},zone,%Y%m%d)}` for one-off dates, because `GotoIfTime`
has no year; the evaluation happens on the server's clock in the
configured zone.

## 6. Loop detection and limits

* A call that arrived from a trunk carries `VEYRA_HOPS=1`. Outbound routes
  refuse such calls (`Hangup(21)`, call rejected) so a DID can never be
  routed straight back out to a carrier; this stays true when forwarding
  destinations arrive in later milestones, which must increment the counter
  and respect a maximum of 3 hops.
* Trunk endpoints send `Max-Forwards: 70` and the trunk AOR carries a single
  contact, so a carrier looping a call back is cut off by SIP itself.
* `max_channels` on a trunk is enforced with `GROUP(trunk)=<slug>` and
  `GROUP_COUNT`; an over-limit trunk is skipped like an unreachable one.
* The static validator refuses a snapshot with a duplicate DID, slug or
  context name, patterns with unsafe characters, and a route without trunks.

## 7. Emergency numbers

See [EMERGENCY_CALLING.md](EMERGENCY_CALLING.md) for the obligations.
Milestone 6 delivers the routing part only:

* Routes marked `is_emergency` are included first, so `911` dialled from any
  extension matches before any other pattern, with no prefix (Kari's Law
  direct dialling). The numbering plan already reserves `911` and `933`.
* An emergency route ignores the loop check, dials with a 120-second
  timeout and logs `Veyra EMERGENCY call from <extension>` at WARNING level
  in the Asterisk log, with the extension's emergency caller ID when it has
  one.
* **Caller ID presented on an emergency call** (Milestone 9): the
  extension's `emergency_caller_id_number` (the building's ELIN or
  registered DID, [EXTENSIONS.md](EXTENSIONS.md) §1) when set; otherwise
  the route's `caller_id_number`; otherwise the trunk's `default_caller_id`;
  otherwise the extension's regular caller ID. The generator writes
  `set_var=VEYRA_EMERGENCY_CID=<number>` on the endpoint and the emergency
  context runs `ExecIf($["${VEYRA_EMERGENCY_CID}"!=""]?Set(CALLERID(num)=…))`
  before dialling, so a more specific number always wins. `GET
  /routing/outbound` warns when an emergency route has no number of its own
  and enabled extensions have no emergency caller ID (the trunk default is
  then presented for them).
* `GET /routing/outbound` reports `warnings`, including "No enabled
  emergency route" when none exists, and the Outbound Routes page shows it.
  Veyra does not block deployment: an installation may legitimately route
  emergency calls through another system.
* Not yet: on-site notification, per-site trunk selection with dispatchable
  location, callback handling, test-call records (Milestone 17).

## 8. Generated configuration

| File | Content | Reload |
|---|---|---|
| `pjsip.trunks.conf` (**sensitive**) | Per enabled trunk: endpoint `trunk-<slug>` (`context=veyra-from-trunk-<slug>`, codecs, NAT and media settings as for phones, `set_var=VEYRA_TRUNK=<slug>`, caller-ID header, DTMF, From overrides, outbound proxy, `outbound_auth` in registration mode), AOR with the carrier contact and qualify, `identify` with the match addresses, and in registration mode an `auth` and a `registration` section (`server_uri`, `client_uri`, `contact_user`, retry intervals, `line=yes`) | `res_pjsip.so` |
| `pjsip.endpoints.conf` | Unchanged apart from `set_var=VEYRA_ORG=<organization slug>` on every phone endpoint (used by later per-tenant routing) | `res_pjsip.so` |
| `extensions.conf` | `veyra-internal` now includes `veyra-features`, `veyra-outbound`, `veyra-invalid`; new `veyra-outbound`, one `veyra-out-<slug>` per route, `veyra-from-trunk` and one `veyra-from-trunk-<slug>` per trunk | `pbx_config.so` |

Reload order is unchanged (`res_rtp_asterisk.so`, `res_pjsip.so`,
`pbx_config.so`). A SIP reload re-reads trunk registrations: changing a
registration trunk re-registers it; unchanged trunks are not disturbed.

## 9. Permissions

| Permission | Default roles | Allows |
|---|---|---|
| `trunks.read` | Organization administrators, technicians | List trunks and their status (needed to restrict an inbound route to a trunk) |
| `trunks.write` | Platform administrators only | Create, edit, delete trunks; create, edit, reorder, delete outbound routes |
| `routing.read` | Organization and site administrators, technicians, read-only users | Inbound routes and time conditions of their organizations; outbound routes (read) |
| `routing.write` | Organization and site administrators | Inbound routes and time conditions of their organizations |

Outbound routes are shared by every organization unless one is chosen for
the route (Milestone 14, [MULTI_TENANCY.md](MULTI_TENANCY.md) §4); they sit
under `trunks.write` because they choose the installation's trunks.

## 10. API summary

```
GET    /trunks?q=                         status included
POST   /trunks                            {name, auth_mode, host, port?, transport?, username?, auth_username?, password?, from_user?, from_domain?, outbound_proxy?, match_addresses?, codecs?, max_channels?, default_caller_id?, caller_id_header?, dtmf_mode?, fax_t38?, qualify_frequency?, register_expiry?, description?, is_enabled?}
GET    /trunks/{id}
PATCH  /trunks/{id}                       password: set a new one; null clears it
DELETE /trunks/{id}                       409 trunk_in_use

GET    /routing/inbound?q=&organization_id=
POST   /routing/inbound                   {organization_id, did, trunk_id?, destination_type, destination_extension_id, time_condition_id?, after_hours_extension_id?, caller_id_prefix?, description?, is_enabled?}
GET    /routing/inbound/{id}
PATCH  /routing/inbound/{id}
DELETE /routing/inbound/{id}

GET    /routing/outbound                  ordered; with warnings
POST   /routing/outbound                  {name, patterns:[{prefix, match, prepend}], trunk_ids:[...], caller_id_number?, caller_id_force?, is_emergency?, description?, is_enabled?}
GET    /routing/outbound/{id}
PATCH  /routing/outbound/{id}
DELETE /routing/outbound/{id}
PUT    /routing/outbound/order            {ids:[...]}

GET    /routing/time-conditions?organization_id=
POST   /routing/time-conditions           {organization_id, name, timezone?, ranges:[{days, start, end}], holidays?:["MM-DD" | "YYYY-MM-DD" | "…..…" | "4-thu-11"], description?}
GET    /routing/time-conditions/{id}
PATCH  /routing/time-conditions/{id}
DELETE /routing/time-conditions/{id}      409 time_condition_in_use
```

Errors: `409 did_in_use`, `409 name_in_use`, `409 trunk_in_use`, `409
time_condition_in_use`, `422 validation_failed` with the field. Audit
actions: `trunk.create/update/delete`, `inbound_route.create/update/delete`,
`outbound_route.create/update/delete/reorder`,
`time_condition.create/update/delete`. Every write calls `mark_changed`.

## 11. Known limitations

* Registration state (registered, rejected, retrying) is not available
  through ARI. The status shows reachability from the qualify ping only;
  a failed registration therefore shows as *online* if the carrier answers
  OPTIONS. A later milestone can read `pjsip show registrations` through a
  read-only console channel granted to the deployer, or subscribe to ARI
  events.
* Inbound destinations are extensions only; outbound routes apply to every
  organization; no per-trunk inbound caller-ID manipulation beyond the name
  prefix; no least-cost or time-based outbound selection.
* Emergency calling remains **not certified** ([EMERGENCY_CALLING.md](EMERGENCY_CALLING.md)).
