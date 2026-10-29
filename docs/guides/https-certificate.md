---
title: Get a public HTTPS certificate (Let's Encrypt)
summary: Get a free certificate that every browser trusts, so nobody has to install the Veyra certificate and passkeys and the Companion work.
audience: admin
section: Sign-in and security
order: 40
reviewed: 0.27.44
covers:
  - frontend/src/components/account/PublicCertificateCard.tsx
  - backend/veyra/api/v1/certificate.py
  - backend/veyra/system/certificate.py
  - installer/bin/veyra-acme
---

Out of the box, Veyra uses a certificate from its own certificate authority (the *Veyra CA*). Phones Veyra sets up trust it, but browsers warn until the Veyra CA certificate is installed on each computer.

A **public certificate** from Let's Encrypt (free) or another authority fixes that: every browser trusts it with nothing installed. Passkeys and the [Companion extension](guide:companion-rollout) need one, or the Veyra CA on every computer.

Phones are not affected: they keep using the Veyra certificate, which also keeps answering the server's IP addresses and every other name.

You need to be a platform administrator. Open [System → Settings](app:/settings/) and find the **HTTPS certificate** card. Its badge says **Veyra CA only** or **Public, n days left**.

## Before you start

- A **host name** people will use, such as `pbx.example.org`, in a domain you control. Not an IP address.
- A way to prove you own it. Choose one:
  - **DNS record:** Veyra adds a temporary record in your DNS. Works even when the server cannot be reached from the internet, which is usual for a phone system. You need an API key for your DNS provider.
  - **Web request on port 80:** the authority connects to the name on port 80. The name must point (in public DNS) at an address whose port 80 is forwarded to this server.

## 1. Fill in the settings

- **Host names:** the names users type in the browser, separated by commas. A wildcard (`*.example.org`) needs the DNS check.
- **Email for expiry notices:** the authority writes here if renewal keeps failing.
- **How the authority checks you own the name:** **DNS record** or **Web request on port 80**.
- For DNS, the **DNS provider** that hosts the name: **Cloudflare**, **Amazon Route 53**, **Google Cloud DNS**, **DigitalOcean**, **Linode (Akamai)**, **DNSimple**, **OVH**, or **Your own DNS server (RFC 2136: BIND, Windows DNS with TSIG)**. Then the provider's credentials, and **Wait for the DNS record (seconds)**. Give the key the narrowest rights the provider offers (edit DNS of this zone only). It is stored encrypted and never shown again.
- **Certificate authority:** **Let's Encrypt**, **Let's Encrypt staging (test the setup; browsers do not trust it)**, or **Another ACME authority** (with its **ACME directory address**, and the **External account key ID** and **External account HMAC key** if it asks for them, as ZeroSSL and Sectigo do).

Choose **Save settings**. If something is missing, the card says what.

> **Tip:** Try **Let's Encrypt staging** first. It has generous limits, so mistakes cost nothing. When it works, switch to **Let's Encrypt**, save, and get the real certificate.

## 2. Get the certificate

Choose **Get the certificate…**, check the names, and choose **Get it now**. It takes up to a few minutes; **Show output** shows the progress. When it is done, the card shows the certificate **In use**, who issued it and until when. Calls are not affected.

If the firewall limits the web interface to the allow list, Veyra opens port 80 to everyone for ten minutes while the authority checks.

## Renewal

Veyra checks every day and renews the certificate when 30 days or fewer are left. **Renew now** does the same check at once (it renews only within those 30 days). **Get a new certificate…** gets a fresh one regardless, for example after changing the names.

If a renewal fails, the **Public certificate not renewed** alert is raised (see [Health, alerts and diagnostics](guide:health-alerts-diagnostics)).

## Go back to the Veyra certificate

**Stop using it…** gives every name the Veyra certificate again. Browsers without the Veyra CA installed will warn again, and passkeys stop working until they trust it. The stored DNS credentials are deleted.

## From the server console

- `sudo veyra certificate status` shows the certificate in use and the last run.
- `sudo veyra certificate renew` renews now if 30 days or fewer are left.
- `sudo veyra certificate remove` goes back to the Veyra certificate.

Getting the first certificate needs the web page, where the settings are entered.

## When it does not work

Open **Show output** and read the last lines.

- **DNS check fails:** the API key lacks rights to the zone, or the record had not spread yet. Raise **Wait for the DNS record (seconds)**.
- **Port 80 check fails:** the name does not point to your public address, or port 80 is not forwarded to this server.
- **Too many requests:** Let's Encrypt limits how often you can ask. Wait, and use staging while testing.
