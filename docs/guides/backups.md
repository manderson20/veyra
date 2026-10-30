---
title: Backups and restore
summary: Schedule verified, encrypted backups, copy them to a NAS, an SFTP server or S3 storage, and restore a server from one.
audience: admin
section: Maintenance
order: 20
reviewed: 0.27.56
checked: 2026-10-29
pages:
  - /system/backups/
covers:
  - frontend/src/app/(app)/system/backups/*
  - backend/veyra/api/v1/backups.py
  - backend/veyra/backups/*.py
  - frontend/src/components/backups/*
---

Open [System → Backups](app:/system/backups/). Veyra backs up everything needed to rebuild the phone system:

- the database (extensions, users, call flows, settings, call history),
- the configuration and secrets, including the keys and certificates phones trust,
- the telephony engine's configuration,
- prompts, hold music, firmware, provisioning templates and modules,
- voicemail,
- and, if you choose, call recordings.

Every backup is **verified before it counts**: Veyra restores the database into a scratch database, compares it, and checks every file. A backup that fails verification is kept, marked failed, and raises an alert.

Scheduled backups are **on** from installation, every day at 02:30 server time.

## The summary

Three cards at the top:

- **Last good backup:** when the last verified backup was taken. *No verified backup in the last two days* means something is wrong.
- **Encryption:** **age** when backups are encrypted, **Off** when they are not.
- **Schedule:** the daily time, or **Off**, and the last error if the last run failed.

## Settings

Choose **Save** after changing any of these.

- **Scheduled backups:** on or off.
- **Time of day:** server local time, such as `02:30`.
- **Keep daily for (days)** (default 14), **Then one per week for (weeks)** (default 8), and **Keep pre-upgrade backups** (default 3). Old backups are removed only after a new one succeeds.
- **Include call recordings:** recordings are usually the largest files. Without them, a restore keeps the list of recordings but not the audio.
- **Encryption recipients (age public keys, one per line):** see below.

## Turn on encryption

Without encryption, backups stay on the server, readable only by its administrator (root). Before backups leave the server, encrypt them.

Veyra encrypts with [age](https://age-encryption.org) to a *public* key you give it. Only the matching *private* key can decrypt, and Veyra never has it.

1. On a computer that is **not** the Veyra server, install age and run `age-keygen -o veyra-backup-identity.txt`. It prints a public key starting with `age1…`.
2. Paste that public key into **Encryption recipients** and **Save**. An SSH public key (`ssh-ed25519 …`) works too.
3. Keep `veyra-backup-identity.txt` safe, in more than one place, such as your password manager or a safe.

> **Warning:** Without the private key, an encrypted backup cannot be restored by anyone. Test a restore once, on a spare server, while you still have the original.

## Copy backups off the server

A backup that only lives on the server is lost with the server. Under **Destinations**, choose **Add a destination** (up to five):

| Kind | What you need |
|---|---|
| **Folder** | A share mounted on the server (NFS or Windows/SMB), for example `/mnt/nas/veyra`. Mount it in `/etc/fstab` so it is there after a restart; Veyra does not mount it. |
| **SFTP server** | A server reachable over SSH (a NAS with SFTP turned on, a Linux server): its **Server** name, **Port**, **User name** and **Folder on the server**. |
| **S3-compatible storage** | Amazon S3, Backblaze B2, Wasabi, Cloudflare R2, MinIO and others: the **Endpoint** (empty for Amazon S3), **Region**, **Bucket**, an optional **Folder in the bucket**, and an **Access key ID** with its **Secret access key**. |

Set up encryption first (below). Until there is a recipient, the page warns that backups leave the server unencrypted, and they include the configuration's secrets.

**SFTP:** Veyra signs in with its own SSH key, not a password. The dialog shows the public key: add it to the user's `~/.ssh/authorized_keys` on the server. Then choose **Test**. The first test shows the server's host key; compare it with what the server shows (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` as root) and choose **This is the server's key**. Veyra then refuses any other server at that address.

**S3:** create an access key that can only list, write and delete in this bucket. The secret is stored encrypted and never shown again; to change it, enter a new one when editing. Most S3-compatible storage needs **Path style** addressing, which is the default when you enter an endpoint.

How copies work:

- After each verified backup, Veyra copies every verified backup the destination is missing, newest first, and checks each copy (sizes, and for S3 a checksum of every upload). A copy is written under a temporary name and only takes its real name when it is complete.
- A copy that fails does not fail the backup. It raises the **Backup copy to a destination failed** alert, the destination shows **last copy failed** with the reason, and the next backup copies what is missing.
- Each destination keeps backups by the same rule as the server unless you turn off **Same keep policy as on this server** and give it its own, for example a longer history off-site. Old copies are removed there by that rule.
- **Test** writes, checks and removes a small file. For a **Folder** it only checks that the folder exists, because the copies are written by the backup service as root.
- **Remove** stops the copies; the copies already made stay where they are.

> **Note:** The **Copy to directory** setting of earlier releases is now a **Folder** destination named *Copy folder*.

## Take a backup now

Choose **Back up now**. A **Backup running** note shows the current step. Take one before a large change, such as importing many extensions.

## The backup list

Each row shows when it was **Taken** and how (**Scheduled**, **Manual** or **Before upgrade**, which Veyra takes before every update), its **State**, **Size**, **Contents**, whether it is **Encrypted** (**age** or **clear**), the **Copies** to each destination (*name*: **ok** or **failed**, or **local only**), and the Veyra **Version** it came from. **Delete** removes the files from the server and from every destination.

Backups are stored on the server in `/var/backups/veyra`.

## Download a backup

To keep a backup somewhere of your own, choose **Download** on a verified backup in the list, then **Prepare download**. Veyra makes a copy the web service can read, which takes a few minutes for a large backup. Choose **Download**. The window shows the file's SHA-256, so you can check it arrived whole. The prepared copy is removed from the server when the download ends, or after 6 hours if nobody downloads it. Veyra may ask you to sign in again first, and the audit log records each download.

> **Warning:** A backup that is not encrypted holds the server's secrets in the clear, including its installation key and passwords. Veyra warns you first. Turn on encryption, or keep the file somewhere as safe as the server.

The file restores with the same console command as below, once copied to the server.

## Restore a server

Restoring is done on the server console, as root, on a server with the **same Veyra release** installed. A freshly installed server is fine: see [Install Veyra](guide:install-veyra).

1. Copy the backup file (`veyra-<date>-<time>.tar.age`) and your identity file onto the server.
2. Run:

   ```
   sudo veyra backup restore /var/backups/veyra/<backup>.tar.age --identity ~/veyra-backup-identity.txt
   ```

   It asks for confirmation, because it replaces the database, configuration and data of the server.
3. When it finishes, run `sudo installer/verify.sh`.

The database, configuration and secrets, engine files, data and voicemail come back; if the backup is from an older release, the database is upgraded; the services restart. Because the server's identity, keys and certificates are in the backup, phones keep trusting it and a central console keeps recognising it.

Other console commands: `sudo veyra backup list` lists backups and `sudo veyra backup run` takes one. `--parts db,etc,engine,data,voicemail,recordings` restores only some parts.

> **Note:** A backup from a newer Veyra release is refused; install that release first. A server that is part of a high availability pair cannot be restored directly; restore a standalone server and build the pair again.

## When it does not work

- **Last run failed:** the **Schedule** card shows the error, and the **Backup failed** alert is raised (see [Health, alerts and diagnostics](guide:health-alerts-diagnostics)). Disk space is the usual cause.
- **Copy failed:** the destination shows the reason. A folder that is not mounted, an SFTP server that refuses Veyra's key (add the public key again) or whose host key changed (confirm the new one with **Test** if the server was reinstalled), or S3 credentials or a region that are wrong. Fix it and choose **Test**; the missing copies are made at the next backup.
- **No recent good backup:** the **No recent good backup** alert is raised after two days without a verified backup.

## Copy backups to Google Drive

Backups can go to a Shared drive in your Google Workspace. Personal Google accounts and My Drive do not work, because a service account has no storage of its own.

1. In the Google Cloud console, create a project and enable the **Google Drive API**.
2. Create a **service account** and download a **JSON key** for it.
3. Create a Shared drive and add the service account's email address as a **Manager**.
4. On this page, add a destination, choose **Google Drive**, and enter the Shared drive's ID and the contents of the key file.
5. Choose **Test**. It writes a file and deletes it for good.

> **Warning:** the service account must be a Manager, not a Content manager. A Content manager can only move files to the trash, where they stay for 30 days, so old backups and archived recordings would outlive their deletion. Test fails with that message if the role is wrong.

## Archive call recordings

Under **Recording archive**, choose a destination to keep a copy of every call recording there, in case this server is lost. Copies start within the hour. The first run after turning it on works through your older recordings, up to 500 an hour.

A copy lives exactly as long as its recording. When a recording is deleted, by hand or at its retention date, Veyra deletes its copy too, usually within an hour, and checks that it is gone. If it cannot, it keeps trying and raises an alert. Held recordings and their copies stay.

> **Note:** the archive does not keep recordings longer than your retention period. To keep them longer, lengthen the retention on the recording policy.

A destination that holds copies cannot be removed, because Veyra must be able to delete them. Restoring a copy is not in the interface yet.
