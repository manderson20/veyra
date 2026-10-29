---
title: High availability
summary: Run Veyra on two servers so a standby can take over when the primary needs maintenance or fails.
audience: admin
section: Maintenance
order: 60
reviewed: 0.27.44
pages:
  - /system/ha/
covers:
  - frontend/src/app/(app)/system/ha/*
  - frontend/src/components/ha/HaDialogs.tsx
  - backend/veyra/api/v1/ha.py
---

With high availability, two Veyra servers work as one phone system. The **primary** handles calls. The **standby** keeps a live copy of the database and the files (prompts, voicemail, firmware) and can take over:

- by a planned **switchover**, while both servers are up (for maintenance or updates), in about a minute;
- by a **failover**, from the standby, when the primary is lost.

Phones and browsers use one **service name** and **service address**, which moves to whichever server is primary.

> **Important:** Veyra never fails over by itself. With only two servers, a server cannot tell a dead partner from a broken network cable, and two primaries at once would both take calls and change the database. A person decides. At most one server ever runs the telephony engine, holds the service address and writes the database.

Open [System → High Availability](app:/system/ha/). You need to be a platform administrator.

## What you need

- A second server with the same Ubuntu release.
- Both servers on the same network segment (the same VLAN).
- A **service name** (such as `veyra.example.org`) and a free **service address** on that segment. The name must point at the address in your DNS.
- The name of the network interface that will carry the address (such as `ens18`).

## 1. Enable high availability on the first server

On a standalone server the page shows **Standalone** and whether the **HA agent** is running.

1. Choose **Enable high availability**.
2. Fill in the **Service name**, **Service address**, **Prefix length** (24 for a typical /24 network) and **Interface**.
3. Leave **Synchronous replication** off unless you have a reason (see *Options* below).
4. Choose **Enable**.

The database is reconfigured and restarted once (calls are not affected; the web page reconnects). The HTTPS certificate is reissued for the service name and both server names. Afterwards use the service name to reach Veyra.

## 2. Add the standby

1. Choose **Add node**. Veyra shows a command with a one-time **join token**. Copy it now: it is shown once and expires in 24 hours. Note the **Fingerprint**.
2. On the second server, get the same Veyra release (see [Install Veyra](guide:install-veyra)) and run the command, from the Veyra folder. It looks like:

   ```
   sudo installer/install.sh --role secondary --join https://<primary> --token <token>
   ```

3. The installer copies the credentials and certificates, copies the database and starts replication. Asterisk is installed but stays stopped on the standby.

The page now shows both servers. Each card shows its **Role**, **State**, **Version**, **Database** replication, **Replication lag**, **Last heartbeat**, **File sync** and whether it holds the **Service address**.

## Switch over (planned)

Use this before maintenance on the primary, or to update a pair (see [Updates and maintenance windows](guide:updates)).

1. On the primary, choose **Switch over to <standby>** on the standby's card.
2. Veyra checks the preconditions: both servers online and on the same version, replication streaming with little lag, file sync fresh, nothing else in progress. If something is wrong it says what, under **Not possible now**.
3. Type the standby's name and choose **Switch over**.

> **Warning:** Calls in progress end. Asterisk stops on the old primary and starts on the new one. Phones re-register within their registration time; trunks re-register at once. It takes about a minute.

The progress shows step by step. The old primary becomes the standby.

## Fail over (the primary is down)

Do this only when the primary is really down.

1. Open the **standby's own address** in the browser (its web page is read-only, but it offers failover).
2. Choose **Fail over to this node**. The window shows the primary's last heartbeat and what may be lost: changes after the last replicated moment and files changed since the last sync.
3. Unless fencing is set up, tick **I confirm <primary> is powered off or disconnected**. This is recorded in the audit log.
4. Type `FAIL OVER` and choose **Fail over**.

When the old primary comes back, it must not act as primary. Choose **Rejoin** on its card to make it the new standby.

## Fencing (Proxmox)

If both servers are Proxmox virtual machines, **Fencing → Configure** lets Veyra switch off the old primary's VM before a failover, so you do not have to confirm it by hand. Enter the **Proxmox API** address, an **API token id** and **API token secret** (the token needs `VM.PowerMgmt` on both VMs), the **Proxmox node**, the **VM id** of each server, and the certificate settings. If stopping the VM fails, the failover stops.

## An isolated primary

If the primary loses contact with the standby, it stops serving calls (the standby may have taken over) and the page says **This primary is isolated**. If the standby really is down, choose **Resume as primary** and type `RESUME`. If the standby is up, fix the network; the primary rejoins by itself.

## Options

On the primary:

- **Replication:** **Asynchronous (recommended)**: the primary never waits for the standby, but a failover may lose the last moments of changes. **Synchronous**: every change waits for the standby, and changes stop entirely while the standby is down; switching back to asynchronous is the way out.
- **Include call recordings in the file sync:** recordings are large; without them, recordings made on the old primary are unavailable after a failover until it is back.

## Remove the standby

**Remove** on the standby's card (type its name) takes it out of the pair. That server then refuses to run the telephony engine until `sudo veyra ha standalone` is run on it. With one server left, the installation is standalone again.

## Events and alerts

**Events** lists switchovers, failovers and role changes. The alerts **HA node offline**, **Replication broken**, **Replication lagging**, **File sync failing**, **Primary isolated** and **HA operation failed** watch the pair (see [Health, alerts and diagnostics](guide:health-alerts-diagnostics)).

On the console, `sudo veyra ha status` shows the server's state.
