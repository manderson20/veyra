---
title: Dial by name
summary: Let callers reach people and offices by spelling a name on the keypad.
audience: admin
section: Calls and call flows
order: 50
reviewed: 0.27.44
pages:
  - /name-directory/
covers:
  - frontend/src/app/(app)/name-directory/*
  - backend/veyra/api/v1/name_directory.py
---

The dial-by-name directory lets a caller spell a first or last name on the keypad, hear the extension, and be connected. Callers reach it from a menu (an IVR key) or an inbound route that points to it.

Everyone whose extension has a voicemail box is listed by themselves. On this page you add the other names callers might spell, such as *Front office*, *Nurse* or *Attendance*, and the operator for 0.

The page is under **Telephony → Dial by Name**.

## Add a name

1. Open [Telephony → Dial by Name](app:/name-directory/). If you manage several organizations, pick the **Organization** first.
2. Choose **Add a name**.
3. **Name:** what callers spell, for example *Front office*. Callers can spell the first or the last word. Use letters, digits, spaces and `. ' & ( ) / -`, up to 100 characters.
4. **Number:** an extension, ring group or queue of the organization.
5. Choose **Add**.
6. Choose **Deploy changes** in the top bar.

To change a name, choose its row. To remove it, choose the bin icon. Both need a deployment.

## Set the operator

In the **Operator** card, enter the **Operator number**: an extension, ring group or queue. A caller in the directory who presses 0 goes there. Leave it empty and 0 says goodbye. Choose **Save**, then deploy.

## If something doesn't work

- **A person is missing from the directory:** they are listed only when their extension has a voicemail box. Create one on the extension's **Voicemail** tab, or add them here.
- **Callers cannot reach the directory:** point an IVR key or an inbound route at it.
