---
title: Analog adapters and fax machines
summary: Connect analog phones, door phones and fax machines through a Grandstream HT80x or HT81x adapter.
audience: admin
section: Phones and devices
order: 50
reviewed: 0.27.44
covers:
  - provisioning/templates/official/grandstream-ata/*
  - provisioning/templates/official/grandstream-ht80x/*
  - provisioning/templates/official/grandstream-ht81x/*
---

An **analog telephone adapter** (ATA) lets an ordinary analog phone or a fax machine use Veyra. Veyra configures Grandstream adapters:

- **HT801** (one phone port) and **HT802** (two), also the V2 versions;
- **HT812** (two ports), **HT814** (four) and **HT818** (eight), also the V2 versions.

These templates are experimental: test one adapter before rolling out more (see [Supported phones and adapters](guide:supported-phones)).

## Set up an adapter

1. Create one extension for each port you will use (under Telephony → Extensions).
2. Create a [phone template](guide:device-profiles) with the base file **Grandstream HT801 / HT802** or **Grandstream HT812 / HT814 / HT818**, or the family **Grandstream ATA (common settings)**.
3. Register the adapter under [Provisioning → Extension Mapping](app:/devices/) with its MAC address and model (see [Add a phone](guide:add-a-phone)).
4. On the device's **Settings** tab, set **Extension (line 1)** to port 1's extension. Add the other ports with **Add line** under **Extra lines**: line 2 is port 2, line 3 is port 3, and so on.
5. Point the adapter at Veyra: in its web page, Maintenance → Upgrade and Provisioning, choose HTTPS, the server `<your Veyra server>/provisioning`, and the organization's enrollment user name and password. Or use DHCP option 66. See [Connect phones to Veyra](guide:connect-phones-to-veyra).

After it restarts, each port with an extension registers. Ports without an extension are turned off. Lines beyond the adapter's ports (line 3 on an HT802, for example) are ignored.

## What the adapter does for you

- **Star codes go to Veyra.** The adapter's own star codes are turned off, so `*97` (voicemail), `*72`, `*78` and the other Veyra codes work from the analog phone. To use the adapter's own codes instead, turn on the setting `local_call_features` in the profile.
- **Voicemail waiting:** a stutter dial tone, and the light on phones that have one.
- **Hotline:** a phone that dials one number as soon as it is picked up, for example a lobby or elevator phone. Set **Hotline number** (and, for a short pause first, **Warm-line delay (seconds)**) on the port's extension.

## Fax machines

Plug the fax machine straight into a port of the adapter, with no splitter. Faxes can travel two ways:

- **As audio (G.711 pass-through).** Works with any carrier. This is the default for every port.
- **As T.38.** A fax protocol that copes much better with a poor network. It needs a carrier that supports T.38.

To use T.38 for a fax machine:

1. Open the port's extension and turn on **Fax machine (T.38)**. Deploy the change as the page asks.
2. Turn on T.38 for the carrier on its SIP trunk (**Fax over T.38**).
3. Use **Reprovision** on the adapter's device page. With the profile setting `fax_mode` on `auto` (the default), the adapter switches that port to T.38 by itself.

`fax_mode` can also force every port to `passthrough` (audio) or `t38`.

> **Tip:** Keep error correction (ECM) on in the fax machine, and look at its result report after a test fax. A fax that fails as audio usually means packet loss or jitter on the network; T.38 end to end is the fix where the carrier supports it.

## Other adapter settings

These are in the template under **Settings**:

| Setting | What it does |
|---|---|
| `admin_password` | The password of the adapter's web page. Blank keeps the one on the sticker. |
| `polling_hour` | The hour (0–23) the adapter checks Veyra for changes each day. |
| `install_ca` | Installs the Veyra certificate on the adapter (on by default). |
| `validate_server_certificate` | Makes the adapter refuse a server it does not trust. Turn it on once the certificate is installed. |
| `dhcp_override` | Lets DHCP options 43, 66 or 160 replace the server set by Veyra. Off keeps the adapter on Veyra over HTTPS. |

## If something doesn't work

- **The adapter does not get its configuration.** See *If something doesn't work* in [Connect phones to Veyra](guide:connect-phones-to-veyra). Grandstream adapters do not use the plain-HTTP bootstrap, so point them at the **https** address.
- **A port gives no dial tone.** Check that the port's line has an extension on the device's **Settings** tab, and that the extension is enabled.
- **Faxes fail.** Try the port as audio first (turn **Fax machine (T.38)** off). If audio works and T.38 does not, the carrier may not support T.38.
