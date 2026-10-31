---
title: Feature codes people can dial
summary: The star codes phones dial to forward calls, turn on Do Not Disturb, pick up calls and more, and how to change them.
audience: admin
section: Getting started
order: 60
reviewed: 0.27.68
checked: 2026-10-29
pages:
  - /feature-codes/
covers:
  - frontend/src/app/(app)/feature-codes/*
  - backend/veyra/telephony/features.py
---

Feature codes are what people dial on their phone to change its settings or reach a feature, such as `*72` to forward their calls. The codes start with `*` or `#`, so they never clash with extension numbers.

The page is under **Telephony → Feature Codes**. It shows each code with its **Default**, and whether it is **Enabled**. Veyra's defaults follow FreePBX, so people moving from a FreePBX system keep their habits.

## The codes

These are the defaults. Your installation may have changed some of them: the page shows the codes in use.

| Default | Feature | How to use it |
|---|---|---|
| `*78` | Do Not Disturb on | Callers hear busy, or the busy greeting. |
| `*79` | Do Not Disturb off | The phone rings again. |
| `*76` | Do Not Disturb toggle | A phone key on this code lights while Do Not Disturb is on. |
| `*72` | Forward all calls | Dial with the number, or alone and enter it. |
| `*73` | Forward all calls off | |
| `*90` | Forward on busy | Dial with the number, or alone and enter it. |
| `*91` | Forward on busy off | |
| `*52` | Forward on no answer | Dial with the number, or alone and enter it. |
| `*53` | Forward on no answer off | |
| `*94` | Forward all calls of another phone | Dial with the extension, enter its voicemail PIN, then the number. |
| `*96` | Forward all calls of another phone off | Dial with the extension, then enter its voicemail PIN. |
| `*21` | Find me / follow me toggle | |
| `*80` | Intercom | Dial with the extension: that phone answers on speaker. |
| `*` | Direct to voicemail | Dial with an extension, or transfer to it: straight to its greeting. |
| `*28` | Call flow toggle | Followed by the flow's index: switches it between its two destinations. |
| `*27` | Time condition override | Followed by the condition's index: forces the opposite state until the schedule changes. Dial again to clear it. |
| `*30` | Block a caller | Enter a number; it is refused for the whole organization. |
| `*31` | Unblock a caller | Enter a number to remove it. |
| `*32` | Block the last caller | Blocks the last outside number that rang this phone directly. |
| `*45` | Queue log in / log out | Alone: every queue this phone may join. With a queue number: that queue only. |
| `*46` | Queue pause / unpause | Alone or with a queue number. |
| `*47` | Queue waiting count | With a queue number: says how many callers are waiting. |
| `*1` | Record this call | During a call: starts recording (a beep); again, stops it. |
| `*2` | Attended transfer | During a call, then the number: talk first, hang up to connect. |
| `##` | Blind transfer | During a call, then the number: the call goes straight across. |
| `*36` | Colleague's presence | With an extension, on a phone key: shows that colleague's presence; pressing it calls them. |
| `*37` | Set your presence | Followed by 1 available, 2 away, 3 busy, 4 in a meeting, 5 at lunch, 6 out. Alone: back to available. |
| `*85` | Pick up a parked call | Followed by the parking slot number. |
| `*67` | Hide your number on one call | Followed by the number. Emergency calls always show it. |
| `*69` | Call back the last caller | Calls the last outside number that rang this phone directly. |
| `*70` | Call waiting off for one call | Followed by the number. |
| `*77` | Refuse callers who hide their number | |
| `*87` | Accept callers who hide their number | |
| `*222` | Listen to a call (supervisor) | With an extension: hear its call without being heard. |
| `*223` | Whisper on a call (supervisor) | With an extension: only that phone's user hears you. |
| `*224` | Join a call (supervisor) | With an extension: both sides hear you. |

The supervisor codes work only on phones whose class of service allows supervising. The class of service of an extension can also block other codes.

## Codes that never change

The **Always available** card lists the codes every installation has:

| Code | Feature |
|---|---|
| `*97` | Your own voicemail |
| `*98` | Any voicemail box |
| `*8` | Pick up a call ringing in your pickup group |
| `**` and an extension | Pick up the call ringing on that phone |
| `*43` | Echo test |
| `*60` | Speaking clock |
| `*95` | Record a prompt |

## Change a code

You need the permission to change routing.

1. Type the new code in the **Code** column. A code starts with `*` or `#` and has 1 to 7 characters (digits, `*` or `#`).
2. To turn a feature off entirely, switch **Enabled** off.
3. Choose **Save** at the top of the page.
4. Choose **Deploy changes** in the top bar. The new codes work after the deployment.

Tell staff about the change, and update any phone keys that use the old code.

## Load the codes from your old phone system

If staff are used to the codes of another system, use **Code sets**:

1. Under **Load a code set**, pick the set, for example *Metaswitch (Sparklight code card)*.
2. Veyra puts its codes into the table, but does not save them yet. The box underneath lists every change and any differences the set cannot remove.
3. Check the table, then choose **Save** and deploy.

## If something doesn't work

- **"… is already used":** the code belongs to one of the fixed codes, or starts with `**`. Pick another.
- **"… is also used by …":** two enabled features cannot share a code.
- **A code does nothing on the phone:** check that it is enabled, that you deployed, and that the extension's class of service allows it.
