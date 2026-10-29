---
title: Set up fax
summary: Receive faxes as PDFs by email, let staff send PDFs as faxes from My Phone, and connect fax machines through an analog adapter.
audience: admin
section: Voicemail and fax
order: 20
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /fax/
covers:
  - frontend/src/app/(app)/fax/*
  - frontend/src/components/portal/FaxCard.tsx
  - backend/veyra/api/v1/fax.py
  - backend/veyra/api/v1/me_fax.py
  - backend/veyra/fax/service.py
---

Veyra handles fax in three ways:

- **Receiving:** a fax number of yours answers as a **fax inbox**. The pages arrive by email as a PDF.
- **Sending from the browser:** staff send a PDF as a fax from the **Fax** widget on [My Phone](app:/my-phone/). No fax machine needed.
- **Fax machines:** an existing fax machine plugs into an analog telephone adapter (ATA) port and works like any extension.

Everything is managed under [Telephony → Fax](app:/fax/).

## Before you start

- Fax emails need an SMTP server on the **Email delivery** card under [Settings](app:/settings/).
- Set the organization's **Fax header** (the line printed at the top of sent pages) and **Fax station ID** (the number announced to the other machine) on the organization's page under [Organizations](app:/organizations/). Inboxes can override them.
- Fax travels over your SIP trunk. If your carrier supports T.38 fax relay, turn on **Fax over T.38** on the trunk; otherwise faxes travel as audio, which works with most carriers.

## Receive faxes by email

1. Choose **New fax inbox**.
2. Enter a **Name**, for example *Front office*.
3. Under **Email the PDF to**, enter up to 20 addresses, one per line.
4. Optionally set a **Station ID** (digits, `+` and spaces) and a **Page header** (up to 64 characters). Empty uses the organization's.
5. Choose **Create inbox**.
6. Point your fax number at it: on the DID or the inbound route, choose the destination **Fax to email** and this inbox.
7. Use **Deploy changes** in the top bar.

A fax that arrives is converted to a PDF, emailed to the recipients and listed under **Faxes**. An inbox with no recipients shows **No recipients**: its faxes are only listed. A disabled inbox is kept, but the routes pointing at it stop receiving.

## Sending from My Phone

Users with an extension see the **Fax** widget on My Phone: they enter the **Fax number**, pick a **PDF to send** (up to 20 MB and 50 pages), optionally **Add a cover sheet**, and choose **Send fax**. The fax goes out with the extension's outbound caller ID, and the user is emailed when it is delivered or fails. See [Your phone at a glance: My Phone](guide:my-phone).

- Veyra tries up to 3 times when the line is busy or does not answer, a few minutes apart.
- To stop some phones from sending faxes, untick **May send faxes from My Phone** in their class of service.
- The server needs Ghostscript to convert PDFs; if it is missing, sending answers *Fax unavailable*.

## Follow faxes

The **Faxes** card lists sent and received faxes, newest first, with filters for direction and state (**Waiting**, **Dialling**, **Sending**, **Sent**, **Failed**, **Received**, **Cancelled**). The list refreshes by itself while faxes are on their way. Administrators who can manage fax can:

- download a fax as **PDF**,
- **Cancel** a fax that is still waiting or in progress,
- **Retry** a failed or cancelled send.

Faxes and their files are kept for 90 days by default; a platform administrator can change that on the **Retention** card under Settings. A fax whose file was removed can no longer be retried.

## Fax machines on an analog adapter

Connect the fax machine to a port of an analog telephone adapter (ATA) and give that port its own extension, like any phone. On the extension's page, the **Fax machine (T.38)** switch decides how faxes travel:

- **On:** Veyra offers T.38 to the adapter, so faxes are relayed end to end. Use it when the trunk has **Fax over T.38** turned on. Set the adapter's fax mode to T.38 as well.
- **Off (default):** the fax travels as ordinary audio (G.711). This works with any trunk; set the adapter's fax mode to pass-through.

The change needs a deployment.

## If something doesn't work

- **Faxes fail with errors part-way through:** try the other setting of **Fax machine (T.38)** or **Fax over T.38** on the trunk, matching what your carrier supports.
- **No email for received faxes:** check the inbox's recipients and the Email delivery settings.
- **"Fax not allowed":** the user's class of service does not allow sending faxes.
- **"No phone":** faxes are sent with the user's extension's caller ID; the user has no extension.
