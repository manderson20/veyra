---
title: Manage voicemail boxes and shared inboxes
summary: Give extensions a voicemail box, set PINs and email delivery, and create shared inboxes that several phones watch.
audience: admin
section: Voicemail and fax
order: 10
reviewed: 0.27.51
pages:
  - /voicemail/
covers:
  - frontend/src/app/(app)/voicemail/*
  - frontend/src/components/voicemail/VoicemailBoxDialog.tsx
  - frontend/src/components/voicemail/LocaterField.tsx
  - frontend/src/components/voicemail/VoicemailBoxPanel.tsx
  - frontend/src/components/voicemail/VoicemailInbox.tsx
  - frontend/src/components/voicemail/GreetingsPanel.tsx
  - backend/veyra/api/v1/voicemail.py
  - backend/veyra/voicemail/service.py
---

Every extension can have one voicemail box. Callers reach it when the phone is not answered, is busy or is on Do Not Disturb, and from inbound routes and phone-menu keys that point at it. You can also create **shared inboxes**: boxes with their own number that belong to no single phone, such as an *Attendance line* that several office phones watch.

Voicemail boxes are listed under [Telephony → Voicemail](app:/voicemail/).

## Before you start

- For new messages to be emailed, an SMTP server must be set up on the **Email delivery** card under [Settings](app:/settings/). Until then, the Voicemail page shows *Email delivery is not configured* and messages stay in the boxes.
- You need permission to change voicemail (`voicemail.write`).

## Create a box for an extension

1. Choose **New voicemail box**.
2. Pick the **Extension**. Only extensions without a box are offered.
3. **PIN**: 4 to 10 digits, or leave it empty for a random PIN.
4. **Ring time (seconds)**: how long the phone rings before voicemail answers, 5 to 120 (default 20).
5. **Use the extension user's email address**: on by default. New messages go to the email address of the person the extension belongs to. Untick it to enter another address under **Email address for new messages**, or leave that empty to keep messages in the box only.
6. Choose **Create box**.
7. The PIN is shown **once**. Copy it and give it to the user now.
8. Use **Deploy changes** in the top bar so the phone system learns the box.

You can also create a box from the extension's own page.

> **Note:** If the extension follows an extension template, the template may set or lock some voicemail options. Locked options can only be changed in the template.

## Box options

When you create or edit a box (click its row), these options are available:

| Option | What it does |
|---|---|
| **Operator extension (press 0)** | A caller who presses 0 during the greeting rings this extension. Empty: 0 does nothing. |
| **After-hours greeting** | Choose a time condition: while it is closed, the box plays its *After hours* greeting instead of the *Unavailable* one. Needs a deployment. |
| **Press 1 during the greeting** / **Press 2 during the greeting** | **Does nothing**, **Tries the follow-me numbers** (key 1 of an extension's box only), or **Rings another number** (an extension, ring group or queue). Users can set these themselves too. |
| **Attach the recording to the email** | On by default. Off: the email only says a message arrived. |
| **Delete the message from the box once it has been emailed** | Saves storage. The message is deleted only after the email server accepted it; if sending fails, it stays. Needs an email address and the recording attached. |
| **Delete messages older than (days)** | 1 to 3650. Once a day, older messages are deleted from every folder of the box. Empty keeps them. |
| **Enabled** | A disabled box keeps its settings and messages, but calls no longer land in it. |

Each message can be up to 3 minutes long, and greetings up to 60 seconds.

## Reset a PIN

Open the box and choose **Reset PIN**. A new random PIN is shown once. The old PIN stops working at the next deployment. Users can also change their PIN from the phone (`*97`, mailbox options) or on their account page, except for a shared inbox, whose PIN only an administrator resets here.

## Shared inboxes

A shared inbox has its own number and is not tied to one phone. Callers reach it by dialling its number, or through inbound routes and phone-menu keys that point at it. The phones you list as members light their message lamp when it has new messages, and their users see it on [My Phone](app:/my-phone/).

1. Choose **New shared inbox**.
2. Enter a **Name** (for example *Attendance line*) and a **Number** from the numbering plan.
3. Add **Member phones**.
4. Set the **PIN** and an **Email address for new messages**, for example a shared office mailbox.
5. Choose **Create box**, note the PIN, and deploy the changes.

From a phone, members open the inbox with `*98`: enter the inbox's number, then its PIN. Dialling the inbox's number itself leaves a message.

> **Tip:** Point an inbound route or a phone-menu key at the shared inbox, for example *press 1 to report an absence*.

## Listen to a box's messages

**Messages** on a box's row opens its messages and greetings, as the user sees them:

- **Messages**: play, **Move** to another folder, **Forward** a copy to another box, **Email** it to an address (it stays in the box unless you tick **Delete it from the voicemail box once the email is sent**), or **Delete** it. Folders are *New*, *Old*, *Work*, *Family*, *Friends* and *Urgent*.
- **Greetings**: play, **Upload** or **Record** in the browser, or **Remove** each greeting: *Unavailable*, *Busy*, *Name*, *Temporary*, *Extended absence* and *After hours*. Below them is the box's **Extended absence** (see [Your voicemail](guide:your-voicemail)).

Listening to a message and every change are written to the audit log.

## Extended absence for many boxes

For a break when nobody answers, such as the summer, set one absence for many boxes at once:

1. Choose **Extended absence…** at the top of the page.
2. Leave **Extended absence on** switched on.
3. Set the **First day** (empty: from now) and the **Last day** (empty: until it is turned off). After the last day it turns itself off.
4. Tick **Take no messages while away** if callers should hear the greeting and then be hung up on, without leaving a message.
5. Pick the boxes: tick them one by one, or narrow the list with **Organization** or **Find a box** and choose **Pick all … shown**.
6. Choose **Set for … boxes**.

Callers hear each box's *Extended absence* greeting (or its *Temporary* greeting) for these dates. It takes effect at once; no deployment is needed. To end it early, open the dialog again, switch **Extended absence on** off, pick the boxes and choose **Turn off for …**.

## Delete a box

Open the box and choose **Delete box**. Routes and phone-menu keys that point at it must be changed first. Then deploy the changes.

## If something doesn't work

- **No emails arrive:** check the **Email delivery** card under Settings, and the box's email address. Look in the recipient's spam folder.
- **The user's PIN does not work:** PIN changes reach the phone system at the next deployment. Check that changes have been deployed.
- **The Messages tab says messages are not available on this server:** Veyra cannot reach the phone system's voicemail storage on this server. Check [System → Health](app:/system/health/).
