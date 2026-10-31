---
title: Import and export with CSV files
summary: Create or change many extensions, users, routes or groups at once with a spreadsheet, or move from FreePBX.
audience: admin
section: Maintenance
order: 40
reviewed: 0.27.64
checked: 2026-10-30T15:10Z
pages:
  - /system/import/
covers:
  - frontend/src/app/(app)/system/import/*
  - backend/veyra/api/v1/bulk.py
  - backend/veyra/bulk/*.py
---

Open [System → Import and Export](app:/system/import/). You can export what exists as a CSV file, change it in a spreadsheet, check it, and import it again. Every row goes through the same checks as the web pages, so a CSV cannot do anything the pages would refuse.

## What you can import

**Extensions**, **Users**, **Ring groups**, **Queues**, **IVR menus**, **Time conditions**, **Inbound routes** and **Shared voicemail inboxes**.

## How the file works

- The first line names the columns. An export is always a valid import.
- The **first column is the key**: extensions, ring groups, queues and shared inboxes by `number`, users by `email`, inbound routes by `did`, IVR menus and time conditions by `name`, phones by `mac`. A row whose key exists **updates** it; otherwise it **creates** a new one.
- **An empty cell keeps** the current value. **A dash (`-`) clears** it.
- Yes/no cells take `yes` or `no`. Lists (such as `members`, `pickup_groups` or `roles`) are separated by `;`.
- At most 5,000 rows and 5 MB per file. A key appearing twice is an error.
- Importing never deletes an extension, user or other item; remove those on their own pages. List columns such as `members` are the full list, though: a member left out of the list leaves the group.

> **Tip:** Import **users before the extensions** that name them (`user_email`), and extensions before the groups that list them.

## Export or get a template

1. Under **1. Choose what**, pick the **Kind** (and the **Organization**, if you have several). The columns are listed below it.
2. **Export …** downloads what exists today. **Blank template** downloads just the header line.

## Check, then import

1. Change the file in a spreadsheet and save it as CSV.
2. Under **2. Check and import**, choose the **CSV file**.
3. Choose **Check the file**. Nothing changes yet. The summary says how many rows would be created, updated, unchanged or have errors, and the **Rows** table shows each line with **Create**, **Update**, **No change** or **Error** and the reason.
4. Fix the errors in the file and check again, or go ahead without them.
5. Choose **Import n rows**. Rows with errors are left out and listed.
6. Use **Deploy changes** in the top bar to send the changes to the phone system. See [Deploy changes to the phone system](guide:deploy-changes).

If you can export but not import a kind, the page says *You cannot change …*: your role lets you see it but not change it.

## Moving from FreePBX

The **From FreePBX** card turns a FreePBX database into the files above. Extensions, ring groups, queues, IVR menus, time conditions and inbound routes come across.

1. If FreePBX used shorter extensions than Veyra's numbering plan, widen the numbering plan under Settings first.
2. On the FreePBX server run `mysqldump asterisk > asterisk.sql` (it may be gzipped).
3. Choose the file under **FreePBX database dump**. Optionally add `voicemail.conf` to keep PINs and emails, and the output of `asterisk -rx "database show QPENALTY"` saved as a text file to keep queue agents who log in with a code.
4. Choose **Read the FreePBX files**. Nothing is saved yet. A list of *things to do by hand* shows what could not be converted.
5. Bring the recordings and hold music over: on the FreePBX server run `tar czf audio.tar.gz -C /var/lib/asterisk sounds/en/custom moh`, choose the file under **Audio archive** and choose **Import the audio**. Keep the database dump chosen, so recordings keep the names the IVR menus look for. The archive can be up to 1000 MB. Nothing already in the library is changed, so you can run it again. A list shows anything that could not be read, for example a file over 25 MB or 5 minutes.
6. Choose each **Check n …** button in order (extensions, ring groups, queues, IVR menus, time conditions, inbound routes). Each loads the converted file into **2. Check and import**; check it and import it before the next.

> **Note:** SIP passwords are not carried over from FreePBX.
