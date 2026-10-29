---
title: Ring bells from a calendar
summary: Let a Google Calendar or any iCal calendar ring your school bells through the paging speakers.
audience: admin
section: Paging and bells
order: 30
reviewed: 0.27.45
pages:
  - /bells/
  - /calendars/
covers:
  - frontend/src/app/(app)/bells/*
  - frontend/src/app/(app)/calendars/*
  - frontend/src/components/bells/CalendarDialog.tsx
  - backend/veyra/api/v1/bell_schedules.py
  - backend/veyra/api/v1/calendars.py
  - backend/veyra/bells/*
---

Veyra rings bells from a calendar you already keep. You put the bell times in a calendar (for example a Google Calendar called *Bell schedule*, with an event for each period). Veyra checks the calendar every few minutes, and when an event starts (or ends, or both, as you choose) it plays a recorded page, such as a school bell, into the paging zones.

Changing the schedule then means editing the calendar: a late-start day, an assembly schedule or a holiday is just different events.

It takes three pieces:

1. a **page with a recording**: the bell sound and the zones it plays in (see [Create and send pages](guide:send-a-page)),
2. a **calendar** in Veyra, linked to your calendar, and
3. a **bell schedule** that connects the two.

> **Warning:** Bells over the phone system are not a life-safety notification system. Use them for class changes and drills, not as a replacement for a fire alarm.

## 1. Make the bell page

Create a page with the zones that should hear the bell and a recording as its **Audio**, for example the built-in school bell (add it to your library from [Audio](app:/prompts/) first). Give it no number if only the bells should start it, and choose **Only from Veyra (interface, bells, API)** under **Who may start it from a phone**.

## 2. Add the calendar

You need the calendar's iCal address.

- **Google Calendar:** in Google Calendar's settings, open the calendar and copy its **Secret address in iCal format**. It ends in `basic.ics`. Anyone with this address can read the calendar, so treat it like a password.
- **Other calendars:** any iCal (`.ics`) feed works: Microsoft 365 published calendars, school information systems, and so on.

Then, under [Telephony → Calendars](app:/calendars/):

1. Choose **Add calendar**.
2. Enter a **Name**, for example *Bell schedule*.
3. Paste the **Feed address**. It must start with `https://`, `http://` or `webcal://`. The address is stored encrypted and never shown again; the list shows only the server's name.
4. **Check every (minutes)**: 1 to 60, default 3.
5. **Time zone**: leave it empty to use the calendar's own. Enter a name such as `America/Chicago` only for feeds that carry no time zone.
6. Choose **Add calendar**. It is fetched within a minute.

The list shows when each calendar was **Checked**, how many **Events (48 h)** it has in the next two days (choose the number to see them), how many **Bell schedules** use it, and its **Status**. **Fetch now** checks it at once.

> **Tip:** Recurring events (every school day at 8:05) work. Veyra reads the next two days of events at every check.

## 3. Create the bell schedule

Under [Telephony → Bell Schedules](app:/bells/):

1. Choose **New bell schedule**.
2. Fill in the form:

| Field | What to enter |
|---|---|
| **Name** | For example *Class periods*. |
| **Calendar** | The calendar from step 2. |
| **Page to ring** | The bell page. Only pages with a recording are offered. |
| **Events to ring** | Which events ring, by their title. `*` (the default) rings every event. `Bell:*` rings only events whose title starts with *Bell:*. Upper and lower case do not matter. |
| **Ring** | **When an event starts**, **When an event ends**, or **At start and end**. |
| **Late tolerance (seconds)** | 0 to 900, default 90. If the server was busy or restarting, a bell up to this late is still rung; a later one is skipped rather than rung at the wrong time. |
| **Include all-day events** | Off by default, so a holiday marked as an all-day event does not ring a bell at midnight. |
| **Enabled** | Turn it off to pause the bells, for example over the summer. |

3. Choose **Create schedule**.

Each event rings once at each time chosen under **Ring**. Veyra checks for due bells every few seconds.

## Check it

- The **Next ring** column shows the next event that will ring and when.
- **Ring now** plays the page at once, to test the sound and the zones.
- **History** shows the last 50 rings of the schedule, each with its event, when it was due and whether it **started** or **failed**.
- The **Status** column shows **Ready**, **Disabled** or the first problem, for example *The calendar could not be fetched*, *The page has no recording; bells need one* or *The page is disabled*.

## If a bell does not ring

- **The calendar shows an error:** open the calendar, paste the address again and save. For Google, make sure you copied the *secret* iCal address, not the public one, and that it has not been reset in Google Calendar since.
- **The bell rings at the wrong hour:** the feed has no time zone; set **Time zone** on the calendar.
- **No events in the next 48 hours:** choose the number in **Events (48 h)** to see what Veyra read. Check the event titles against **Events to ring**.
- **Ring now works but the scheduled bell does not:** check that both the calendar and the schedule are enabled, and that the event is not an all-day event.

## Removing things

- Deleting a bell schedule keeps the calendar and the page.
- Removing a calendar also removes the bell schedules that use it. Your calendar itself is not touched.
