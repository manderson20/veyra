---
title: Route incoming calls
summary: Decide where each of your phone numbers (DIDs) rings, with a different destination outside business hours.
audience: admin
section: Calls and call flows
order: 20
reviewed: 0.27.45
checked: 2026-10-30T15:10Z
pages:
  - /routing/inbound/
  - /routing/inbound/view/
covers:
  - frontend/src/app/(app)/routing/inbound/*
  - frontend/src/app/(app)/routing/inbound/view/*
  - frontend/src/components/routing/InboundRouteFields.tsx
  - frontend/src/components/routing/DestinationPicker.tsx
  - backend/veyra/api/v1/routing.py
  - backend/veyra/telephony/routing.py
---

Each phone number your carrier delivers to Veyra is called a **DID** (direct inward dialing number). An **inbound route** says where calls to one DID go: a person's phone, a voicemail box, a menu, a ring group and so on. Calls to a number without a route are refused.

Inbound routes are at [Telephony → Inbound Routes](app:/routing/inbound/). You need a working trunk first: see [Connect a SIP trunk](guide:connect-a-sip-trunk).

## Before you start

- Get the list of your numbers from the carrier, and ask **in what form they send them**: ten digits (`5735550100`), eleven (`15735550100`) or with a plus (`+15735550100`).
- Create what the calls should reach first (the extension, ring group, menu and so on).
- If calls should go elsewhere after hours, create the [time condition](guide:business-hours-and-holidays) first.

## Create a route

1. Choose **New inbound route**.
2. If you manage several organizations, choose the **Organization** that owns the number.
3. Fill in the route:
   - **DID:** the number, digits with an optional leading `+` (2 to 20 digits). Spaces, dashes, dots and brackets are removed for you. Enter `any` for a catch-all route that takes calls to every number without a route of its own.
   - **Trunk:** leave **Any trunk** unless the number should only be answered when it arrives on one particular trunk.
   - **Destination:** first the kind, then which one. See the table below.
   - **Time condition:** leave **Always (no time condition)**, or pick one. With a time condition, an **After-hours destination** appears, and it is required.
   - **Caller ID prefix:** optional text put in front of the caller's name on the ringing phone, such as `Sales:`, so people can see which number was called. Up to 40 letters, digits, spaces and `. ' & ( ) - :`.
   - **Description** and **Enabled**.
4. Choose **Create route**, then **Deploy changes** in the top bar.

### Destinations

| Kind | Calls go to |
|---|---|
| **Extension** | One phone (and its forwarding and voicemail as set on the extension) |
| **Voicemail of an extension** | Straight to that extension's voicemail; only extensions with a voicemail box are listed |
| **Shared voicemail inbox** | A shared box, such as a department's |
| **IVR menu** | A "press 1 for…" menu |
| **Ring group** | Several phones at once or in turn |
| **Call queue** | A queue with hold music and agents |
| **Announcement** | A recorded message |
| **Conference room** | A conference room |
| **Call flow** | A day/night switch: see [Day/night switches](guide:day-night-switches) |
| **Fax to email** | A fax inbox |
| **Custom dialplan** | A custom context (platform administrators only; see [Deploy changes](guide:deploy-changes)) |
| **Dial-by-name directory** | Callers spell a name on the keypad |

## How numbers are matched

- **North American numbers in any form.** A ten-digit DID also answers calls the carrier sends as `1` + ten digits or `+1` + ten digits, and the other way round. You cannot create two routes for the same number in different forms with the same trunk setting. The route's page shows the forms under **Matches**. Numbers of other lengths must match exactly.
- **One route per number per trunk setting.** You can have one route for a number on **Any trunk** and another for the same number on a specific trunk. On that trunk, the trunk's own route wins.
- **The catch-all.** An `any` route only takes calls whose number has no route of its own.

## Business hours

With a **Time condition**, calls during the open hours go to the **Destination**, and calls at any other time, and on holidays, go to the **After-hours destination**. The list shows each route's destination by name, with its kind (such as *IVR menu* or *Ring group*) underneath, and the time condition and closed-hours destination.

To open or close early for a day (a snow day, an assembly), use the time condition's **Force open** or **Force closed** instead of editing the route. See [Business hours and holidays](guide:business-hours-and-holidays).

## Editing and deleting

Open a route from the list to change it, then **Save changes** and deploy. The **Information** panel shows the forms of the number that match, the destination and the after-hours destination.

**Delete** removes the route. After the next deployment, calls to that number are no longer answered.

## If it does not work

- **The route shows "No destination" in red.** What it pointed to was deleted or disabled. Calls to the number are refused until you choose a new destination.
- **Calls to a number are refused, but the route exists.** Check that the route is **Enabled** and deployed, that the carrier sends the number in a form the route matches (see the call details in Call History), and that a **Trunk** restriction is not excluding the trunk the call arrives on.
- **Calls go to the after-hours destination during the day.** Check the time condition's time zone and hours, and whether someone left it **Forced closed**.
- **A caller is rejected straight away.** They may be on the organization's block list: see [Block callers](guide:block-callers).

> **Note:** Organization administrators can create and change inbound routes for their own organization. The **Trunk** field can only be changed by people allowed to see the trunks.
