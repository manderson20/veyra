---
title: Customize a base file
summary: Change what Veyra writes into phones' configuration files with your own base file, edited in the browser, previewed, exported and imported.
audience: admin
section: Phones and devices
order: 60
reviewed: 0.27.63
pages:
  - /provisioning/
  - /provisioning/view/
covers:
  - frontend/src/app/(app)/provisioning/*
  - frontend/src/app/(app)/provisioning/view/*
  - frontend/src/components/provisioning/*
  - backend/veyra/api/v1/provisioning.py
  - backend/veyra/provisioning/catalog.py
---

A **base file** turns what Veyra knows about a phone (its extensions, keys, paging zones, time zone…) into the files the phone downloads. Most of the time the official base files are all you need, and the settings in a [phone template](guide:device-profiles) cover the rest. Make your own when you need a phone setting that no base file setting offers.

You never change an official base file. You make a **local** base file that inherits from it and replaces only the parts you change. Veyra updates can then improve the official base file without overwriting your work.

> **Note:** Base files are written in Jinja2, a simple text template language. You need to know the phone vendor's configuration parameter names. Test every change on one phone first.

## Look at a base file

Open [Provisioning → Base Files](app:/provisioning/) and click a base file. Base files are grouped by brand. The list shows each base file's models (or *Family*), version and source: **Official**, **Community** or **Local**, plus a status badge when it is not stable.

The base file's page has these tabs:

- **Overview:** manufacturer, models, the firmware it was written for, its features and description. **Inheritance and files** shows the chain of base files it inherits from and the files it produces (for example `{mac}.cfg`).
- **Variables:** the settings a profile or device can give, with their type, default, and whether they are required or secret.
- **Preview:** fill in sample values, pick a model and a MAC address, and choose **Render preview** to see the files. Secrets are masked. Base base files cannot be previewed: open one of their model base files.
- **Edit:** only on local base files, for people who may change provisioning.

## Make an editable copy

1. Open the official base file and choose **Customize**.
2. Fill in:
   - **Template key** (required): a unique name of lower-case letters and digits in two to eight parts separated by dots or dashes, for example `local.vvx.450`.
   - **Name** (required), for example *Poly VVX 450 (ours)*.
   - **Organization:** the organization it belongs to. A platform administrator can leave it on **Platform-wide (all organizations)**.
3. Choose **Create editable copy**.

The copy starts at version 0.1.0, marked experimental, with nothing changed: each file just extends the official one and has an empty `model_settings` block where your changes go.

If you customize a **family** (base base file), Veyra also makes a local model base file under your copy for each model of the family. Point a profile at your family copy to use them.

> **Warning:** When a phone's profile points at a family, Veyra uses a local model base file in that family before the official one. So customizing a model base file, such as Poly VVX 450, changes the files of every VVX 450 whose profile uses the Poly VVX family as soon as you save — in the base file's organization only, or in every organization for a **Platform-wide** base file. Other organizations neither use nor see an organization's local base files. Profiles that point at the official model base file directly keep it.

## Edit a local base file

Open the local base file and go to the **Edit** tab.

**Template card**

- **Name** and **Version** (required). The version is a number like `0.1.1`. Raise it when you change the base file; the previous version is replaced, not kept.
- **Models:** the model names this base file serves, separated by commas. A family has no models of its own.
- **Status:** **Experimental**, **Stable (verified on hardware)** or **Deprecated**.
- **Description.**

**Variables card**

Variables are settings that a profile or device can fill in, used in a file as `{{ name }}`. Choose **Add a variable** and give it:

- **Name** (required): lower-case letters, digits and `_`.
- **Type:** **Text**, **Number** or **Yes / no**, and a **Default**.
- **Description:** shown next to the field on the profile and device.
- **Required**, and **Secret** (masked in previews, never exported, no default).
- For text: an **Allowed pattern** (a regular expression the value must match) and a **Maximum length**.

Under **Inherited from the parent** you can give a different default to any setting the base file inherits. Leave it empty to keep the parent's.

**Files card**

Pick a file under **File** and edit it in the box. In a base file with a parent, the file starts with `{% extends %}`, and each `{% block %}` replaces that part of the parent's file.

The **Insert a Veyra variable** panel next to the box lists everything you can use. Click an entry to insert it where the cursor is. Search it, or open a section:

- **This template's values:** its variables.
- **Device**, **Organization**, **Lines**, **Keys**, **Paging**, **Paging zones**, **Server**, **Features:** what Veyra knows about the phone. Lines, keys and paging zones are lists: first insert the loop at the top of the section, then the entries inside it.
- **Provisioning variables:** the [provisioning variables](guide:provisioning-variables) defined under Provisioning → Variables, inserted as `{{ vars.name }}`. Each phone gets the value of its site, its organization or the installation.
- **Snippets:** common patterns, such as *Only when set*, *Yes/no as 1/0* and *Override a block*.

Choose **Save template**. Veyra checks the base file first. If something is wrong, **The template did not validate** lists the problems and nothing is saved. Phones using the base file get the change at their next check.

## Export and import

- **Export** (on any base file) shows the base file as JSON. Choose **Copy JSON** to save or share it. Exports never contain SIP passwords or other secrets.
- **Import base file** (on the Base files list) takes such JSON. Paste it under **Template export (JSON)**, choose the **Organization**, then **Validate**. When it says **Template is valid**, choose **Import**. It becomes a local base file.

## Delete a local base file

**Delete** works only when no phone template uses the base file and no other base file inherits from it.

## When Veyra updates an official base file

After a Veyra update, a local base file whose official parent has a new version shows **Parent updated** in the list. Your base file keeps working, and phones already get the new parent together with your changes. Compare it with the new parent (open the parent from **Inheritance and files**) to see whether the parent now does what you added, or changed something you rely on, and check **Preview**. Veyra keeps only the current official version, so it cannot list what changed. When it looks right, choose **Take version …** on your base file's page: the note goes away. If your base file does not work with the new parent, Veyra says why and leaves it as it is.

## If something doesn't work

- **"Template key … is already used."** Choose another key.
- **The preview says "Could not render".** The list names the problem, often a misspelled name or an unclosed `{% if %}` or `{% for %}`.
- **A setting you wrote does not reach the phone.** Check that your change is inside a block that the parent file has. Text outside the blocks of a file with `{% extends %}` is ignored. Veyra refuses to save a block the parent file does not have. **Customize** names the blocks you can override; when a parent file has none, such as the Algo base file's, you get a full copy of the file to edit, which does not follow later versions of the parent's file.
- **The Base Files list shows "Some base files could not be loaded".** A stored base file failed its checks, for example after its parent changed, and phones cannot use it. Choose its name in the message to see the problem and its stored text, then fix it with **Save and check**, or delete it.
