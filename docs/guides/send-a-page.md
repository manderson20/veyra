---
title: Create and send pages
summary: Combine paging zones into pages such as an all-call, give them a recording, and start them from a phone, from Veyra, from a bell or from another system.
audience: admin
section: Paging and bells
order: 20
reviewed: 0.27.44
pages:
  - /paging/
covers:
  - frontend/src/app/(app)/paging/*
  - frontend/src/components/paging/PageDialog.tsx
  - backend/veyra/api/v1/pages.py
---

A **page** is a named announcement into one or more [paging zones](guide:paging-zones). It carries either:

- **live audio**: whoever dials the page's number talks, as on an intercom, or
- **a recording**: a bell, a chime or a spoken message from the audio library, played into the zones when the page is started.

Typical pages are an *All call* over every zone, *Building A and B* for two buildings, or a *Fire drill* recording. Pages are listed under [Telephony → Pages](app:/paging/).

> **Warning:** Paging over the phone system is not a life-safety notification system. The alert tones are meant for drills and attention, not as a replacement for a fire alarm.

## Before you start

- Create the zones first, under [Paging Zones](app:/paging-zones/).
- For a page with a recording, add the recording to the audio library under [Audio](app:/prompts/). The Audio page also offers built-in bells, chimes and alert tones that you can add to the library.

## Create a page

1. Choose **New page**.
2. Fill in the form:

| Field | What to enter |
|---|---|
| **Name** | For example *All call*. Required, and unique in the organization. |
| **Number to dial (optional)** | The number phones dial to start the page. Leave it blank for a page that is only started from Veyra, a bell or the API. It shares the numbering plan with extensions, groups and zones. |
| **Zones** | Tick every zone the page reaches (up to 25). |
| **Audio** | Leave **Live: the caller's voice**, or choose a recording. Only a page with a recording can be started from Veyra, by a bell schedule or by another system. |
| **Repeat the recording** | 1 to 5 times. Only with a recording. |
| **Priority** | **Normal**, **Priority (interrupts calls on Poly phones)** or **Emergency**. |
| **Longest page (seconds)** | 5 to 600, default 120. |
| **Who may start it from a phone** | **Everyone in the organization**, **Listed phones only** (add them under **Phones allowed to start it**), or **Only from Veyra (interface, bells, API)**. |
| **Description** | Optional; shown under the name in the list. |
| **Play a tone before the page** | On by default: a short tone warns people before the page starts. |
| **Enabled** | A disabled page cannot be started. |

3. Choose **Create page**.
4. If the page has a number, use **Deploy changes** in the top bar so phones can dial it.

## Start a page

- **From a phone:** dial the page's number. For a live page, speak after the tone and hang up when you are done. For a page with a recording, you hear a short beep and can hang up: the recording plays into the zones by itself. A phone that is not allowed to start the page hears an "invalid" message.
- **From Veyra:** **Send now** on the page's row (shown for pages with a recording, to people allowed to send pages). The recording plays into the zones at once.
- **From a bell schedule:** see [Ring bells from a calendar](guide:bell-schedules).
- **From another system:** a door controller, a building-management system or a script can start a recorded page through Veyra's API with an integration token that may *Start pages*. Tokens are created under [System → Integrations](app:/system/integrations/). A device with a relay or a SIP line can also simply dial the page's number.

Phones and speakers in each zone play the page together.

## Recent pages

The **Recent pages** card lists the last pages sent, with the zones, how each was started (from a phone, the interface, a bell or the API), who started it, and whether it **started** or **failed**. Entries are kept for 90 days by default; a platform administrator can change that on the **Retention** card under [Settings](app:/settings/).

## Reading the list

The **Status** column shows **Ready**, **Disabled**, or the first problem found:

- *No zones: the page reaches nothing.* Tick at least one zone.
- *A zone of this page is disabled.* Turn the zone back on, or remove it from the page.
- *Only members may start this page, and it has none.* Add phones, or change **Who may start it from a phone**.
- *The recording no longer exists.* Choose another recording.

**Send now** answers *This page plays live audio; dial its number from a phone to page* for a page without a recording.

## Delete a page

Use the bin icon on the page's row, then deploy the changes so phones no longer reach its number. Bell schedules that use the page stop ringing it.
