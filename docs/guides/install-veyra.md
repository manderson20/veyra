---
title: Install Veyra
summary: Put Veyra on an Ubuntu server, open the setup wizard and create the first administrator.
audience: admin
section: Getting started
order: 5
reviewed: 0.27.60
covers:
  - installer/install.sh
  - installer/preflight.sh
  - installer/verify.sh
  - installer/upgrade.sh
  - installer/uninstall.sh
  - installer/lib/steps.sh
  - frontend/src/app/(public)/setup/page.tsx
  - backend/veyra/api/v1/setup.py
---

Veyra runs on one Ubuntu server (or two, for [high availability](guide:high-availability)). The installer sets up everything it needs: the database, the web server, the telephony engine (Asterisk) and Veyra itself. You then finish in the browser with a short setup wizard.

The full technical reference is [the installation document](repo:docs/INSTALLATION.md). This guide is the short version.

## What you need

| | Minimum | Recommended |
|---|---|---|
| Operating system | Ubuntu Server 26.04 LTS or 24.04 LTS | 26.04 LTS, no desktop |
| Processor | 2 virtual CPUs | 4 or more |
| Memory | 2 GB | 4 to 8 GB |
| Disk | 5 GB free | 20 GB or more (voicemail, recordings and backups grow) |
| Network | A fixed address, working DNS and time (NTP) | A private address (such as 10.x or 192.168.x) |

On Proxmox, use VirtIO network and disk, turn on the QEMU guest agent and use a bridged network.

> **Note:** On Ubuntu 24.04 the packaged Node.js is too old to build the web interface. The installer stops with a clear message if it would need it. Use 26.04, or see the installation document for the workaround.

## 1. Get Veyra onto the server

Sign in to the server with an account that can use `sudo`, then:

```
git clone https://github.com/manderson20/veyra.git
cd veyra
```

## 2. Check the server

```
sudo installer/preflight.sh
```

This only looks; it changes nothing. It reports blocking problems (fix them first) and warnings (read them). A common warning is that Ubuntu's installer left part of the disk unused; the installation document shows the one command that adds it.

## 3. Run the installer

```
sudo installer/install.sh
```

It asks before it starts. Add `--dry-run` to see every step without doing anything. It takes several minutes, and at the end it checks the result and prints:

- the address of the setup wizard, such as `https://192.168.1.20/setup/`
- a **one-time setup token**

The installer is safe to run again. If it stops half-way, fix what it reports and run it again; it carries on where it stopped and never replaces passwords, keys, certificates or data that already exist.

Things the installer never does: change SSH settings, change firewall rules, remove packages, or listen on a public internet address (unless you add `--allow-public-admin`).

## 4. Finish in the browser

1. Open the setup address. Your browser warns about the certificate the first time; that is expected (see *Certificates* below).
2. **Verify access:** paste the **Setup token**. Lost it? On the server run `sudo veyra setup-token` for a new one. A token works once and for 24 hours.
3. **Administrator account:** your **Full name**, **Email address** and a **Password** of at least 12 characters. This first account is the *recovery administrator*: it always signs in with a password, even after you set up single sign-on.
4. **Organization:** the **Organization name** (your school, district or company) and a **Short name**.
5. **Installation:** an **Installation name** (for example *District Phone System*) and the **Time zone**.
6. **Numbering plan:** the **Extension length** and the **First extension** and **Last extension**. You can widen it later.
7. **Review**, then **Finish setup**. You are signed in.

The wizard also lists, on the left, what is set up after it, each with where to find it (*After setup: System → Backups*, for example): SIP and media addresses, outside lines, email delivery, backups, updates and high availability. Once you are signed in, **Help** in the top bar has a guide for each, starting with [First steps after installing Veyra](guide:first-steps).

## Certificates

Veyra makes its own certificate authority, so phones it sets up trust it automatically. Browsers do not, so they warn until you either:

- install the Veyra CA certificate on the computers (download it from `https://<server>/downloads/veyra-ca.crt`), or
- get a public certificate from Let's Encrypt for the server's name. See [Get a public HTTPS certificate](guide:https-certificate). Nothing then needs installing on computers.

## Next steps

- Turn on [backups](guide:backups) encryption and a copy to another machine.
- Choose how [updates](guide:updates) are installed.
- Set up email delivery under **System → Settings**, so alerts, voicemail and update notices can be sent.
- Consider the [firewall](guide:firewall).

## Useful console commands

| Command | What it does |
|---|---|
| `sudo installer/verify.sh` | Checks services, HTTPS, the database and that nothing internal is exposed |
| `sudo veyra status` | A short health summary |
| `sudo veyra setup-token` | A new setup token (before setup is finished) |
| `sudo veyra users reset-password <email> --unlock` | A one-time password reset link when no administrator can sign in |
| `sudo installer/uninstall.sh` | Removes Veyra but keeps the database, configuration, data and backups |

## When it does not work

- **"public IP address" warning in preflight:** Veyra will not show its admin interface on a public address. Give the server a private address, put it behind a firewall or VPN, or use `--listen <address>`.
- **The web page does not open:** run `sudo installer/verify.sh` and `sudo veyra status`. Another program holding port 80 or 443 is a common cause.
- **The installer stopped:** read the last lines it printed (the full log is in `/var/log/veyra/`), fix the problem, and run `sudo installer/install.sh` again.
