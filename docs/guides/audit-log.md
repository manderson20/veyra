---
title: Audit log
summary: Find out who changed what, who signed in, and which attempts were refused.
audience: admin
section: Sign-in and security
order: 50
reviewed: 0.27.45
pages:
  - /audit/
covers:
  - frontend/src/app/(app)/audit/*
  - backend/veyra/api/v1/audit.py
---

[System → Audit Log](app:/audit/) is a lasting record of administrative actions, sign-ins and refused attempts. Entries cannot be edited or deleted, not even by a platform administrator; only the retention period (below) removes old ones.

Use it to answer questions such as *who changed this ring group?*, *who downloaded that packet capture?* or *is someone trying passwords?*

## Read the list

The newest events are first, 50 per page. Each row shows:

- **Time**
- **Action:** what happened, as a short code such as `extension.create`, `auth.login` or `updates.approve`.
- **Actor:** who did it: a person, an integration token, the system, or `cli (<name>)` for a command run on the server console.
- **Target:** what it was done to.
- **Outcome:** **success**, **failure** or **denied** (the person was not allowed).

## Find something

- **Search action or actor:** type part of an action (such as `firewall` or `backup`) or a person's name or email.
- The outcome filter shows only **Success**, **Failure** or **Denied** events. **Denied** and **Failure** together are a quick way to spot someone trying things they should not.
- The two date fields, **From** and **To**, limit the list to whole days: from the start of the first day to the end of the last. Leave either empty for no limit.

## Export the list

Choose **Export CSV** at the top of the page. The file holds the events that match the search, outcome and dates you set, newest first, up to 100,000 events. Each row has the time, actor, organization, action, target, outcome, IP address, request ID and details.

## See the details

Click a row. The panel shows the **Time**, **Outcome**, **Actor** (and whether it was a user, a token or the system), **Target**, **Organization**, the **IP address** the request came from, the **Request ID**, and the **Details**: what changed, as the system recorded it.

## Who sees what

You need permission to read the audit log. Organization administrators see the events of their organizations; platform administrators see everything, including events that belong to no organization (such as server settings).

## How long entries are kept

By default two years. A platform administrator can change it on the **Retention** card under **System → Settings**, but never below one year.
