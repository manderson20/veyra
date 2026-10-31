---
title: Set up a ring group
summary: Give a team one number that rings several phones at once or in turn, and decide where unanswered calls go.
audience: admin
section: Calls and call flows
order: 10
reviewed: 0.27.67
checked: 2026-10-30T15:10Z
pages:
  - /ring-groups/
  - /ring-groups/view/
covers:
  - frontend/src/app/(app)/ring-groups/*
  - frontend/src/components/groups/RingGroupFields.tsx
  - frontend/src/components/groups/MemberListEditor.tsx
  - frontend/src/components/routing/DestinationPicker.tsx
  - backend/veyra/api/v1/ring_groups.py
  - backend/veyra/api/v1/group_helpers.py
---

A ring group is a number that rings several phones. The front office, the help desk or the maintenance team get one number. When it is called, their phones ring all at once or one after the other. If nobody answers, the call goes on to a voicemail box, a menu or another number.

Use a ring group when a few people share the calls and someone usually answers within a few rings. When callers may have to wait for someone to become free, use a call queue instead: see [Set up a call queue](guide:call-queues).

## Before you start

- You need permission to change ring groups and queues. Organization and site administrators have it by default.
- The people in the group need extensions. A ring group rings extensions, plus up to 10 outside numbers such as mobiles.

## 1. Create the group

1. Open [Telephony → Ring Groups](app:/ring-groups/) and choose **New ring group**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Front office*, and a **Number**. The number comes from the same numbering plan as extensions and queues, so it must not already be in use. The field suggests the next free number.
4. Choose **Create group**. Veyra opens the group's page.

## 2. Choose who rings and how

On the group's page:

- **Members**: choose an extension under *Choose an extension to add* and click **Add**. Repeat for each person. A group has at most 32 members. Use the arrows to change the order.
- **Outside numbers**: mobile or other outside numbers, one per line, up to 10. They ring along with the members and are dialled through the organization's outbound routes. Tick **Outside numbers must press 1 to accept** so that a mobile's voicemail cannot answer the call and keep it.
- **Strategy**: how the members ring.

| Strategy | What happens |
|---|---|
| **Ring all members at once** | Every member rings for the ring time. The first to answer gets the call. |
| **Ring members one after the other** | The first member in the list rings, then the second, and so on. |
| **One at a time, starting after the last who answered** | Shares the calls out, starting with the member after whoever answered last. |
| **One at a time, each call starting one member later** | Each new call starts one place further down the list. |
| **One at a time, longest without a call first** | The member who has gone longest without a call rings first. |

- **Ring time (seconds)**: 5 to 120. With *Ring all* it is the time for the whole group. With the one-at-a-time strategies it is the time per member. Open **Ring time per member** to give one person a longer or shorter time.
- **Skip a member after unanswered calls** (one-at-a-time strategies only): a member who lets this many calls in a row go unanswered (1 to 10) is passed over for **Skip for (minutes)**. Answering a call clears it. Leave it empty to never skip anyone.
- **Ring members who are already on a call**: off, a member on a call is skipped. On, their phone gets a second call (call waiting).
- **Caller ID prefix**: a short text shown before the caller's name on the ringing phones, for example `Front: `, so people know which group the call came in on. Letters, digits, spaces and `. ' & ( ) - :` only, at most 40 characters.
- **Ring tone (Alert-Info)**: sent to the ringing phones so this group can ring differently. The value depends on the brand and its settings, for example `info=ring2` on many phones. Leave it empty for the normal ring.
- **Show "answered elsewhere" on the other phones**: when someone answers, phones that support this don't list the call as missed.
- **Ignore forwarding set on a member's phone**: a forward set on the phone itself is not followed. Forwarding set in Veyra is not affected.
- **Callers hear**: **Ringing tone**, or **Music on hold** with a **Hold music set** (see [Manage audio and hold music](guide:audio-and-hold-music)).

## 3. Decide what happens when nobody answers

Under **When nobody answers**, choose a destination: an extension, an extension's voicemail, a shared voicemail inbox, an IVR menu, another ring group, a call queue, an announcement, a conference room, a call flow, fax to email, the dial-by-name directory, or **Hang up**.

A group with no members sends every caller straight to this destination.

## 4. Save and deploy

1. Choose **Save changes**.
2. A blue *Changes not yet deployed* note appears. Choose **Deploy changes** in the top bar to send the change to the phone system. (If you do not have that button, a platform administrator deploys.)
3. Point an inbound route or an IVR menu key at the group, or simply dial its number from any phone.

The **As deployed** card on the right sums up what the group will do once deployed.

## Turn a group off or delete it

- Switch off **Enabled** to leave the group out of the phone system without deleting it. Routes and menus that point at it are flagged.
- **Delete** removes the group. Routes, menus, groups and queues that still point at it must be changed first; Veyra tells you which. The number stops working at the next deployment.

## When it does not work

- **A problems badge**, or the note *This group will not work as configured*: read the list. Common causes are no members, a disabled member extension, or a failover destination that was deleted.
- **A member's phone never rings**: check the extension is enabled and its phone is registered. With **Ring members who are already on a call** off, a busy member is skipped. With a skip setting, the member may be passed over after missed calls.
- **An outside number never rings**: the organization needs an outbound route that allows the number.
- **Nothing changed after saving**: deploy the changes.
- **Answering for a colleague**: a ringing member phone can be picked up with `**` and its extension, or with `*8` from a phone in the same pickup group. See [Pick up a colleague's ringing phone](guide:pickup-groups).
