---
title: Build a phone menu
summary: Greet callers with a recording, send each key to the right place, and play announcements before a call goes on.
audience: admin
section: Calls and call flows
order: 60
reviewed: 0.27.44
pages:
  - /ivr/
  - /ivr/view/
  - /announcements/
  - /announcements/view/
covers:
  - frontend/src/app/(app)/ivr/*
  - frontend/src/app/(app)/announcements/*
  - frontend/src/components/ivr/IvrMenuFields.tsx
  - frontend/src/components/callflow/AnnouncementFields.tsx
  - backend/veyra/api/v1/ivr.py
  - backend/veyra/api/v1/announcements.py
---

A phone menu (an *IVR menu*, or auto-attendant) answers a call with a recording such as "For attendance, press 1. For the front office, press 2." and sends the caller wherever the key they press leads. An *announcement* plays one recording, then sends the call on: a closure notice before the main menu, or "this call may be recorded" before a queue.

## Before you start

- You need permission to change IVR menus, announcements and prompts. Organization and site administrators have it by default.
- Record or upload the greeting first. A menu without a prompt does not work. See [Manage audio and hold music](guide:audio-and-hold-music): you can record from any phone with `*95`.
- Create the places the keys lead to first (extensions, ring groups, queues, voicemail boxes), so you can choose them.

## 1. Create the menu

1. Open [Telephony → IVR Menus](app:/ivr/) and choose **New IVR menu**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Main menu*.
4. Choose the **Menu prompt**, or leave **Choose later**.
5. Choose **Create menu**. Veyra opens the menu's page.

## 2. Map the keys

Under **Keys**, every key from `0` to `9`, `*` and `#` is listed. Choose **Key 1: not mapped** (and so on) to map a key, then choose where it goes:

| Destination | Sends the caller to |
|---|---|
| **Extension** | One phone |
| **Voicemail of an extension** | Straight to that person's voicemail greeting |
| **Shared voicemail inbox** | A shared box, such as the attendance line |
| **IVR menu** | Another menu (a sub-menu) |
| **Ring group** / **Call queue** | A team |
| **Announcement** | A recording, then onwards |
| **Conference room** | A meeting room |
| **Call flow** | A day/night switch |
| **Fax to email** | A fax inbox |
| **Dial-by-name directory** | Callers spell a name |
| **Hang up** | Ends the call |

**Remove** unmaps a key again. A key can be mapped only once.

Tick **Callers may dial an extension number during the menu** to let callers who know an extension dial it. Only extensions of this organization can be reached. A mapped key wins over an extension starting with the same digit, so with key 2 mapped, nobody can dial extension 2001 from the menu.

## 3. Decide what happens when callers press nothing or the wrong key

- **Wait for a key (seconds)**: 1 to 30, after the prompt ends. Callers may press a key while the prompt is still playing.
- **Attempts before giving up**: 1 to 9, timeouts or wrong keys before the caller is sent on. The prompt plays again between attempts.
- **After too many timeouts**: where callers who press nothing go. Send them to a person (for example the reception ring group) rather than **Hang up**: callers on old phones or who do not understand the menu end up here.
- **Invalid-key prompt**: what callers hear after a wrong key. The default says "I'm sorry, that's not a valid extension".
- **After too many invalid keys**: where they go then.

## 4. Save, deploy and connect

1. Choose **Save changes**, then **Deploy changes** in the top bar.
2. Point an inbound route at the menu so outside callers reach it (Telephony → Inbound Routes), or map a key of another menu to it.

The **As deployed** card shows the prompt, each key and the fallbacks as the phone system will use them.

## Announcements

1. Open [Telephony → Announcements](app:/announcements/) and choose **New announcement**.
2. Enter a **Name**, choose the **Recording to play** (or **Choose later**), and choose **Create announcement**.
3. On the announcement's page:
   - **Callers may press any key to skip the recording**.
   - **Key that replays the recording**: optional, `0`–`9`, `*` or `#`.
   - **Then send the call to**: where the call goes after the recording.
4. Choose **Save**, then **Deploy changes**.

Point a route, a menu key, a group's or queue's failover, or another announcement at it.

> **Tip:** for a snow day or holiday closure, put an announcement in front of the main menu and switch between the two with a call flow, so the change is one key press on a phone. Call flows and time conditions are explained in their own guides.

## When it does not work

- **Callers hear a fast busy tone**: the menu has no prompt (*No prompt* in the list), or the announcement has no recording. Choose one and deploy.
- **A problems badge**: read the list on the page. A destination may have been deleted, or the menu has no keys and direct dialling is off.
- **A key does nothing**: the key is not mapped, or the change has not been deployed.
- **You cannot delete a menu or an announcement**: routes, menus, groups and queues that point at it must be changed first.
