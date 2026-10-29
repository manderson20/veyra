---
title: Route outgoing calls
summary: Decide which dialled numbers go out to the carrier, through which trunks, and with which caller ID.
audience: admin
section: Calls and call flows
order: 30
reviewed: 0.27.44
pages:
  - /routing/outbound/
  - /routing/outbound/view/
covers:
  - frontend/src/app/(app)/routing/outbound/*
  - frontend/src/app/(app)/routing/outbound/view/*
  - frontend/src/components/routing/OutboundRouteFields.tsx
  - frontend/src/components/routing/PatternsEditor.tsx
  - frontend/src/components/routing/TrunkOrderEditor.tsx
  - backend/veyra/api/v1/routing.py
  - backend/veyra/telephony/routing.py
---

An **outbound route** says which numbers people may dial to the outside world and which trunk carries those calls. Without any outbound route, phones can only call other extensions.

Outbound routes are at [Telephony → Outbound Routes](app:/routing/outbound/). Only platform administrators can create or change them. You need at least one trunk first: see [Connect a SIP trunk](guide:connect-a-sip-trunk).

> **Important:** Create the emergency route first. See [Emergency calling (911)](guide:emergency-calling).

## How Veyra picks a route

- Routes are tried **in the order of the list**. The first route with a pattern that matches the dialled number carries the call.
- **Emergency routes always come first**, and the other routes cannot be moved above them.
- Within a route, the **trunks are tried in order**. If a trunk is unavailable, full (its **Maximum channels** reached) or rejects the call as congested, the next one is tried. If the far end is busy or does not answer, that is the result: Veyra does not try another trunk.
- If every trunk fails, the caller hears "all circuits are busy".
- Extensions always win over outbound patterns, so a pattern can never take over an internal number.

Use the arrows in the **Order** column to move a route up or down. Deploy afterwards.

## Dial patterns

Each route has one or more patterns. A pattern has three parts:

| Part | What it does |
|---|---|
| **Prefix (stripped)** | Digits the person dials first that are **not** sent to the carrier, such as an outside-line `9`. Optional |
| **Match** | The number itself, using pattern letters |
| **Prepend** | Digits added in front before the number is sent, such as `1` for long distance. Optional |

Pattern letters in **Match**:

| Letter | Means |
|---|---|
| `X` | any digit 0–9 |
| `Z` | any digit 1–9 |
| `N` | any digit 2–9 |
| `[2-5]` | one digit from the range or list |
| `.` | one or more of anything (only at the end) |
| `!` | zero or more of anything (only at the end) |

Examples for North America:

| Prefix | Match | Prepend | People dial | Sent to the carrier |
|---|---|---|---|---|
| | `NXXNXXXXXX` | | `5735550100` | `5735550100` |
| | `1NXXNXXXXXX` | | `15735550100` | `15735550100` |
| `9` | `NXXNXXXXXX` | `1` | `95735550100` | `15735550100` |
| | `NXXXXXX` | `573` | `5550100` | `5735550100` (seven-digit local dialling) |
| | `011.` | | `01144…` | `01144…` (international) |

A route can have up to 50 patterns. Two patterns in one route may not be the same.

## Create a route

1. Choose **New outbound route**.
2. Fill in:
   - **Name**, such as *Local and long distance*.
   - **Caller ID number** (optional): see below.
   - **Used by** (only shown when there are several organizations): **All organizations**, or one. A route of one organization is never used by the others' phones.
   - **Emergency route**: only for 911 and similar numbers.
   - **Dial patterns**: at least one. **Add pattern** adds a row.
   - **Trunks**: choose a trunk and **Add trunk**. Add a second trunk as a backup if you have one, and order them with the arrows. At least one trunk is required.
   - **Description** and **Enabled**.
3. Choose **Create route**. It is added at the end of its group (emergency or other).
4. Move it into place with the arrows, then **Deploy changes** in the top bar.

## Caller ID on outgoing calls

The number the called person sees is chosen in this order:

1. On an emergency route: the extension's emergency caller ID (see [Emergency calling (911)](guide:emergency-calling)).
2. The route's **Caller ID number**, if **Always send this caller ID** is ticked.
3. The extension's own **Outbound caller ID number** (set on the extension's page).
4. The route's **Caller ID number**.
5. The trunk's **Default caller ID**.
6. Otherwise, the caller's own number as is, which the carrier may reject or replace.

The **Caller ID** column shows **From the extension** when the route has no number of its own.

> **Tip:** Most carriers only accept numbers that belong to you. Set the trunk's **Default caller ID** to your main number so there is always a valid one.

## Warnings at the top of the page

Veyra checks the routes and lists problems under **Check these routes**:

- **No enabled emergency route**: 911 dialled from a phone will not reach a carrier. Fix this first.
- **Extensions with no emergency caller ID**: see [Emergency calling (911)](guide:emergency-calling).
- **Route … has no enabled trunk**: its calls will fail. A disabled trunk is shown struck through in the **Trunks** column.

## Who may use which route

By default every phone may use every route. To limit what some phones can dial (for example classroom phones that may only make local calls), see [Who can call where](guide:classes-of-service). Emergency routes always work, whatever the phone's class.

## If it does not work

- **The caller hears "all circuits are busy".** Every trunk on the route failed. Check the trunks' status on [SIP Trunks](app:/trunks/), and their **Maximum channels**.
- **The call reaches the wrong route.** An earlier route has a pattern that matches too. Move the more specific route higher.
- **The carrier rejects the call.** Check the number format it expects (with or without `1`, with `+`) and adjust **Prepend**, and check that the caller ID is one of your numbers.
- **Nothing happens when people dial.** The number may not match any pattern, or the change was not deployed.
