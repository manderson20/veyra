---
title: Business hours and holidays
summary: Set opening hours, holidays and closed days, so calls outside them go to a different destination.
audience: admin
section: Calls and call flows
order: 40
reviewed: 0.27.49
checked: 2026-10-30T15:10Z
pages:
  - /routing/time-conditions/
  - /routing/time-conditions/view/
covers:
  - frontend/src/app/(app)/routing/time-conditions/*
  - frontend/src/app/(app)/routing/time-conditions/view/*
  - frontend/src/components/routing/TimeConditionFields.tsx
  - frontend/src/components/routing/RangesEditor.tsx
  - frontend/src/components/routing/HolidaysEditor.tsx
  - backend/veyra/api/v1/routing.py
  - backend/veyra/telephony/routing.py
  - backend/veyra/telephony/switches.py
---

A **time condition** is a schedule: the hours you are open, plus holidays and other closed days. On its own it does nothing. You pick it on an [inbound route](guide:route-incoming-calls), and the route then sends calls during the open hours to its normal destination and calls at any other time to its after-hours destination.

Time conditions are at [Telephony → Time Conditions](app:/routing/time-conditions/). The list shows whether each one is **Open now** or **Closed now**, its hours, and how many routes use it.

## Create a time condition

1. Choose **New time condition**.
2. If you manage several organizations, choose the **Organization**.
3. Fill in:
   - **Name**, such as *Office hours*.
   - **Time zone**: leave it empty to use the organization's time zone, or enter a name such as `America/Chicago`.
   - **Open hours**: see below.
   - **Holidays and closed days**: see below.
   - **Override code index** and **Override PIN** (optional): see *Open or close early*.
4. Choose **Create time condition**.
5. Open an inbound route, pick the time condition, choose the **After-hours destination**, save, and choose **Deploy changes** in the top bar.

## Open hours

Each range is a set of days and a time: click the day buttons (**Mon** to **Sun**) to turn days on or off, and set **From** and **Until**. A new time condition starts with Monday to Friday, 08:00 to 17:00.

- **Add range** adds another, for example Saturday 09:00 to 12:00.
- A call counts as open if it falls within any range. **Until** is not included: with 08:00 to 17:00, a call at 17:00 is after hours.
- A range cannot cross midnight. For hours such as 22:00 to 06:00, add two ranges: 22:00 to 23:59, and 00:00 to 06:00 on the following days.
- A time condition needs at least one range, and can have up to 50.

## Holidays and closed days

On these days the condition is closed all day, whatever the open hours say.

- **Add holiday** adds a date that repeats. Under **Repeats**, choose:
  - **Same date every year**, such as 25 December. Tick **Several days in a row** for a period such as 21 December to 2 January (it may cross New Year).
  - **A weekday of a month**, such as the **Fourth** **Thursday** of **November** (Thanksgiving) or the **Last** **Monday** of **May** (Memorial Day). The last weekday of February is not supported.
- **Add closed day** adds a one-off date, such as a snow day, with an optional **Until** date for a period such as this year's winter break.

Each holiday shows a plain description below it so you can check it. A time condition can have up to 100.

> **Tip:** One-off closed days stay in the list after they pass. Remove old ones from time to time.

## Open or close early

On the time condition's page, the **Override** panel shows what the schedule says and what callers get right now.

- **Force open** or **Force closed** changes what callers get immediately. No deployment is needed.
- With **Temporary: ends when the schedule next changes state** ticked (the default), the override ends by itself at the next opening or closing time. Untick it to keep the override until someone chooses **Back to the schedule**.
- The panel shows who forced it and when. The list shows a **Forced** badge.

People can also do this from a phone. Give the time condition an **Override code index** from 0 to 99, unique within the organization. Phones then dial the time-condition override feature code (`*27` by default) followed by the index, for example `*271`, to force the opposite state until the schedule changes. Dialling it again clears it. A busy lamp field (BLF) key programmed with that code lights while the condition is forced. With an **Override PIN** (4 to 10 digits), the phone asks for the PIN first.

## Editing and deleting

Change the schedule on the time condition's page, then **Save changes** and deploy. The **Information** panel lists the open hours and holidays as Veyra understands them.

A time condition used by an inbound route cannot be deleted. Remove it from those routes first.

## If it does not work

- **Calls go after hours when you are open, or the reverse.** Check the time zone shown under **Information**, and whether the condition is forced (**Callers get** says *forced*).
- **A schedule change has no effect.** It needs **Deploy changes**. Only **Force open** and **Force closed** take effect without a deployment.
- **The phone code does nothing.** Check the code on the time condition's page under **Phone code**, and that the feature code is turned on at [Feature Codes](app:/feature-codes/).

For a switch that people flip by hand rather than a schedule (for example "night mode" when the office closes), see [Day/night switches](guide:day-night-switches).
