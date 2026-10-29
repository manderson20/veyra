---
title: Block callers
summary: Refuse calls from unwanted numbers, and optionally from callers who hide their number.
audience: admin
section: Calls and call flows
order: 70
reviewed: 0.27.44
pages:
  - /caller-blocks/
covers:
  - frontend/src/app/(app)/caller-blocks/*
  - backend/veyra/api/v1/caller_blocks.py
  - backend/veyra/telephony/blacklist.py
---

The block list holds numbers your organization refuses. A call from a blocked number is refused on **every inbound route** of the organization, before any phone rings. Calls between your own extensions are not affected.

The list is at [Telephony → Blocked Callers](app:/caller-blocks/). If you manage several organizations, choose the **Organization** first: each has its own list.

## Block a number

1. Choose **Block a number**.
2. Enter the **Number** exactly as the caller ID shows it, for example `5735551234`. Spaces, dashes, dots and brackets are removed; the number must be 2 to 32 digits, optionally with a leading `+`.
3. Optionally add a **Note**, such as why it is blocked.
4. Choose **Block**.

The block takes effect at once. No deployment is needed.

> **Important:** The number must match the caller ID exactly as your carrier delivers it. `5735551234` does not block `+15735551234`. Look the call up in Call History to see the form your carrier uses, and if in doubt block both forms.

## Block from a phone

Anyone allowed to dial these feature codes can manage the list from a desk phone:

| Code (default) | Does |
|---|---|
| `*30` | Asks for a number and blocks it |
| `*32` | Blocks the last outside caller who called this phone directly |
| `*31` | Asks for a number and unblocks it |

Numbers blocked from a phone appear in the list with **From a phone** in the **Added** column. The codes can be changed or turned off at [Feature Codes](app:/feature-codes/), and limited with a [class of service](guide:classes-of-service).

## Import and export

- **Import** takes a list with one number per line, optionally followed by a comma and a note (`5735551234,Robocaller`). A CSV exported from Veyra, or from FreePBX, works as is. Up to 5,000 lines at a time. Numbers already blocked keep their block and get the new note, and lines that are not valid numbers are listed as skipped.
- **Export CSV** downloads the organization's list.

## Rules for blocked and hidden callers

The **Rules** panel applies to the whole organization:

- **Block callers who withhold their number**: also refuses callers whose number is anonymous, restricted, private or unavailable.
- **Blocked calls go to**: what refused callers get. **Hang up** (the default) plays "the number you have dialled is not in service" and hangs up. You can instead send them somewhere, for example a voicemail box or an announcement.

Choose **Save rules**, then **Deploy changes** in the top bar. Unlike the numbers themselves, the rules need a deployment.

The panel also counts the **Blocked numbers** and **Blocked calls** (with how many were withheld numbers). The list shows how many calls each number made since it was blocked and when the last one was.

## Unblock

Choose **Unblock** on the number's row and confirm. Calls from it reach the organization again at once.

## If it does not work

- **A blocked number still gets through.** Compare the caller ID in Call History with the number in the list, character for character, including any leading `1` or `+`.
- **Legitimate callers are refused.** If **Block callers who withhold their number** is on, some callers (for example hospitals or other organizations' phone systems) hide their number. Turn it off, or send blocked calls to a voicemail box instead of hanging up.
