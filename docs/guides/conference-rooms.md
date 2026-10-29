---
title: Set up conference rooms
summary: Create a dial-in meeting room with optional PINs, see who is in it, and mute, remove or end from the web.
audience: admin
section: Calls and call flows
order: 50
reviewed: 0.27.44
pages:
  - /conferences/
  - /conferences/view/
covers:
  - frontend/src/app/(app)/conferences/*
  - frontend/src/components/callflow/ConferenceFields.tsx
  - frontend/src/components/conferences/LiveConference.tsx
  - backend/veyra/api/v1/conferences.py
---

A conference room is a number people dial to talk together: a staff meeting, a parent conference with a teacher and an interpreter, a call with a vendor. Anyone who dials the room's number joins the others already there. Outside callers can join too, when an inbound route or a menu key points at the room.

## Before you start

You need permission to change ring groups, queues and conference rooms. Organization and site administrators have it by default.

## 1. Create the room

1. Open [Telephony → Conference Rooms](app:/conferences/) and choose **New conference room**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Board room*, and a **Number**. The number shares the numbering plan with extensions and groups, so it must be free.
4. Choose **Create room**. Veyra opens the room's page.

## 2. Set PINs and options

- **Participant PIN**: 4 to 10 digits that callers must enter to join. Leave it empty for an open room.
- **Administrator PIN**: 4 to 10 digits. Someone who joins with it is the room's administrator and can use the administrator keys below. Once a PIN is set it is never shown again; type a new one to change it, or tick **Remove the participant PIN** / **Remove the administrator PIN**.
- **Participant limit**: 0 for no limit, up to 500.
- **Hold music while waiting alone**: a hold music set, or the built-in music.
- **Announce when participants join and leave**.
- **Play hold music to a participant who is alone**.
- **Participants wait until an administrator joins**: the meeting starts when someone joins with the administrator PIN. This needs an administrator PIN; without one the room shows a warning.
- **Record the conference**: the whole meeting is recorded. The recordings are listed under [Call Recording](app:/recording/) with a *Conference* badge. See [Record calls](guide:call-recording).
- **Enabled**: a disabled room is left out of the phone system.

Choose **Save**, then **Deploy changes** in the top bar.

> **Tip:** a line key (BLF) with the room's number lights while the room is in use.

## Keys people press in the room

The **In the room** card on the room's page lists them:

| Key | What it does |
|---|---|
| `*1` | Mute or unmute yourself |
| `*4` / `*6` | Listening volume down / up |
| `*7` / `*9` | Talking volume down / up |
| `*2` | Administrator: lock or unlock the room |
| `*3` | Administrator: drop the last participant who joined |
| `*8` | Administrator: mute or unmute everyone else |

## Watch and control a meeting from the web

While a meeting is going on, the **Live** card on the room's page lists everyone in the room, with *Admin* and *Muted* badges, and updates every few seconds. If you may change conference rooms you can:

- **Mute** or **Unmute** one participant, and **Remove** them from the room.
- **Mute everyone else** mutes every participant who did not join as an administrator; **Unmute all** undoes it.
- **Lock** the room so nobody else can join, and **Unlock** it.
- **End** the meeting: everyone in the room is disconnected (you confirm with **End for everyone**).

Each of these actions is written to the audit log. They apply at once and need no deployment.

## When it does not work

- **Callers are asked for a PIN you did not expect**: the room has a participant PIN. Remove it or share it.
- **Everyone hears music and nobody can talk**: **Participants wait until an administrator joins** is on and nobody has joined with the administrator PIN.
- **The Live card says the engine is unavailable**: the telephony engine is not running or cannot report rooms. Check [System → Telephony Engine](app:/system/telephony/).
- **Deleting a room**: routes, menus, groups and announcements that point at it must be changed first.
