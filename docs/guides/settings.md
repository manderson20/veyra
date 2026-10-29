---
title: Settings: email, sign-in policy and retention
summary: Set up email delivery, the two-factor rule, how long data is kept, the installation key and multi-tenancy.
audience: admin
section: Getting started
order: 70
reviewed: 0.27.44
pages:
  - /settings/
covers:
  - frontend/src/app/(app)/settings/*
  - frontend/src/components/account/EmailDeliveryCard.tsx
  - frontend/src/components/account/MfaPolicyCard.tsx
  - frontend/src/components/account/RetentionCard.tsx
  - frontend/src/components/account/InstallationKeyCard.tsx
  - frontend/src/components/organizations/MultiTenancyCard.tsx
  - backend/veyra/api/v1/smtp.py
  - backend/veyra/api/v1/retention.py
  - backend/veyra/core/retention.py
  - backend/veyra/core/security/mfa.py
  - backend/veyra/core/tenancy.py
---

[System → Settings](app:/settings/) holds the settings that apply to the whole server. Everyone sees the **Installation** card (name, version, deployment, whether multi-tenancy and central management are on) and **Appearance**, where you choose a light, dark or automatic theme for your own browser. The other cards appear only to administrators who may see system settings; some are for platform administrators only.

The **HTTPS certificate** card and the Companion settings on the same page have their own guides.

## Email delivery

Veyra sends email through your mail server: voicemail notifications, password reset links, alerts and other messages. Until this is set up, nothing is emailed.

1. Switch on **Send email**.
2. Enter the **SMTP server** (for example `smtp.office365.com` or `smtp-relay.gmail.com`) and the **Port**.
3. Choose the **Connection security**: **STARTTLS (usually port 587)** or **TLS from the start (usually port 465)**. **None** is allowed only for a relay on the server itself.
4. If the server needs a sign-in, enter the **User name** and **Password**. Leave the user name empty for no sign-in. The password is stored encrypted and never shown again; to keep it, leave the field empty.
5. Enter the **From address** and **From name**. Many mail servers only accept their own domain as the sender.
6. Choose **Save settings**.
7. Choose **Send me a test message**. Veyra sends it to your own account's email address and shows whether the server accepted it.

The line under the form shows the **Queue**: messages waiting to be sent, and messages given up on after a day of retries. Each one given up on is in the audit log as `mail.failed`.

> **Tip:** With Google Workspace or Microsoft 365, the simplest choice is often their SMTP relay service with the Veyra server's address allowed, so no password is needed.

## Two-factor policy

Decides who must use a second factor when signing in to Veyra.

- **Required for:** tick the roles that must use one. By default these are Platform Administrator and Organization Administrator.
- **Allowed second factors:** **Passkeys** (Touch ID, Windows Hello, a security key or a phone; needs the server's name and a trusted certificate) and **Authenticator apps** (six-digit codes). At least one must stay ticked.
- **Days to set it up:** after their first sign-in with such a role, people can sign in without a second factor for this many days (0 to 365; default 14). 0 means they must set it up at once.
- **Trust a browser for (days):** people may tick *Trust this browser* and then sign in there with just the password for this many days (0 to 90). 0 turns it off.

Choose **Save policy**. Affected people are told at their next sign-in.

The recovery administrator is not exempt. If they lose their second factor, run `veyra users mfa-reset` on the server. People who sign in with [single sign-on](guide:single-sign-on) use their provider's second factor instead.

## Retention

Platform administrators decide how long Veyra keeps each kind of data. The table shows each kind with its days, how many rows it has, its size, and its oldest entry.

| Data | Default (days) | Lowest allowed |
|---|---|---|
| Audit log | 730 | 365 |
| Call history | 400 | 30 |
| Alert history | 365 | 30 |
| Update history | 730 | 90 |
| Cluster events | 730 | 90 |
| Firewall events and expired bans | 90 | 7 |
| Provisioning request log | 30 | 7 |
| Page log | 90 | 7 |
| Faxes | 90 | 7 |
| Packet captures | 7 | 1 |
| Engine metrics samples | 14 | 2 |
| Central console samples | 30 | 7 |

To change it, type the days in **Keep (days)** and choose **Save**. Going below 30 days asks you to type `SHORTEN` to confirm. Old data is removed once a day; **Apply now** removes it at once. Removed data can only be recovered from a backup.

Voicemail messages are kept per box (on the extension's Voicemail tab), not here.

## Installation key

The installation key encrypts the stored secrets: SIP passwords, the SMTP password, two-factor secrets and recordings. The card shows its **Fingerprint** and the result of the last rotation.

To replace it, choose **Rotate the key…**, then **Rotate now**. Veyra makes a new key and re-encrypts every secret with it. The web interface and the worker restart, which takes under a minute; calls are not affected. Afterwards take a backup, and remove the previous key file from the server once the backup is verified.

## Multi-tenancy

Multi-tenancy lets one Veyra server serve several organizations whose phones cannot reach each other. The card shows whether it is **On** or **Off**, how many organizations are active, and what every organization shares (trunks, the numbering plan, the mail server, the firewall, updates, modules and sign-in providers).

- **Turn on:** choose **Turn on**, then **Run checks and turn on**. Veyra first builds the configuration with a test copy of your organization and proves that neither can reach the other's phones, voicemail or queues. Your current organization and its phones do not change. Then you can add organizations (see [Organizations and sites](guide:organizations-and-sites)).
- **Turn off:** only possible while a single organization is active.

## If something doesn't work

- **The test message fails:** read the message Veyra shows. Check the server name, port and security together (587 with STARTTLS, or 465 with TLS), and the user name and password. Check that the mail server accepts the **From address**.
- **"Unencrypted delivery … is only allowed to a loopback relay":** choose STARTTLS or TLS.
- **"Enter the password for the SMTP user name":** a user name needs a password.
- **The card says *Needs attention*:** the saved settings have a problem; it is shown in the yellow box.
- **Turning on multi-tenancy fails:** the list under the card shows which check failed.
