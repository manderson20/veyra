---
title: Watch live calls
summary: See the calls in progress, hang one up, record it, or listen in, whisper and join as a supervisor.
audience: admin
section: Calls and call flows
order: 90
reviewed: 0.27.53
pages:
  - /calls/
covers:
  - frontend/src/app/(app)/calls/*
  - backend/veyra/api/v1/calls.py
---

[Telephony → Active Calls](app:/calls/) lists every call that is ringing or up right now: the extension, who called whom, the state and how long it has lasted. The list updates by itself every few seconds; **Refresh** updates it at once.

## Who can do what

| Permission | Lets someone | By default |
|---|---|---|
| View active calls | See the list | Organization and site administrators, technicians, read-only users |
| Hang up calls in progress | **Hang up** | Organization and site administrators, technicians |
| Start and stop recording a call in progress | **Record** | Organization and site administrators |
| Listen to, whisper on and join calls in progress (supervisor) | **Supervise…** | Organization and site administrators |

Platform administrators see every call. Everyone else sees the calls of extensions in the organizations they manage; a call leg Veyra cannot match to one of those extensions, such as the trunk side of an outside call, is shown only to platform administrators.

## Read the list

- **Extension**: the phone in the call, with the person's name. A leg on a trunk shows the phone system's name for the trunk instead.
- **From** and **To**: the numbers.
- **State**: *Ring* or *Ringing* while it rings, *Up* while people talk.
- **Channel**: the phone system's name for this side of the call; support may ask for it.

A call between two phones shows up twice, once for each side.

## Hang up a call

Choose **Hang up**, then **Hang up** again to confirm (or **Keep** to cancel). This ends that side of the call; the phone system clears the other side. Use it for a call stuck on a line or a phone left off the hook.

## Record a call

Choose **Record** to start recording the call, and **Stop recording** to stop. The recording is filed with the call when it ends and appears under [Call Recording](app:/recording/). See [Record calls](guide:call-recording).

A call that is already being recorded, by a [recording policy](guide:call-recording) or from a phone, shows a *Recording* badge instead. Only a recording started here can be stopped here. A call can be recorded from this page once: after **Stop recording**, starting again is refused.

## Supervise a call

A supervisor can hear a call without being heard, coach the staff member without the caller hearing, or join the call.

1. Find the call and open **Supervise…** next to it.
2. Choose **Listen**, **Whisper to the user** or **Join the call**.
3. Your own desk phone rings: the first enabled extension assigned to you. If you have several extensions, pick the phone that should ring in **Supervise from** above the list first. Answer it:
   - **Listen**: you hear both sides; nobody hears you.
   - **Whisper to the user**: the staff member hears you, the caller does not.
   - **Join the call**: both sides hear you.
4. Hang up your phone to stop.

Every supervision session is written to the audit log: who, which call, which mode and from which phone.

Supervisors can do the same from a phone, without the web, with the default codes `*222` (listen), `*223` (whisper) or `*224` (join) followed by the extension. That needs a class of service with **May listen to, whisper on and join calls (supervisor codes)**.

**Beep and protection**

- On the organization's page under [Directory → Organizations](app:/organizations/), **Beep when a supervisor listens in** plays a short beep to both sides when supervision starts. Some states require that everyone on a call knows it is being monitored.
- A class of service with **Never monitored** protects its phones: nobody can listen to, whisper on or join their calls, for example a counselor's or the nurse's phone.

## When it does not work

- **"Live call data is not available"**: the telephony engine is not running or cannot report calls. Check [System → Telephony Engine](app:/system/telephony/).
- **"You have no phone to listen on"**: you have no enabled extension assigned to your user. Ask an administrator to assign one.
- **"…class of service does not allow monitoring"**: the phone is protected with **Never monitored**.
- **"That is the call on your own phone"**: you cannot supervise your own call.
- **Your phone does not ring**: check that your extension is registered (Telephony → Registrations).
