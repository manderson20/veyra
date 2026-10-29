---
title: Emergency calling (911)
summary: Set up 911 so it dials directly, sends the right number and location, alerts people on site, and reaches the caller on a callback.
audience: admin
section: Calls and call flows
order: 80
reviewed: 0.27.44
pages:
  - /system/emergency/
covers:
  - frontend/src/app/(app)/system/emergency/*
  - backend/veyra/api/v1/emergency.py
  - backend/veyra/emergency/service.py
  - frontend/src/components/routing/OutboundRouteFields.tsx
  - frontend/src/components/routing/TrunkFields.tsx
---

> **Warning:** Emergency calling is safety-critical. Veyra checks your configuration against its own list, but it does **not** certify that 911 works. You must test it with your carrier and make sure you meet the laws that apply to you. This guide is not legal advice.

In the United States, two federal rules apply to phone systems with many lines (Kari's Law and RAY BAUM'S Act):

- People must be able to dial **911 directly**, without an outside-line prefix such as 9.
- When someone dials 911, the system must **notify someone on site** (a front office or security desk).
- The 911 call must carry a **dispatchable location**: the street address plus details such as the building, floor or room.

State laws may add requirements, and other countries have their own emergency numbers and rules.

Veyra handles this in four places. Work through them in order, then check the result at [System → Emergency Calling](app:/system/emergency/).

## 1. Sites: address and emergency number

Open [Directory → Sites](app:/sites/) and, for each site (each campus or building with its own address):

- Enter the full **civic address**: **Street**, **City**, **State or region**, **Postal code**.
- Enter the **Emergency caller ID number**: the number the 911 center sees and calls back. This is often called the **ELIN**. It must be one of your numbers, and your carrier must have it registered with this site's address in their E911 service.

Ask your carrier to register each site's emergency number and address before going further. Veyra cannot do that part.

## 2. Extensions: site and location

On each extension's page under [Extensions](app:/extensions/):

- Choose its **Site** and, where you have them, its **Building**.
- Fill in **Location (dispatchable)**, such as *Room 101, first floor*.
- Leave **Emergency caller ID number** empty to use the site's number. Fill it in only when this phone needs a different emergency number (for example a building with its own registered number). The extension's number wins over the site's.

## 3. The emergency route

Open [Telephony → Outbound Routes](app:/routing/outbound/) and choose **New outbound route** (platform administrators only):

1. **Name**: such as *Emergency*.
2. Tick **Emergency route**. Emergency routes are always tried before every other route, cannot be moved below them, and work for every phone whatever its [class of service](guide:classes-of-service).
3. **Dial patterns**: add `911` and, if your carrier supports test calls, `933`, with no prefix. If people are used to dialling 9 for an outside line, also add a pattern with **Prefix (stripped)** `9` and **Match** `911`, so `9911` reaches 911 too.
4. **Trunks**: add your main trunk and, if you have one, a second trunk as a backup. The backup is tried when the first trunk is unavailable.
5. **Caller ID number**: optional, used for phones that have no emergency number from steps 1 and 2.
6. **Create route**, then **Deploy changes** in the top bar.

The Outbound Routes page warns you when there is **no enabled emergency route**, and when extensions have no emergency caller ID.

### One route per site (optional)

If your sites use different trunks, create one emergency route per site and choose the site under **For the phones of**. A site's route is tried first for that site's phones and passes other phones on to the next emergency route.

> **Important:** Always keep one emergency route for **Every site** as well. Routes bound to a site are tried before it.

### Keep a line free for 911

On each trunk the emergency route uses, set **Maximum channels** to the number of calls your carrier allows and **Channels kept for emergency calls** to at least 1 (see [Connect a SIP trunk](guide:connect-a-sip-trunk)). Ordinary calls then never use the last channel, so a 911 call can get out even when every other line is busy.

## 4. On-site notification and callback

At [System → Emergency Calling](app:/system/emergency/), choose **Open** on a site. (Changing these settings needs the emergency-calling management permission.)

- **This address is registered with the carrier's E911 service for the ELIN above**: tick it once the carrier has confirmed. Your name and the date are recorded.
- **Responder extension**: the phone that rings when the 911 center calls back and Veyra cannot tell who made the call, or the callback window has passed.
- **Callback window (minutes)**: how long after a 911 call a call to the site's emergency number rings the phone that dialled 911 (1 to 1440, 30 by default).
- **Notify by email**: one address per line. Email must be set up under Settings first.
- **Ring these extensions**: extension numbers, separated by commas (up to 20). These phones ring when someone dials 911, show the caller's extension as the name, and hear it read out.
- **Send the emergency.call webhook**: for your own systems, through the webhooks set up in Veyra.

Choose **Save**, then **Deploy changes** in the top bar if it appears (the responder and callback window are part of the phone system's configuration).

> **Note:** On-site notification by phone, email or paging is not a life-safety mass notification system. Do not rely on it as one.

## 5. Test

1. **Test the notification now** sends the real notifications (email, ringing phones, webhook), marked as a test with the number 933. Check that everyone received them. The notification check passes once a test reached at least one recipient.
2. Arrange a test call with your carrier (933 where they support it, or a scheduled 911 test). Ask the 911 center to read back the number and address they see.
3. Under **Carrier test call**, type what they read back in **Result** and choose **Record as passed** or **Record as failed**.

Repeat the carrier test at least once a year, and after any change to trunks, sites or emergency numbers.

## Readiness

The **Sites** table shows each site as **ready** or how many checks are **missing**. Open a site to see every check:

- An enabled emergency route with a trunk reaches this site
- Every emergency trunk keeps a channel free for emergency calls (advice only; it does not stop a site being ready)
- The site has an emergency caller ID (ELIN or registered DID)
- The site has a civic address
- The address is attested as registered with the carrier's E911 service
- Every extension of the site has a location (building or floor/room)
- On-site notification recipients are set
- The notification was tested
- A test call with the carrier succeeded within the last year

**Ready** means Veyra's checks pass. It does not mean the carrier delivers the right address: only the carrier test shows that.

## What happens on a 911 call

- The call goes out through the first matching emergency route, ignoring any class of service and channel limit, and rings for up to 120 seconds.
- The number sent is the extension's **Emergency caller ID number**, else the site's, else the usual outgoing caller ID. Hiding the number (such as `*67`) has no effect on an emergency call.
- The notifications from step 4 go out, and the call is listed under **Emergency calls** with the caller's extension, the number dialled, the location and who was notified. Test notifications are marked **test**, real calls **live**.
- When the 911 center calls the emergency number back within the callback window, the phone that made the call rings, even if the number has no inbound route of its own. After the window (or when Veyra cannot tell who called), the **Responder extension** rings. Without a responder, the number's normal [inbound route](guide:route-incoming-calls) answers, and a number without an inbound route is not answered, so set a responder.

## If something is missing

- **"No enabled emergency route"**: create the route in step 3, or turn it back on.
- **Extensions missing a location**: the readiness check lists up to ten of them; fill in their **Location (dispatchable)** or **Building**.
- **The notification test fails**: check that email is set up, and that the extensions listed under **Ring these extensions** exist in the site's organization.
- **The 911 center sees the wrong address**: the address registered with the carrier for that number is wrong. Correct it with the carrier, then test again.
