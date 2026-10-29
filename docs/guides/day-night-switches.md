---
title: Day/night switches (call flows)
summary: Give staff a switch, on the web or on a phone key, that sends calls to a second destination until it is switched back.
audience: admin
section: Calls and call flows
order: 50
reviewed: 0.27.44
pages:
  - /routing/call-flows/
  - /routing/call-flows/view/
covers:
  - frontend/src/app/(app)/routing/call-flows/*
  - frontend/src/app/(app)/routing/call-flows/view/*
  - frontend/src/components/callflow/CallFlowFields.tsx
  - backend/veyra/api/v1/call_flows.py
  - backend/veyra/telephony/switches.py
---

A **call flow** is a switch with two positions. Normally, calls that reach it go to one destination. While it is **switched**, they go to another. Staff flip it by hand: from Veyra, or from a desk phone with a code or a lit button.

Typical uses:

- **Night mode:** the front office switches the main number to an after-hours message when the last person leaves.
- **Emergency closure:** the main number plays a closure announcement on a snow day.
- **Cover:** calls to a desk go to a colleague while someone is out.

For opening hours that follow a fixed schedule, use [Business hours and holidays](guide:business-hours-and-holidays) instead. The two can be combined.

Call flows are at [Telephony → Call Flows](app:/routing/call-flows/).

## Create a call flow

1. Choose **New call flow**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, such as *Night mode*, and a **Code index** from 0 to 99. The index must be unique within the organization; it is the number dialled after the toggle code.
4. Choose **Create call flow**. Veyra opens its page.
5. Set the two destinations:
   - **Normally, calls go to**
   - **While switched, calls go to**

   Both offer the same kinds as an inbound route (extension, voicemail, IVR menu, ring group, queue, announcement and so on), plus **Hang up**.
6. Optionally set a **PIN** of 4 to 10 digits, which a phone must enter before it can switch.
7. Choose **Save**, then **Deploy changes** in the top bar.

A new call flow starts with both destinations set to hang up, so set them before you send calls to it.

## Send calls into the call flow

A call flow only affects calls that are sent to it. Choose **Call flow** as the destination of:

- an [inbound route](guide:route-incoming-calls), for example your main number,
- or anywhere else Veyra asks for a destination, such as an IVR menu key.

## Switch it

Switching takes effect immediately. No deployment is needed.

- **In the list:** turn the switch in the **Switched** column on or off. The **Calls go to** column shows where calls go right now.
- **On the call flow's page:** **Switch now**, and **Back to normal** to return. The **Right now** panel shows the state, who switched it and when.
- **From a phone:** dial the call-flow toggle feature code (`*28` by default) followed by the index, for example `*281`. Dial it again to switch back. If the call flow has a PIN, the phone asks for it. The exact code is shown in the **Phone code** column.
- **With a lit button:** program a busy lamp field (BLF) key with the same code on a phone (for example the front-office phone). The light is on while the call flow is switched, so staff can see the state at a glance.

## Good to know

- The **Status** column shows **Ready**, **Disabled**, or a count of problems. Open the call flow to see them: a destination that no longer exists, or the toggle feature code turned off at [Feature Codes](app:/feature-codes/) (the **Phone code** column then shows **Code disabled**).
- **Enabled** off leaves the call flow out of the phone system, and routes that point at it are flagged.
- Renaming a call flow does not change its internal name (the **Context** shown under **Information**) or its phone code.
- A call flow that is still used by a route, menu, group or announcement cannot be deleted. Change those first.
