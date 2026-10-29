---
title: Your voicemail
summary: Listen to your messages from your phone or the browser, record your greetings, set an away message for the holidays, and choose your PIN.
audience: user
section: Using Veyra
order: 20
reviewed: 0.27.44
pages:
  - /my-phone/
covers:
  - frontend/src/components/voicemail/VoicemailInbox.tsx
  - frontend/src/components/voicemail/GreetingsPanel.tsx
  - frontend/src/components/voicemail/LocaterField.tsx
  - frontend/src/components/account/MyVoicemailCard.tsx
  - backend/veyra/api/v1/me.py
  - backend/veyra/telephony/features.py
---

When you don't answer, are on another call or have Do Not Disturb on, callers can leave you a message. Your desk phone's message lamp lights up when you have new messages. If your administrator has set it up, each new message is also emailed to you with the recording attached.

You can listen to messages from your desk phone, or in the browser on [My Phone](app:/my-phone/).

## From your desk phone

1. Dial **\*97**.
2. Enter your PIN, then press **#**.
3. Press **1** to listen to your messages.

While a message plays or after it, the usual keys are: **4** previous message, **5** repeat, **6** next message, **7** delete, **9** save it to a folder. Press **0** for your mailbox options, where you record your greetings: **1** unavailable greeting, **2** busy greeting, **3** your name, **4** temporary greeting. The voice prompts tell you the keys at every step.

From another phone, dial **\*98**, then enter your mailbox number (your extension) and your PIN.

> **Note:** These are Veyra's usual codes. If they do not work, check the **Codes you can dial** widget on My Phone; your administrator may have changed them.

## In the browser

On [My Phone](app:/my-phone/), the **Voicemail** widget has two tabs.

**Messages** shows your messages by folder (**New**, **Old** and others). For each message:

- **Play** listens in the browser.
- **Call me** rings your desk phone and plays the message there, useful in a shared office.
- **Move** puts it in another folder. Moving a new message to *Old* marks it as heard on the phone too.
- **Forward** sends a copy to a colleague's box.
- **Email** sends it to your email address with the recording attached. **Delete it from the voicemail box once the email is sent** is ticked by default; untick it to keep a copy in the box.
- **Delete** removes it.

**Greetings** lists your greetings, each **Recorded** by you or **Standard** (the phone system's own):

- **Unavailable**: played when you do not answer.
- **Busy**: played when you are on another call.
- **Name**: your name, used by the directory and the standard greetings.
- **Temporary**: played instead of the others while it exists. Remove it when you are back.
- **Extended absence** and **After hours**: see below.

For each one, **Record** records it with your computer's microphone (up to 60 seconds; listen to it, then **Save greeting**), **Upload** takes an audio file, and **Remove** goes back to the standard greeting.

## Away for a while: extended absence

For the summer break or a leave:

1. Record or upload your **Extended absence** greeting, for example *I am away until August 20. For urgent matters, call the front office at 1000.*
2. Under **Extended absence**, pick the **First day** and **Last day**. Leave **First day** empty to start now, and **Last day** empty to keep it on until you turn it off. Choose **Save dates**.
3. Turn on **Extended absence**.
4. To stop messages piling up while you are away, tick **Take no messages while away**: callers hear your greeting and the call ends.

On the first day, callers hear your absence greeting; after the last day, it turns itself off.

## After hours

If your administrator has set office hours for your box, your **After hours** greeting plays instead of the unavailable one while the office is closed. A temporary greeting still takes priority.

## Your PIN and greeting keys

On [your account page](app:/account/), the **Voicemail** card shows where your new messages are emailed and how long your phone rings before voicemail answers.

- **Change PIN** sets a new PIN of 4 to 10 digits. It starts working after your administrator's next deployment of changes, so keep using the old one until then.
- **Greeting keys** lets callers press a key during your greeting instead of leaving a message: **Press 1 during the greeting** can try your follow-me numbers or ring another number, and **Press 2 during the greeting** can ring another number. Say so in your greeting, for example *press 1 to try my mobile*.

> **Tip:** Change your PIN on your account page rather than from the phone's mailbox options, so that Veyra keeps it.

## Shared inboxes

If you watch a shared inbox, such as an attendance line, it appears as another **Voicemail** widget on My Phone (or add one with **Arrange → Add widget**), and your message lamp also lights for it. From a phone, dial **\*98** and enter the inbox's number and PIN.

## If something doesn't work

- **The PIN is refused:** if you changed it recently, the old one works until the next deployment. Otherwise ask your administrator to reset it.
- **No voicemail emails:** your administrator controls email delivery and the address it goes to.
- **The browser cannot record:** allow the microphone for this site, or upload a recording, or record from the phone with \*97.
