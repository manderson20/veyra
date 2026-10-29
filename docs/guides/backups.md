---
title: Backups and restore
summary: Schedule verified, encrypted backups, copy them off the server, and restore a server from one.
audience: admin
section: Maintenance
order: 20
reviewed: 0.27.44
pages:
  - /system/backups/
covers:
  - frontend/src/app/(app)/system/backups/*
  - backend/veyra/api/v1/backups.py
  - backend/veyra/backups/*.py
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
- **Copy to directory:** a folder on a mounted network share (NFS or CIFS) that receives a copy of every backup, for example `/mnt/nas/veyra`. The share must be mounted on the server; Veyra does not mount it. Set up encryption first, so the copy is unreadable without your key.
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

## Take a backup now

Choose **Back up now**. A **Backup running** note shows the current step. Take one before a large change, such as importing many extensions.

## The backup list

Each row shows when it was **Taken** and how (**Scheduled**, **Manual** or **Before upgrade**, which Veyra takes before every update), its **State**, **Size**, **Contents**, whether it is **Encrypted** (**age** or **clear**), whether the **Copies** to the share worked (**copied**, **copy failed** or **local only**), and the Veyra **Version** it came from. **Delete** removes the files from the server and from the copy directory.

Backups are stored on the server in `/var/backups/veyra`.

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
- **copy failed:** the share is not mounted or not writable. Check it on the server; the copy is retried at the next backup.
- **No recent good backup:** the **No recent good backup** alert is raised after two days without a verified backup.
