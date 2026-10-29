---
title: The dashboard
summary: What the dashboard shows about the server, the phone system and today's calls.
audience: admin
section: Getting started
order: 20
reviewed: 0.27.44
pages:
  - /
covers:
  - frontend/src/app/(app)/page.tsx
  - frontend/src/components/reports/TodayCards.tsx
  - frontend/src/components/common/Metric.tsx
---

The dashboard is the first page after you sign in. It shows whether Veyra and the phone system are healthy, how busy the server is, and what happened today. It refreshes by itself every 30 seconds; **Refresh** reloads it at once.

What you see depends on your role. Someone without the *system health* permission sees **No dashboard access** instead of the status cards.

## Service status

The top row has one card each for **Veyra** (with its version), the **Database**, the **Telephony engine** and **Modules**. Each shows a status badge: normal, degraded or failed. The small text under the badge says what is wrong when something is.

Depending on what is set up, more cards follow:

- **Emergency calling:** how many sites are ready for emergency calls, with a link to readiness per site and test calls.
- **Last good backup:** when the last backup succeeded, and whether scheduled backups are on and encrypted. Platform administrators only.
- **High availability:** the state of the cluster, when high availability is on. Platform administrators only.

## Server resources

**CPU**, **Memory**, **Disk** and **Uptime** of this server. A disk that is nearly full is the most common cause of trouble, because recordings, voicemail and backups all need space.

## Graphs

- **Channels:** the calls going through the telephony engine, and the registered phones.
- **Calls: internal vs external:** calls between your phones against calls through your carrier.
- **Phones online:** phones that are registered against phones the engine knows but cannot reach.

Choose **1h**, **6h**, **24h** or **7d** above a graph for the time range. If a graph says *Not available yet*, the telephony engine is not reporting.

## Calls, cluster and updates

- **Calls and registrations:** the number of active calls and registered extensions right now.
- **Cluster and updates:** whether this is a standalone server or a cluster, the database role, and whether updates are available. Choose the update line to go to the Updates page.

## Today and recent activity

- **Calls today:** calls so far today, how many were answered and missed, and the change since the same time last week. Choose **Reports** for more.
- **Alerts:** open alerts. *Nothing is wrong* means there are none.
- **Recent activity:** the last changes from the audit log. Choose **View audit log** for all of them.

## If something doesn't work

- **The telephony engine card is red:** open System → Telephony Engine to see what the engine reports.
- **Graphs say *Not available yet*:** the engine is not running or not reachable. Check the telephony engine card first.
- **Calls and registrations shows *Not available yet* to an organization administrator:** with multi-tenancy on, these counts cover every organization, so only platform administrators see them.
