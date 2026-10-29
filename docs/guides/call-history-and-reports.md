---
title: Call history and reports
summary: Look up any call, export the history, build your own reports and have them emailed on a schedule.
audience: admin
section: Calls and call flows
order: 100
reviewed: 0.27.44
pages:
  - /call-history/
  - /reports/
covers:
  - frontend/src/app/(app)/call-history/*
  - frontend/src/app/(app)/reports/*
  - frontend/src/components/reports/Builder.tsx
  - frontend/src/components/reports/Overview.tsx
  - frontend/src/components/reports/SavedReports.tsx
  - backend/veyra/api/v1/call_history.py
  - backend/veyra/api/v1/reports.py
  - backend/veyra/reporting/builder.py
  - backend/veyra/reporting/schedule.py
---

Veyra keeps a record of every call: who called whom, who answered, how long it rang and how long people talked. **Call History** finds single calls, for example when a parent says nobody answered. **Reports** adds them up: busy hours, missed calls per office, how long queue callers wait.

## Who can do what

| Permission | Lets someone | By default |
|---|---|---|
| View the call history of the organization | Open Call History | Organization and site administrators, technicians, read-only users |
| Export the call history as CSV | **Export CSV** on Call History | Organization administrators |
| View call reports | Open Reports, run and export reports | Organization and site administrators, read-only users |
| Save, share and schedule reports | **Save report…**, **Send now**, delete | Organization and site administrators |

## Find a call

1. Open [Telephony → Call History](app:/call-history/).
2. Choose the period: **Last 24 hours**, **Last 7 days**, **Last 30 days**, **Last 90 days**, or **Custom range** with two dates.
3. Narrow it down with the search box (a number, a name or an extension), **All directions** (*Internal*, *Inbound*, *Outbound*) and **All outcomes**:

| Outcome | Means |
|---|---|
| **Answered** | Someone picked up |
| **Missed** | It rang and nobody answered |
| **Busy** | The other side was busy |
| **Failed** | The call could not be placed |
| **Voicemail** | It ended in voicemail |
| **Abandoned** | The caller hung up while waiting, for example in a queue |
| **Blocked caller** | The number is on the blocked list |
| **Not allowed** | The phone's class of service does not allow the number |

4. Click a call to see the details: direction and trunk, the number dialled (DID), who answered, ringing and talking time, and each *leg* of the call as the phone system saw it. If the call was recorded (a record icon in the list) and you may listen to recordings, the recording plays here.

Calls appear a few seconds after they end. The relative periods are fixed when the page opens; **Refresh** brings them up to now.

**Export CSV** downloads the calls that match the current filters, up to 100,000 rows.

Veyra keeps the call history for 400 days by default. A platform administrator can change that under [Settings](app:/settings/), in the **Retention** card.

## The reports overview

[Telephony → Reports](app:/reports/), **Overview** tab, summarises a period (**Last 7 days** to **Last 365 days**, or **Custom range**), optionally for one organization:

- **Calls**, **Missed**, **Average ring / talk**, and the share of inbound calls answered within 20 seconds.
- **Calls per day** by direction, and **Busiest hours** by weekday and hour.
- **Extensions**: answered, missed and talk time per extension.
- **Trunks**: inbound and outbound calls per carrier connection, and **Most at once**, the most calls up at the same time. Compare it with the number of channels your carrier sells you.
- **Queues**: callers, answered, **Hung up waiting**, **Average wait**, **Answered within 20 s**, **Left by the menu** (callers who used the break-out menu), and per agent the calls answered and time logged in and paused.

Days and hours are in the organization's time zone.

## Build a report

On the **Build** tab:

1. Choose the **Period**, from **Today** to **This year**, or **Custom dates**.
2. Choose **Group by**, for example **Day**, **Hour of day**, **Called extension**, **Number dialled (DID)**, **Queue** or **Caller number**. Add **Then by** and **And by** for up to three levels.
3. Tick the **Measures**: **Calls**, **Answered**, **Missed**, **Voicemail**, **Answer rate**, **Average ring**, **Total ring**, **Average talk**, **Total talk**, **Answered within service level** (then set the **Service level (seconds)**).
4. Open **Filters** to include only some calls: directions, outcomes, extensions (either side of the call), numbers dialled, queues, ring groups, trunks, **Caller number contains**, **At least this much talk (seconds)**, and **Business hours**: inside or outside the hours and holidays of a time condition you choose.
5. Choose **Show as** (**Table**, **Bars and table**, **Line and table**), the sort order and **Show at most (rows)** (up to 5000).
6. Choose **Run**. Under the chart, **Chart** picks which measure the chart shows; the table always shows them all, with the totals below.

**Export CSV** downloads the result.

## Save and email a report

1. On the **Build** tab choose **Save report…**.
2. Enter a **Name** and optionally a **Description**.
3. **Shared with the organization**: on, everyone who may see reports can open it; off, only you and report editors.
4. Switch on **Email it on a schedule** to send the result as a CSV: **How often** (**Every day**, **Every week**, **Every month**), **At** (the hour, in the organization's time zone), **On** (weekday) or **On day** (day of the month; a shorter month sends on its last day), and **Email to**, one address per line, up to 20.
5. Choose **Save**.

The **Saved** tab lists the reports with their schedule, the next and last email, and any sending error. **Open** loads a report into the builder; save it again to change it, or tick **Save as a new report**. **Send now** emails a scheduled report at once.

> **Warning:** the CSV contains call data, including phone numbers. Send it only to people allowed to see it.

Emails need outgoing mail to be set up in the **Email delivery** card under [Settings](app:/settings/). Without it, sending fails and the error shows in the **Last sent** column.

## When it does not work

- **A call is missing**: widen the period, clear the filters, and check the organization filter. Calls appear only after they end.
- **No Export CSV button**: you do not have the permission to export the call history.
- **A report covers at most 400 days**: shorten the period.
- **A scheduled report was not received**: look at **Last sent** on the **Saved** tab, check the mail settings, and try **Send now**.
