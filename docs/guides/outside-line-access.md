---
title: Let staff call out from outside
summary: Give people away from the building a number and PIN that let them dial out through your phone lines (DISA).
audience: admin
section: Calls and call flows
order: 45
reviewed: 0.27.81
checked: 2026-11-01
pages:
  - /disa/
covers:
  - frontend/src/app/(app)/disa/*
  - backend/veyra/api/v1/disa.py
---

**Outside line access** (often called DISA) lets someone call a number from outside, enter a PIN, hear a dial tone and make a call through your lines. The person they call sees your number, not theirs.

> **Risk:** anyone who gets the PIN can run up call charges on your account. This is a common target for phone fraud. Only add it if people really need it, and limit what it can reach.

## Before you start

Create a [class of service](guide:classes-of-service) just for this. Allow only the outbound routes it needs, set a limit on simultaneous calls, and leave out international routes. A call through outside line access can only use what this class allows.

## Set it up

1. Go to [Outside Line Access](app:/disa/) and choose **New outside line access**.
2. Enter a **Name** and a **PIN** of 6 to 10 digits. Repeated digits and runs such as `123456` are refused. Veyra can't show the PIN again, so note it somewhere safe.
3. Choose the **Class of service**.
4. Enter the **Caller ID number** these calls should show. A route that forces its own number overrides it.
5. Save, then point an [inbound route](guide:route-incoming-calls) or a [menu](guide:phone-menus) key at it by choosing **Outside line access** as the destination.
6. [Deploy the configuration](guide:deploy-changes).

To use it, call the number, enter the PIN when asked, wait for the dial tone and dial the number as you would from a desk phone.

## What protects it

- **Lock-out:** five wrong PINs in a row lock that line for 15 minutes, even if the caller hangs up between tries. During a lock-out the right PIN doesn't work either, so someone guessing can keep staff out for a while. Wrong PINs and lock-outs are written to the Asterisk log.
- **Only outside calls:** the caller can reach your outbound routes, but not your phones, voicemail or feature codes.
- **Audit log:** adding or changing a line is recorded; the PIN isn't.

## Limits

- **No 911:** emergency numbers are refused, because the 911 center would get the wrong address or none. Callers must use their own phone's emergency service. Tell the people you give this to.
- **PIN sharing:** there's one PIN per line, so Call History can't show which person made a call. Give groups their own line if you need to tell them apart.
- **Import and export:** routes that point here export as `disa`, and that value can't be imported. Set those routes by hand after importing.
