---
title: Who can call where (classes of service)
summary: Limit what groups of phones may dial, such as local calls only for classrooms, while 911 always works.
audience: admin
section: Calls and call flows
order: 60
reviewed: 0.27.44
pages:
  - /routing/classes-of-service/
covers:
  - frontend/src/app/(app)/routing/classes-of-service/*
  - frontend/src/components/routing/ClassOfServiceDialog.tsx
  - backend/veyra/api/v1/classes_of_service.py
---

A **class of service** is a set of permissions for a group of phones: which outbound routes they may use, which feature codes they may dial, and a few other limits. You create classes, then put extensions in them.

**An extension without a class may do everything.** Nothing is restricted until you create a class and assign it. **Emergency routes always work** for every class.

Classes of service are at [Telephony → Classes of Service](app:/routing/classes-of-service/). Each organization has its own classes.

## Plan first

Classes are built from your [outbound routes](guide:route-outgoing-calls), so split the routes the way you want to allow them. For example:

| Outbound route | Classrooms | Staff | Office |
|---|---|---|---|
| Local | ✓ | ✓ | ✓ |
| Long distance | | ✓ | ✓ |
| International | | | ✓ |

The office phones could simply have no class at all.

## Create a class

1. Choose **New class**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, such as *Classrooms*, and an optional **Description**.
4. Under **Outbound routes the class may use**, tick the routes. Emergency routes are not listed because they are always allowed. With no route ticked, the phones can call extensions and 911 only.
5. **Every feature code**: leave it on to allow every star code, or turn it off and tick the codes the class may dial.
6. Set the other permissions:

| Setting | When ticked |
|---|---|
| **Forwards may go to outside numbers** | People can forward their phone to a mobile or other outside number |
| **Follow-me may ring outside numbers** | Follow-me can include outside numbers |
| **May use intercom** | The phone can make intercom calls that answer on the other phone's speaker |
| **May send faxes from My Phone** | People can send faxes from the web |
| **May listen to, whisper on and join calls (supervisor codes)** | The phone may use `*222`, `*223` and `*224` plus an extension. Off by default. Check your state's rules on call monitoring and consent before turning it on |
| **Never monitored** | Nobody can listen to these phones' calls, with a supervisor code or from the web. Use it for counselors, nurses and others whose calls must stay private |

7. **Outside calls at once (empty: no limit)**: the most outside calls the whole class may have at the same time, counted across all its phones (1 to 500). When the limit is reached, the next caller hears a busy signal.
8. Choose **Create class**, then **Deploy changes** in the top bar.

## Put phones in a class

Open an extension under [Extensions](app:/extensions/) and choose its **Class of service**, or set the class on an extension template so new extensions get it. Save and deploy.

The **Extensions** column of the list shows how many extensions are in each class.

## What people notice

- Dialling a number whose route is not in their class: the call is refused with a short recorded message, and Call History shows it as refused.
- Dialling a feature code their class does not allow: the code is refused.
- Dialling 911 (or any number on an emergency route): always goes through.

## Editing and deleting

Choose **Edit** on a class (or click its row), change it, and choose **Save changes**, then deploy.

> **Note:** When you add a new outbound route later, existing classes do not get it automatically. Edit each class that should use it.

A class that still has extensions cannot be deleted. Move them to another class (or to none) first.
