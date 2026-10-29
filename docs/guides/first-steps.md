---
title: First steps after installing Veyra
summary: Finish the setup wizard, then set Veyra up in the order that gets the first phones ringing.
audience: admin
section: Getting started
order: 10
reviewed: 0.27.45
covers:
  - frontend/src/app/(public)/setup/*
  - backend/veyra/api/v1/setup.py
  - backend/veyra/telephony/numbering.py
---

This guide takes you from a freshly installed server to the first working phones. It starts with the setup wizard, which you see only once, and then lists the order to set things up in.

## Before you start

- You need access to the server's console (the screen or an SSH session), to get the setup token.
- Know the name of your school district, town or company, and roughly how many extensions you need.

## 1. Run the setup wizard

Open the server's address in a browser. As long as nobody has set Veyra up, it shows **Set up Veyra**. The wizard has six steps.

1. **Verify access.** Paste the **Setup token**. The installer printed it when it finished. If you no longer have it, run `sudo veyra setup-token` on the server to make a new one. A token is valid for 24 hours and works once.
2. **Administrator account.** Enter your **Full name**, **Email address** and a **Password** (at least 12 characters), twice. This account becomes the platform administrator and the recovery account. Veyra refuses passwords that contain your name or email address, use fewer than four different characters, or are a common word repeated.
3. **Organization.** The **Organization name** is your district, town or business. The **Short name** is filled in from it (lower-case letters, digits and dashes). Choose it with care: it is part of every phone's SIP user name and cannot be changed later.
4. **Installation.** Give this server an **Installation name**, such as *District Phone System*, and pick the **Time zone**. The box underneath checks the telephony engine. If it does not say the engine is running, you can still continue and check it afterwards under System → Telephony Engine.
5. **Numbering plan.** Choose the **Extension length** (3 to 6 digits) and the **First extension** and **Last extension**. The default is 4 digits from 1000 to 7999. Extensions never start with 0 (operator), 9 (outside line), 911 or 933 (emergency).
6. **Review.** Check the details and choose **Finish setup**. You are signed in and land on the dashboard.

> **Note:** The wizard also lists, on the left, what you set up after it and where: *SIP and media addresses* (System → Telephony Engine), *Outside lines* (Telephony → SIP Trunks), *Email delivery* (System → Settings), *Backups* (System → Backups), *Update preferences* (System → Updates) and *High availability (optional)* (System → High Availability), each marked *After setup:* with its place. The order is described below.

## 2. Set up your second factor

Platform administrators and organization administrators must use a second factor (an authenticator app or a passkey). By default you have 14 days to set it up. Do it now from your account page, so that you are not locked out later. See [Settings: email, sign-in policy and retention](guide:settings) for how to change this rule.

## 3. Set things up in this order

Each step has its own guide.

1. **Email delivery.** Under [System → Settings](app:/settings/), fill in **Email delivery** so that Veyra can send voicemail, password reset links and alerts. See [Settings: email, sign-in policy and retention](guide:settings).
2. **Your organization and its sites.** Check the organization's details, then add a site for each campus or building, with its address and emergency caller ID. See [Organizations and sites](guide:organizations-and-sites).
3. **The telephony engine.** Check the SIP settings under System → Telephony Engine.
4. **Trunks and routes.** Connect your carrier (SIP Trunks), then decide where incoming numbers ring (Inbound Routes) and how outside calls leave (Outbound Routes). Set up emergency calling before anyone uses the phones.
5. **Extension templates** (optional). If many phones should behave the same, create a template first. See [Extension templates](guide:extension-templates).
6. **Users and roles.** Add the people who sign in and give them roles. See [Add users and give them roles](guide:users-and-roles).
7. **Extensions.** Create an extension for each phone. See [Add extensions](guide:extensions).
8. **Deploy the changes.** Changes to extensions, routes and trunks reach the phone system only when you choose **Deploy changes** in the top bar.
9. **Phones.** Connect the desk phones under Provisioning → Devices.
10. **Backups.** Turn on scheduled backups under System → Backups.

## If something doesn't work

- **"Invalid setup token":** the token is wrong, was already used or is older than 24 hours. Run `sudo veyra setup-token` on the server and paste the new one.
- **The address shows the sign-in page instead of the wizard:** setup has already been completed on this server. Sign in with the administrator account.
- **"Use at least 12 characters" or another password message:** choose a longer password that does not contain your name or email address.
