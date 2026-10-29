---
title: Firewall and bans
summary: Ban attackers automatically, keep your own phones and networks on the allow list so they are never locked out, and recover from the console.
audience: admin
section: Sign-in and security
order: 30
reviewed: 0.27.45
pages:
  - /system/firewall/
covers:
  - frontend/src/app/(app)/system/firewall/*
  - backend/veyra/api/v1/firewall.py
  - backend/veyra/firewall/*.py
---

A phone system that can be reached from the internet is attacked within hours: robots try extension numbers and passwords to make expensive calls. Veyra's firewall watches for that and bans the addresses that misbehave.

The firewall is **off** after installation. Open [System → Firewall](app:/system/firewall/).

Anyone who may view the firewall sees its bans, events, lists and settings. Only people who may also change it (the permission *Change firewall rules, bans and settings*) see **Allow**, **Block**, **Lift**, **Block permanently**, **Add feed**, the feed and list buttons, and **Save settings**. Without it, the **Settings** tab says *You can view these settings; changing them needs the firewall write permission.*

## How it works

- Every suspicious event (a wrong SIP password, an unknown extension, a failed sign-in) scores points against the address it came from.
- An address that reaches the **Score that bans** within the **Window** is **banned** for a while. A repeat offender gets a longer ban each time, up to the **Longest ban**.
- Addresses on the **allow list** are never banned or blocked, whatever they do.
- Addresses on the **block list** are always dropped, unless they are also allowed.

## 1. Fill the allow list first

Your phones, trunks and administrators must never be locked out. Before turning the firewall on, open the **Allow and block** tab.

Some entries are added and kept up to date by Veyra itself, marked by their **Source**:

- **This server**,
- **Local network**: the networks listed under **Local networks** in the SIP settings ([System → Telephony Engine](app:/system/telephony/)),
- **Trunk**: the addresses of your phone providers.

Add the rest with **Allow**:

1. Enter the **Address or network**, such as `203.0.113.7` or `10.20.0.0/16`.
2. Add a **Comment** (why, for whom).
3. Choose when it **Expires** (**Never**, or 1 hour to 30 days).

Add every network your phones live on (voice VLANs, other buildings, the VPN), your offices and administrators' networks, and remote workers with fixed addresses.

> **Important:** If a whole building's phones sit behind one router, one misconfigured phone there can get that address banned, and every phone behind it with it. Put such addresses on the allow list.

## 2. Turn it on

On the **Settings** tab, switch **Firewall on**, then **Save settings** and confirm **Turn on**. If the address you are using is not on the allow list, the page warns *Your address is not on the allow list*.

## Limit who can reach each service

Under **Who may reach each service**, each of **SIP signaling**, **Call audio (RTP)**, **Web interface and provisioning** and **SSH** can be open to **Anyone not banned or blocked** or to **Only the allow list**. Set the **SSH ports** if SSH is not on port 22.

Limiting a service is safe to try: after saving, the page shows **Keep the new restrictions?** with a countdown. Choose **Keep these settings** within 60 seconds. If you have locked yourself out, you cannot press it, and the change is undone by itself.

## Automatic bans

Under **Automatic bans**: **Score that bans** (default 10), **Window (minutes)** (default 10), **First ban (minutes)** (default 60) and **Longest ban (days)** (default 7). **Points per event** sets how much each kind of event counts, such as **Wrong SIP password**, **Unknown SIP account** or **Failed sign-in**. Set a kind to 0 to ignore it.

## See what happens

- **Overview:** whether the firewall is on, **Active bans**, **Suspicious events (24 h)**, **Bans (24 h)**, and the **Most active addresses (24 h)**. Click an address to see its events.
- **Bans:** active, past or all bans, with the reason and until when. **Lift** ends a ban now. **Block permanently** moves the address to the block list.
- **Events:** every suspicious event, filtered by address or source (**Phone system**, **Sign-in**, **Provisioning**, **Web server**). Tick **Only allowed addresses that would have been banned** to find allowed addresses that misbehave, such as a phone with an old password.

## Block an address or network

On **Allow and block**, choose **Block**. Enter the **Address or network**, a **Comment**, and optionally tick **Services** to block only some (none ticked blocks everything), and when it **Expires**.

## Blocklist feeds (optional)

Under **Settings → Blocklist feeds**, **Add feed** to drop addresses that others have already seen attacking:

- **Address list (one per line, HTTPS):** a public list, such as Spamhaus DROP.
- **CrowdSec local API (bouncer):** if you run CrowdSec, its address and a **Bouncer key** (create one with `sudo cscli bouncers add veyra`).

Feeds are refreshed every 10 minutes. The allow list still wins.

## Phone bootstrap networks

A brand-new phone fetches the Veyra certificate over plain HTTP before it can use HTTPS. **Phone bootstrap networks** limits that to the networks you list, such as your staging or voice VLAN. Empty means the **Local networks** of the SIP settings.

## Locked out? Recover from the console

On the server's console (or over SSH, if SSH still works), run:

```
sudo veyra firewall off
```

It turns the firewall off and removes its rules at once. Fix the allow list, then turn it on again. `sudo veyra firewall status` shows the settings and the active bans.

## When it does not work

- **The firewall service is not running:** rules already applied stay, but nothing new is banned. Check `journalctl -u veyra-firewall` on the server.
- **Some event sources cannot be read:** Veyra cannot read the engine's security log or the web server's log, so it cannot see those attacks.
- **The Many firewall bans alert:** see [Health, alerts and diagnostics](guide:health-alerts-diagnostics).
