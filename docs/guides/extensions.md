---
title: Add extensions
summary: Create an extension for each phone, assign it to a person, and set its caller ID, location, voicemail and phone options.
audience: admin
section: Getting started
order: 50
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /extensions/
  - /extensions/view/
covers:
  - frontend/src/app/(app)/extensions/*
  - frontend/src/app/(app)/extensions/view/*
  - frontend/src/components/extensions/NumberingPlanCard.tsx
  - frontend/src/components/extensions/PendingChanges.tsx
  - frontend/src/components/extensions/PlaceFields.tsx
  - frontend/src/components/extensions/CallHandlingCard.tsx
  - frontend/src/components/extensions/FollowMeCard.tsx
  - frontend/src/components/extensions/VoicemailCard.tsx
  - frontend/src/components/extensions/DevicesCard.tsx
  - frontend/src/components/extensions/CallGroupsCard.tsx
  - backend/veyra/api/v1/extensions.py
  - backend/veyra/telephony/numbering.py
---

An **extension** is a number that a phone registers with, such as *1204*. It can belong to a person, or be a **shared phone** (a classroom, the front desk, a lobby phone). Each extension has a SIP user name and secret that the phone uses to connect.

The extensions are under **Telephony → Extensions**.

## Before you start

- Check the **Numbering plan** card at the bottom of the [Extensions](app:/extensions/) page: the extension length and the range new numbers come from.
- Add your sites and buildings first, so you can place each phone (see [Organizations and sites](guide:organizations-and-sites)).
- Create the users who will have their own phone (see [Add users and give them roles](guide:users-and-roles)).

## Create an extension

1. Open [Telephony → Extensions](app:/extensions/) and choose **New extension**.
2. The **Extension number** is already filled in with the next free number. Type another, or choose **Suggest next free**.
3. Enter a **Name**, for example *Front Office* or *Jane Doe*.
4. Pick the **Assigned user (optional)**, or leave it at **Shared phone (no user)**. Only active users of the same organization are listed. Picking a user fills in the name if it is empty.
5. If you like, fill in the **Caller ID name** and **Caller ID number** that colleagues see. They default to the name and the extension number.
6. **Emergency caller ID number:** the building's number registered for emergency calls. Leave it empty to use the site's or the emergency route's number.
7. Choose the **Site**, **Building**, **Location (dispatchable)** (such as *Room 101, first floor*) and **Department**. The site and building decide the address given on emergency calls; the location tells responders the room.
8. Leave **Enabled** on and choose **Create extension**.
9. Choose **Deploy changes** in the top bar. Until then the phone system does not know the new extension.

The number must have the plan's length, lie within its range, and not start with a reserved digit. It must also be free in the organization: extensions, ring groups and queues share one set of numbers.

## The extension's page

Choose an extension in the list to open it. The tabs across the top are:

### General

- **Details:** change the **Extension number**, **Name**, **Assigned user** or **Enabled**. Changing the number also changes the SIP user name, so the phone must be set up again.
- **Information:** the SIP user name (the organization's short name and the number, such as `lincoln-1204`), whether a secret is set, the class of service, and when it changed.
- **Location:** the site, building, dispatchable location and department.

### Caller ID

- **Caller ID name** and **Caller ID number:** what colleagues see on internal calls.
- **Outbound caller ID number:** sent to the carrier on outside calls. It must be one of the organization's numbers (from its inbound routes) or on the organization's allow list. Empty: the route's or the trunk's number is used.
- **Outbound caller ID name:** sent with it; carriers may replace it.
- **Emergency caller ID number:** sent on 911 calls instead of the regular caller ID.

### Call handling

- **Call handling:** **Do Not Disturb**, **Callers who still ring during Do Not Disturb**, **Call waiting**, **Refuse callers who hide their number**, the four forwards (all calls, when busy, when unanswered, when the phone is offline) and the **Ring time (seconds)** before voicemail or the no-answer forward. These take effect at once, except the ring time, which needs a deployment. Choose **Save call handling**.
- **Restrictions:** the **Extension template** the extension follows (shown once a template exists), the **Class of service** (which outside routes and feature codes it may use) and **Intercom** (whether other phones can call it on speaker). Settings locked by a template cannot be changed here. See [Extension templates](guide:extension-templates).

The person can change their own forwarding and Do Not Disturb on My Phone or with the feature codes. See [Feature codes people can dial](guide:feature-codes).

### Follow me

Rings other numbers, such as a mobile, as well as the desk phone. Add up to 10 numbers with **Add a number**, choose whether they ring **All at once** or **One after another**, and choose **Save follow me**. Then switch **Follow me** on. **Outside numbers must press 1 to accept** stops a mobile's voicemail from taking the call.

### Voicemail

Shows the extension's voicemail box. Without a box, unanswered calls simply end. Choose **Create box** (or **Edit box**) to set:

- the **PIN** (4 to 10 digits; leave it empty for a random one, shown once),
- the **Ring time (seconds)** before voicemail answers,
- the **Operator extension (press 0)**,
- the email for new messages: **Use the extension user's email address**, or another address, with **Attach the recording to the email** and **Delete the message from the box once it has been emailed**,
- **Delete messages older than (days)**.

From the phone, the person dials `*97` for their greeting and messages. Email needs email delivery to be set up under [System → Settings](app:/settings/).

### Phones

- **Registered phones:** the phones connected as this extension right now, with their address, model and whether they are reachable.
- **Phones that may register:** how many phones may use this extension at once, 1 to 16. Empty means as many as are provisioned with it. Raise it to let a softphone register beside the desk phone.
- **Hotline number:** lifting the handset dials this number at once. Use it for elevator, lobby, door and emergency phones. With **Warm-line delay (seconds)** above 0, the phone first waits that long for a digit.
- **Fax machine (T.38):** switch it on when a fax machine is plugged into an ATA port for this extension, and your trunk supports T.38. Off, the fax travels as audio, which works with any trunk. Set the ATA's fax mode to match.
- **Phones:** the provisioned devices carrying this extension, as line 1 or as an extra line.

The hotline, phone count and T.38 setting need a deployment.

### Groups

The ring groups, call queues and pickup groups the extension belongs to.

### Credentials

The **User name** and **Secret** the phone registers with. **Show secret** reveals it (this is recorded in the audit log). **New secret** replaces it: the phone stops registering until it gets the new secret and you deploy.

## Delete an extension

Choose **Delete** at the top of the extension's page and type the extension number to confirm. The phone stops working at the next deployment.

## Change the numbering plan

People who can change system settings see a form in the **Numbering plan** card on the [Extensions](app:/extensions/) page: **Extension length**, **First extension**, **Last extension** and **Reserved leading digits** (keep 0, 9, 911 and 933). Choose **Save plan**. Existing extensions keep their numbers; the plan applies to new and renumbered ones. The numbering plan is shared by every organization on the server.

## If something doesn't work

- **"Changes not yet deployed":** choose **Deploy changes** in the top bar.
- **"Installation key missing":** Veyra cannot store or show SIP secrets. Run `sudo veyra installation-key check` on the server.
- **A *No secret* badge:** choose **New secret** on the Credentials tab.
- **The phone does not register:** check the user name and secret on the phone against the Credentials tab, and that you deployed. The **Registers from** column shows where a phone connects from; *behind NAT* means it is behind a router.
- **"Extensions are numbered from … to …" or "Numbers starting with … are reserved":** pick a number inside the plan's range.
- **"Number in use":** an extension, ring group or queue already has that number.
- **"The user belongs to a different organization":** a user can only be assigned to an extension of their own organization.
