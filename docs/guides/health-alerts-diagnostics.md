---
title: Health, alerts and diagnostics
summary: See whether everything is running, get emailed when something breaks, and capture SIP traffic or read engine logs to find out why.
audience: admin
section: Maintenance
order: 50
reviewed: 0.27.44
pages:
  - /system/health/
  - /system/alerts/
  - /system/diagnostics/
covers:
  - frontend/src/app/(app)/system/health/*
  - frontend/src/app/(app)/system/alerts/*
  - frontend/src/app/(app)/system/diagnostics/*
  - backend/veyra/api/v1/system.py
  - backend/veyra/api/v1/alerts.py
  - backend/veyra/api/v1/diagnostics.py
  - backend/veyra/reporting/alerts.py
  - backend/veyra/diagnostics/captures.py
---

Three pages under **System** help when something is wrong:

- **Health:** is everything running right now?
- **Alerts:** problems Veyra noticed, and who gets emailed about them.
- **Diagnostics:** packet captures, engine logs and engine queries, to find the cause.

## System health

[System → Health](app:/system/health/) refreshes every 15 seconds.

- **Overall:** one status for the whole system, and the Veyra version.
- **Database (PostgreSQL)**, **Telephony engine** and **Modules:** each with its status and details.
- **CPU**, **Memory**, **Disk** and **Uptime** of the server.
- **Modules:** each installed module with its **State** and **Health**.

From the server console, `sudo veyra status` prints the same summary.

## Alerts

[System → Alerts](app:/system/alerts/) lists problems Veyra watches for. The list shows **Raised now** by default; switch to **Cleared** or **All** to see history. Each alert shows what is wrong, since when, when it cleared, and whether its email could be sent.

### The rules

| Rule | Raised when |
|---|---|
| **Telephony engine down** | Asterisk does not answer |
| **Trunk down** | A trunk to your phone provider is not registered or not reachable |
| **Veyra service not running** | One of Veyra's background services stopped |
| **Disk space low** | Free space falls below the limit (10 % by default) |
| **HTTPS certificate expiring** | The web certificate expires within the limit (21 days by default) |
| **Public certificate not renewed** | A Let's Encrypt renewal failed |
| **Many firewall bans** | More bans per hour than the limit (20 by default): probably an attack |
| **Phones unregistered** | More than the limit (20 % by default) of phones are not registered |
| **Backup failed**, **No recent good backup** | See [Backups and restore](guide:backups) |
| **Instance not checking in**, **Instance unhealthy**, **Instance update failed** | On a central console only |
| **HA node offline**, **Replication broken**, **Replication lagging**, **File sync failing**, **Primary isolated**, **HA operation failed** | On a high availability pair only |

### Who gets told

By default, alerts show only on this page. To email people, click a rule under **Rules** and set:

- **Enabled.**
- **Raise after (minutes):** how long the problem must last before anyone is told, so short blips are ignored.
- **Limit**, for rules that have one (percent free, days, bans per hour).
- **Email to:** one address per line. People are emailed when the alert is raised, every 24 hours while it lasts, and when it clears.

Email must be set up under **System → Settings → Email delivery**.

## Diagnostics

[System → Diagnostics](app:/system/diagnostics/) has three tabs. Everything here can contain phone numbers, names and, for audio, the content of calls. Downloads, log reads and queries are recorded in the audit log.

### Packet captures

A packet capture records the SIP messages between phones, trunks and Veyra, so you can see why a phone does not register or a call fails.

1. Under **Start a capture**, choose what to **Capture**:
   - **All SIP:** everything on the SIP ports.
   - **An extension (where its phone registers from):** traffic of that phone. If the phone is not registered, use an address instead.
   - **A trunk:** traffic to and from your phone provider.
   - **An address or network:** such as `192.168.1.20` or `10.0.0.0/8`.
2. Set **Duration (minutes)** (up to 30) and **Size limit (MB)** (up to 500). The capture stops at whichever comes first.
3. Tick **Include RTP (media)** only for audio problems: it records the audio of calls.
4. Choose **Start**. Wait until the row shows **Running** (a few seconds), then reproduce the problem: make the call, restart the phone.
5. Choose **Stop**, or let it finish.

Two captures can run at a time.

On a finished capture:

- **SIP** shows a readable summary: one row per call or registration (*dialog*), with who talked to whom and the last answer (such as `200 OK`, `401 Unauthorized`, `404 Not Found`). Click a row to see its messages. For TLS connections the content is encrypted and cannot be read.
- **Download** saves a `.pcap` file that opens in Wireshark. The first time, Veyra reminds you that it is personal data.
- **Delete** removes it from the server. Delete captures when you are done.

From the console: `sudo veyra capture start --host 192.168.1.20`, then `list`, `stop` and `delete`.

### Logs

Shows the last lines of the engine's logs: **Engine messages (notice, warning, error)**, **Security events (failed registrations, blocked requests)** and **Queue events**. Choose the **Log**, the number of **Lines** (up to 2,000), optionally text it must be **Containing** (such as an extension number), and **Show**.

### Engine queries

A fixed list of read-only questions to Asterisk, such as **Every endpoint with its state**, **Registered contacts**, **Trunk registrations**, **Channels and calls up now** and **Do Not Disturb, forwards and follow-me as the engine has them**. **One endpoint in full** takes an extension number as its **Argument**. Choose **Run**.

## Common problems

- **A phone does not register:** run **Registered contacts**, then capture the phone's address. A `401` answer again and again means a wrong password; nothing at all means the phone cannot reach the server (check the network and the firewall's bans; see [Firewall and bans](guide:firewall)).
- **Calls have no audio or one-way audio:** capture with **Include RTP (media)**, and check the **External media address** and **Local networks** in the SIP settings (see [Deploy changes to the phone system](guide:deploy-changes)).
- **A trunk is down:** run **Trunk registrations** and capture the trunk.
