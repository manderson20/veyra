---
title: Wake-up calls
summary: Have a phone ring at a chosen time and play a message, once or every day.
audience: all
section: Calls and call flows
order: 46
reviewed: 0.27.82
checked: 2026-11-01
pages:
  - /extensions/view/
covers:
  - frontend/src/components/extensions/WakeupCard.tsx
  - backend/veyra/telephony/wakeup.py
---

A wake-up call rings a phone at a chosen time and plays a short message. Use one as a reminder, or for guests or staff who stay overnight.

## From a phone

1. Dial `*64`. Your organization may have changed this code under [Feature Codes](app:/feature-codes/).
2. Enter the time as four digits on the 24-hour clock, such as `0630` for 6:30 AM or `1415` for 2:15 PM.

A call set this way happens once, at the next time the clock shows that time. To remove all of the phone's wake-up calls, dial `*65`.

## From the web

Open the **Wake-up calls** card on the **Find me / follow me** tab of an extension, or in My Phone. Enter a time, tick **Every day** if it should repeat, and choose **Add**. A front desk can set calls for other phones this way. Changes apply at once, with no deployment.

## What happens

- The time is in your organization's time zone.
- The phone rings even if Do Not Disturb or call forwarding is on.
- If nobody answers, Veyra tries again five minutes later, three tries in all. The card then shows **Last one missed**.
- If the server was down at that time and more than 30 minutes have passed, the call is skipped rather than ringing late. The card shows **Last one skipped**.
- A phone can have up to five wake-up calls.
