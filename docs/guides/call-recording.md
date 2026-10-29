---
title: Record calls
summary: Choose which calls are recorded and for how long, record a call on demand, and listen to recordings with every playback audited.
audience: admin
section: Calls and call flows
order: 80
reviewed: 0.27.44
pages:
  - /recording/
covers:
  - frontend/src/app/(app)/recording/*
  - frontend/src/components/calls/RecordingPlayer.tsx
  - frontend/src/components/calls/PickList.tsx
  - backend/veyra/api/v1/recording.py
  - backend/veyra/reporting/recordings.py
---

Veyra records nothing until you say so. A *recording policy* says which calls of an organization are recorded, what callers hear first, and how long the recordings are kept. Recordings can also be started during a single call. Every time someone listens to or downloads a recording, it is written to the audit log.

> **Important:** recording calls is regulated. Some states require that everyone on the call agrees. Check your district's or company's policy and the law before you turn recording on, and play an announcement to callers.

## Who can do what

| Permission | Lets someone | By default |
|---|---|---|
| View what calls are recorded | See the **Policies** tab | Organization and site administrators, read-only users |
| Change what calls are recorded | Add, change and remove policies | Organization administrators |
| Listen to and download call recordings | The **Recordings** tab, for the whole organization | Organization administrators |
| Listen to recordings of your own calls | The **Recordings** tab, for calls of their own extensions | Nobody |
| Hold, release and delete call recordings | **Hold** and **Release** | Organization administrators |
| Start and stop recording a call in progress | **Record** on Active Calls | Organization and site administrators |

Users can also be allowed to play recordings of their own calls on My Phone: on the organization's page under [Directory → Organizations](app:/organizations/), switch on **Users may play recordings of their own calls**.

## 1. Add a recording announcement

Record or upload a short recording such as "This call may be recorded for quality purposes", as described in [Manage audio and hold music](guide:audio-and-hold-music).

## 2. Add a policy

1. Open [Telephony → Call Recording](app:/recording/), the **Policies** tab, and choose **New policy**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Front office lines*.
4. Under **Directions**, tick which calls: **Inbound (from outside)**, **Outbound (to outside)**, **Internal (phone to phone)**.
5. Under **Which calls**, choose:
   - **Every call of the organization in these directions**, or
   - **Only calls of the phones, groups, queues and numbers chosen below**, then pick the **Phones**, **Ring groups**, **Queues** and **Inbound numbers (DIDs)**.
6. Choose the **Announcement** callers hear before the call connects.
7. Set **Keep recordings (days)**: 1 to 3650. Recordings are deleted after this unless held.
8. Leave **Enabled** on and choose **Add policy**.
9. Choose **Deploy changes** in the top bar. Recording starts with the next call after the deployment.

The **Notes** box under the list warns about policies that record nothing (no direction ticked, or nothing chosen), and about inbound recording without an announcement.

To stop recording, edit the policy and switch off **Enabled**, or remove it, then deploy. Recordings already made are kept until their retention date.

## Record one call on demand

- **From a phone:** during a call, press `*1`. A beep confirms the recording has started. Press `*1` again to stop it. The extension's class of service can forbid this; the phone then plays an error tone.
- **From the web:** on [Active Calls](app:/calls/), choose **Record** on the call, and **Stop recording** to end it. See [Watch live calls](guide:live-calls).

On-demand recordings are kept for 90 days.

Conference rooms with **Record the conference** on are recorded as well; they appear with a *Conference* badge and *Whole room* as the other party.

## Listen to recordings

1. Open the **Recordings** tab. Each recording shows the call's time, direction, **From**, **To**, **Length** and **Deleted on** (its retention date, or *Held*).
2. Choose **Listen**. The player plays the recording in the browser; **Download** saves the file (Ogg Opus audio).

Recordings appear about a minute after a recorded call ends. You can also open a call in [Call History](app:/call-history/) and play its recording there.

Every listening and download is written to the audit log with who did it.

## Keep a recording past its retention date

When a recording is needed for an investigation or a complaint, choose **Hold**. A held recording is not deleted until someone chooses **Release**; after that it is deleted at its retention date like any other.

## When it does not work

- **No recordings appear**: check the policy is enabled, covers the call's direction and the phones or numbers involved, and that you deployed after adding it.
- **The policy shows a note**: read it; a policy with no direction or nothing chosen records nothing.
- **The browser cannot play the recording**: use **Download** and play the file in a media player such as VLC.
- **`*1` gives an error tone**: the phone's class of service does not allow on-demand recording.
