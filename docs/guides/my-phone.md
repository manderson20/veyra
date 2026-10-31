---
title: Your phone at a glance: My Phone
summary: Turn on Do Not Disturb, forward your calls, check voicemail, call people back, keep your contacts and send a fax, all from the My Phone page.
audience: user
section: Using Veyra
order: 10
reviewed: 0.27.70
checked: 2026-10-30
pages:
  - /my-phone/
covers:
  - frontend/src/app/(app)/my-phone/*
  - frontend/src/components/portal/*
  - frontend/src/components/extensions/CallHandlingCard.tsx
  - frontend/src/components/extensions/FollowMeCard.tsx
  - backend/veyra/api/v1/me.py
  - backend/veyra/api/v1/me_contacts.py
  - backend/veyra/api/v1/me_devices.py
  - backend/veyra/api/v1/me_fax.py
---

**My Phone** is your own page in Veyra. Open it from the menu at any time. It is made of boxes called **widgets**: your phone's settings, your voicemail, your recent calls, your contacts and more. Your school or company chooses the starting arrangement; you can change it.

Most changes you make here take effect at once. You do not need to wait for anyone.

## Your phone and call handling

The **My phone** widget shows your extension number, whether your desk phone is connected (**Phone registered**), and two cards:

**Call handling**

- **Do Not Disturb**: callers hear busy, or your voicemail's busy greeting. Under **Callers who still ring during Do Not Disturb** you can list up to 20 numbers or extensions that always get through, one per line, such as your child's school or your manager.
- **Call waiting**: turn it off so that, while you are on a call, other callers hear busy or go to voicemail.
- **Refuse callers who hide their number**: outside callers without caller ID are turned away. Colleagues always ring.
- **Forward all calls to**, **Forward when busy to**, **Forward when unanswered to** and **Forward when the phone is offline to**: an extension or an outside number. Leave a box empty to turn that forward off. The offline forward helps during a power or network outage.

Switches take effect as soon as you flip them; for the forwards and the list, choose **Save call handling**.

**Find me / follow me**

Rings your mobile or another phone as well as your desk phone.

1. Choose **Add a number**, pick **Extension** or **Outside number**, enter it and how long it should ring.
2. Choose whether to ring **All at once** or **One after another**, and how long your desk phone rings alone first.
3. **Outside numbers must press 1 to accept** keeps your mobile's voicemail from answering the call.
4. Choose **Save follow me**, then turn on **Follow me**.

## Presence

The **Presence** widget sets what colleagues see next to your name: **Available**, **Away**, **Busy**, **In a meeting**, **At lunch** or **Out of the office**, with an optional short **Message** such as *Back at 3*.

- **Automatic actions…** lets each state change your phone too. For example, *Out of the office* can turn on Do Not Disturb or forward your calls; *Available* can turn them off again. Choose **Save actions**.
- **From your calendar**: connect your calendar's secret iCal address and Veyra shows you *In a meeting* while you have a meeting. Only the times are used; colleagues do not see your meeting titles.

## Voicemail

The **Voicemail** widget shows your messages and greetings. See [Your voicemail](guide:your-voicemail).

## Recent calls

**Recent calls** lists calls to and from your phones in the last 30 days. Filter by **Missed**, **Answered** or **To voicemail**, and use **Export** for a spreadsheet file.

- **Call back** calls the number for you: your desk phone rings first; pick it up and Veyra places the call.
- **Add to contacts** saves an unknown number with a name.
- **Recording** plays a recorded call, if your organization lets users play their own recordings.

## Contacts and speed dials

**Contacts** holds your personal phone book. Choose **New contact**, then fill in a **Name**, a **Company or place**, up to 5 **Numbers**, an **Email** and **Notes**.

- **Favourite** contacts come first. Tick **Favourite** in the contact, or use the button beside its name.
- **Speed dial (1–99)** marks a contact for one of your phone keys.
- **Import** takes lines of CSV text (name, company, number) or a file exported from here; **Export** downloads your contacts.
- **Call** rings your desk phone first, then calls the contact.

Names from your contacts are shown on your calls and voicemail.

## Colleagues

**Colleagues** shows who is available, on a call (red dot), or whose phone is offline, with their presence. Search by name or number, and use **Call** to call them through your desk phone.

## Phone keys

**Phone keys** shows the programmable keys of your desk phone. Keys with a lock are set by your administrator and stay. Keys marked **Yours** are free for you: choose **Set** and pick:

- **Speed dial**: calls a number (or one of your contacts) with one press,
- **Busy lamp**: lights up while a colleague is on the phone; press it to call them or pick up their ringing call,
- **Presence**: shows whether a colleague is available; press it to call.

Enter a **Label on the key** and choose **Save key**. The phone picks up the change within a minute. **Clear** empties the key.

## Send a fax

The **Conference** widget lists the conference rooms your phone owns: who is in each one, with mute, remove, lock, end, recording and **Invite a number**. An administrator makes your phone an owner on the room's page.

Everyone also has a personal room with no setup. Dial `*82` to open yours and tell colleagues to dial `*82` plus your extension. They hear hold music until you join, and the room ends when you hang up. It has no PIN and joins are announced, so anyone in your organization can join while you're in it: on your phone, `*2` locks the room and `*3` removes the last person who joined. It works only from phones in your organization and doesn't appear in this widget.

The **Fax** widget sends a PDF as a fax, no fax machine needed.

1. Choose **Send a fax**.
2. Enter the **Fax number**.
3. Choose the **PDF to send**: up to 20 MB and 50 pages.
4. Tick **Add a cover sheet** to add a first page with **To**, **From** (left empty, it shows your name), **Subject** and a **Note**.
5. Choose **Send fax**.

**Your faxes** lists what you sent with its state (**Waiting**, **Dialling**, **Sending**, **Sent**, **Failed**). You are emailed when a fax is delivered or fails. You can **Cancel** a fax still waiting and **Retry** a failed one.

## Codes you can dial

**Codes you can dial** lists the star codes your phone accepts, for example to turn Do Not Disturb or forwarding on and off from the phone itself. Your administrator may have changed the usual codes; this widget always shows the right ones for your phone.

## Arrange the page

1. Choose **Arrange**.
2. Drag a widget by its title bar, resize it from its corner, or remove it with its **×**. Widgets with a lock are required by your administrators and cannot be removed.
3. **Add widget** adds another, for example a second **Voicemail** for a shared inbox you watch. **Tab** adds a tab (up to 8); type in the box beside the tabs to rename the current one.
4. Choose **Save layout**. **Undo** takes back the last change; **Reset to default** returns to your administrators' layout.

On a phone or a narrow window, the widgets stack in order.

## If something doesn't work

- **"No phone is assigned to you":** ask your administrator to assign you an extension.
- **Phone not registered:** your desk phone is not connected. Check its network cable and power, or ask your administrator.
- **Call back or Call does nothing:** your desk phone rings first; pick it up. Check that Do Not Disturb is off.
