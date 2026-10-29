---
title: Extension templates
summary: Give many extensions the same settings at once, and lock the ones people should not change.
audience: admin
section: Getting started
order: 55
reviewed: 0.27.44
pages:
  - /extension-templates/
covers:
  - frontend/src/app/(app)/extension-templates/*
  - frontend/src/components/extensions/ExtensionTemplateDialog.tsx
  - backend/veyra/api/v1/extension_templates.py
---

An **extension template** is one set of settings that many extensions follow, for example *Classroom phones* or *Office staff*. When you change the template, you apply it again and every extension that follows it gets the new settings.

A template can also **lock** a setting. A locked setting cannot be changed on the extension while it follows the template.

The templates are under **Telephony → Extension Templates**.

## What a template can set

| Setting | What it does |
|---|---|
| **Class of service** | Which outside routes and feature codes the phones may use |
| **Intercom** | Whether other phones can call them on speaker |
| **Phones that may register** | How many phones may use each extension at once (1 to 16) |
| **Department** | The department the extensions are in |
| **Ring time (seconds)** | How long they ring before voicemail or the no-answer forward (5 to 120) |
| **Call waiting** | Switch call waiting off |
| **Callers who hide their number** | Refuse outside callers without caller ID |
| **Outside caller ID number** and **name** | What the carrier is sent on outside calls |
| **Forward when busy**, **Forward when not answered**, **Forward when the phone is offline** | Where those calls go |
| **Attach the recording to the email** | For the extension's own voicemail box |
| **Delete after email** | Delete voicemail once it has been emailed |
| **Delete messages older than (days)** | 1 to 3650 |
| **Operator extension (0 in voicemail)** | Where a caller goes when pressing 0 in voicemail |

Anything the template does not set stays as each extension has it.

## Create a template

1. Open [Telephony → Extension Templates](app:/extension-templates/) and choose **New template**.
2. Enter a **Name** and, if you like, a **Description**.
3. Tick each setting the template should set, and fill in its value.
4. Tick **Locked** next to a setting to stop it being changed on the extensions.
5. Choose **Create template**.

## Put extensions on a template

Open an extension, go to the **Call handling** tab, and pick the template under **Extension template** in the **Restrictions** card. Choose **Save changes**. All the template's settings are applied when you save.

## Apply a changed template

After editing a template, its extensions keep their old values until you apply it.

1. On the templates page, choose **Apply…** next to the template.
2. Veyra lists each extension that differs from the template, with every change (for example *Ring time: 20 → 30*).
3. Choose **Apply to … extensions**.

Some settings, such as the ring time and intercom, reach the phone system only at the next deployment. Choose **Deploy changes** in the top bar when Veyra asks.

## Delete a template

Choose the bin icon next to the template. Its extensions keep their current settings and stop following it; nothing is locked any more.

## If something doesn't work

- **"Set by the template" when saving an extension:** that setting is locked by the extension's template. Change the template instead, or unlock the setting there.
- **The Extension template field is missing on an extension:** no template exists in its organization yet.
- **Apply… is greyed out:** no extension follows this template yet.
