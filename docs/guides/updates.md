---
title: Updates and maintenance windows
summary: Install new Veyra releases and operating system updates, now or in a maintenance window, from the web page or the server console.
audience: admin
section: Maintenance
order: 10
reviewed: 0.27.44
pages:
  - /updates/
covers:
  - frontend/src/app/(app)/updates/*
  - backend/veyra/api/v1/updates.py
  - backend/veyra/updates/*.py
  - installer/bin/veyra-os-packages
---

Open [System → Updates](app:/updates/). The page has three tabs: **Updates** (what is available and what was installed), **Settings** (how each part of the system is updated) and **System packages** (Ubuntu's own updates).

Veyra releases are signed. Veyra downloads them only from the official Veyra feed, checks the signature, size and checksum, and refuses anything else.

## What an update does to calls

- **A Veyra update** restarts the web interface and the API, usually for under a minute. **Calls are not affected.** The database and configuration are backed up first, and if the database step fails the previous version is put back.
- **Operating system packages** do not affect calls, except **Asterisk** (the telephony engine): upgrading it restarts it, which drops calls in progress. That is why Veyra holds Asterisk back unless you include it.

## Install a Veyra release now

1. On the **Updates** tab, choose **Check now** (top right) if you do not want to wait for the next automatic check.
2. In **Available updates**, choose **Review and install** on the release. The window shows the release notes, the **Service impact**, and a list of **Checks**: the release is newer, it can be installed from your version, your modules support it, there is enough disk space (2 GB plus the release), and no other installation is running. A failed check shows **Blocked**.
3. Choose **Download and install now**. (Or **Download and verify only** to fetch it now and install later.)

The window then follows the installation live: **Approved**, **Pre-checks passed, upgrade service started**, **Release verified and unpacked**, **Installer running** (with the installer's output) and **Finished**. The first stage can take up to a minute, because a background worker starts the upgrade on its next pass. While Veyra restarts, the page says *Veyra is restarting; this page reconnects by itself*. When it is done, choose **Reload the page**.

You can close the window at any time; the same progress shows at the top of the page.

## Install in the maintenance window instead

Once a release is **Downloaded**, its review window offers **Install in maintenance window** (if the Veyra policy has a window) beside **Install now**. The release then shows **Approved · maintenance window** and installs in the next window, only when no call is in progress. **Withdraw approval** cancels it.

## Install from the server console

If the web interface is not available, or you prefer the console, run on the server:

```
sudo veyra updates install
```

It checks the feed, downloads and verifies the newest release, approves it and starts the installation, exactly as the web page does, and prints each step until it finishes. The web page shows the same progress and history. Useful options:

- `sudo veyra updates install 0.27.44` installs that offered version instead of the newest.
- `--no-wait` returns as soon as the installation has started.
- `sudo veyra updates check` only checks; it never installs.

The approval is recorded in the audit log as done by `cli (<your user name>)`.

## Choose how updates happen

On the **Settings** tab:

**Notifications:** **Email notifications to** lists the addresses told when a release is available, downloaded, installed or failed. Email must be set up under **System → Settings → Email delivery**.

**Update policies:** one card per part of the system: **Veyra application**, **Modules**, **Provisioning templates**, **Telephony engine (Asterisk)** and **Operating system**. Each card has:

- **Update behaviour:**
  - **Manual only:** nothing happens by itself; an administrator checks and installs.
  - **Notify:** checks on a schedule and emails; nothing is downloaded or installed.
  - **Download, install on approval:** downloads new releases; an administrator approves them (Veyra application only).
  - **Install automatically in a maintenance window:** installs the chosen kinds of update in the window, when no call is in progress. Other releases wait for approval.
- **Release channel:** **Stable** for production. **Beta** and **Development** are pre-release software.
- **Check for updates automatically** and **Check every (hours)**.
- **Notify administrators.**
- **Maintenance window** (Veyra, Asterisk and the operating system): turn on **Use a maintenance window**, tick the days, set **Starts at**, **Length (minutes)** (30 to 720) and the **Time zone**.
- In automatic mode, what installs by itself: **Security**, **Bug fixes** and **Features** for Veyra; **Every update except Asterisk** or **Security updates only** for the operating system; and for Asterisk, **Install Asterisk updates in the window when no call is in progress**.

Choose **Save policy** on each card you change.

> **Tip:** A common choice for a school or office: Veyra on **Install automatically in a maintenance window** with **Security** and **Bug fixes** ticked, on Saturday at 02:00; the operating system on **Security updates only** in a Sunday window; Asterisk on **Notify**.

## Operating system packages

The **System packages** tab lists the Ubuntu packages that can be upgraded, checked daily. Packages marked **security** fix security problems; **restarts Asterisk** means the package belongs to the telephony engine.

- **Check now** refreshes the list.
- **Install security (n)** installs only security updates. Asterisk is upgraded only if it has a security update itself.
- **Install all except Asterisk (n)** installs everything else. Calls are not affected.
- **Include Asterisk** installs everything. Calls in progress drop and phones re-register. If calls are in progress, Veyra asks again and offers **Drop the calls and install**.

Progress and output show on the card. A Veyra backup is taken before each run. If the server needs a restart afterwards (for example a new Linux kernel), the card says so. Veyra never restarts the server by itself; do it at a quiet time, because calls drop while it is down.

## High availability pairs

On a pair, update the standby first. The page shows **Update the standby first** with the order: install on the standby (**Install … on the standby**), switch over to it, install on the old primary, and optionally switch back. See [High availability](guide:high-availability).

## Managed by a central console

If this server is enrolled in a central console that sets the update policy, the page shows **Managed by the central console**, and changes made here are replaced at its next check-in. See [Central management of several servers](guide:central-management).

## When it does not work

- **Last check** shows **No update source** or **Failed:** read **Details**. The server must reach the internet over HTTPS.
- **A check says Blocked:** the reason is on the line. Low disk space is the most common: free some space on `/`.
- **The installation failed:** the progress shows the error and the installer's output, and the path of the full log on the server. The previous version keeps running.
- **History:** the **Update history** card lists every installation with its result and who started it.
