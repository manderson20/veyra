---
title: Set the My Phone layout for groups of users
summary: Choose which widgets people see on My Phone by organization, building, department or role, and lock the ones they must keep.
audience: admin
section: Phones and devices
order: 80
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /system/portal-layouts/
covers:
  - frontend/src/app/(app)/system/portal-layouts/*
  - frontend/src/components/portal/Canvas.tsx
  - frontend/src/portal/widgets.ts
  - frontend/src/portal/layout.ts
  - backend/veyra/api/v1/portal_templates.py
  - backend/veyra/portal/layouts.py
---

[My Phone](app:/my-phone/) is each user's own page: their phone's settings, voicemail, calls, contacts and more, arranged as **widgets** on one or more tabs. Users can rearrange it themselves (see [Your phone at a glance: My Phone](guide:my-phone)). A **portal layout** is the arrangement they start with. You can make different layouts for different groups, for example a simple one for classrooms and a fuller one for the front office, and you can **lock** widgets so users cannot remove them.

Layouts are managed under [System → Portal Layouts](app:/system/portal-layouts/). You need the `portal.templates` permission.

## Which layout a user gets

Each layout **Applies to** one scope:

- **A role**: users who have that role,
- **A department**: users whose extension is in that department,
- **A building**: users whose extension is in that building,
- **Whole organization**,
- **System-wide (every organization)**: platform administrators only.

A user gets the nearest one, in that order: a role's layout wins over a department's, which wins over a building's, then the organization's, then the system-wide one. When two layouts of the same scope match, the higher **Priority** (0 to 100) wins. Departments and buildings are taken from the user's first extension. Users with no matching layout see the built-in arrangement.

## Create a layout

1. Choose **New layout**.
2. Enter a **Name** and, if you like, a **Description**.
3. Choose **Applies to**, the **Organization**, and the **Building**, **Department** or **Role** when the scope needs one. These cannot be changed later.
4. Arrange the widgets:
   - The layout starts from the built-in arrangement. Add a widget with its button above the canvas (**My phone**, **Presence**, **Voicemail**, **Recent calls**, **Contacts**, **Colleagues**, **Phone keys**, **Fax**, **Codes you can dial**, **Announcement**).
   - Drag a widget by its title bar, resize it from the corner, and remove it with its **×**.
   - Add a tab with **Tab** (up to 8), rename the current tab in the box beside it, and remove it with the bin icon.
5. For each widget users must keep, turn on **Users cannot remove it**.
6. Leave **Enabled** on and choose **Save**.

### The Announcement widget

**Announcement** shows a note from you to everyone with this layout, for example *Fire drill Thursday 10:00*. Type it in the widget's **Text** box. Users cannot add this widget themselves; lock it so they cannot remove it either.

## What users can change

Users choose **Arrange** on My Phone to move, resize, add and remove widgets and tabs. Their arrangement is saved for them and stays theirs: later changes to the layout do not overwrite it. Locked widgets are the exception: a user cannot remove them, and if a locked widget is missing from their page, it is put back on their first tab.

To give everyone the current version of a layout, open it and choose **Push to users**. Every user who gets this layout loses their own arrangement and sees the layout again on their next visit. Their other settings stay.

## Delete a layout

Open it and choose **Delete**. Users fall back to the next matching layout or the built-in one; their own arrangements stay.

## Good to know

- A widget that shows one extension or voicemail box (**My phone**, **Presence**, **Voicemail**) shows the user's first one. Users with several can add more and pick which.
- A user with no extension and no voicemail box sees *No phone is assigned to you* on My Phone instead of the widgets.
