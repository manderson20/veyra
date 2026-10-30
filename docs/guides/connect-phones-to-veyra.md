---
title: Connect phones to Veyra
summary: How a new phone finds this server, signs in for its configuration, and learns to trust Veyra's certificate.
audience: admin
section: Phones and devices
order: 10
reviewed: 0.27.54
checked: 2026-10-29
pages:
  - /devices/
  - /provisioning/requests/
covers:
  - backend/veyra/provisioning/serve.py
  - backend/veyra/provisioning/bootstrap.py
  - backend/veyra/api/v1/enrollment.py
  - frontend/src/components/organizations/ProvisioningCredentialCard.tsx
  - frontend/src/app/(app)/provisioning/page.tsx
  - frontend/src/app/(app)/provisioning/requests/*
---

Every phone, adapter and speaker that Veyra manages downloads its configuration from Veyra. Nobody types settings into the phone. You do three things once, and after that each new phone sets itself up when it is plugged in:

1. Tell the phones where Veyra is (the **provisioning URL**).
2. Give new phones a password to sign in with the first time (the **enrollment credential**).
3. Make the phones trust Veyra's HTTPS certificate.

Then you register each phone by its MAC address. See [Add a phone](guide:add-a-phone).

## The provisioning URL

Phones download their files from `https://<your Veyra server>/provisioning/`. You can copy this address in two places:

- [Provisioning → Templates](app:/provisioning/), in the **Redirect services** card (**Provisioning URL**).
- On the organization's page under Directory → Organizations, in the **Phone provisioning** card (**Server URL**).

## The enrollment credential

A new phone signs in with its organization's **enrollment credential** the first time. Veyra then gives each phone its own user name and password in its configuration, so from then on every phone signs in on its own. The device page shows that user name on the **Status** tab as **Credential user** (it looks like `dev-0004f2abcdef`).

To create the credential:

1. Open [Directory → Organizations](app:/organizations/) and open the organization.
2. In the **Phone provisioning** card, choose **Create credential** and confirm.
3. Copy the **Password** right away. It is shown only once.

The user name is `veyra-` followed by the organization's short name.

**Rotate credential** makes a new password. Phones that already have their configuration keep working, because they use their own password. Only phones that have not finished their first download need the new one.

## How the phone finds Veyra

Pick one of these. You only need it for new or factory-reset phones, because a configured phone remembers the address.

- **DHCP option 66.** On the DHCP scope of the voice network, set option 66 to the provisioning URL. Poly phones also read option 160. You can put the credential in the address so nothing is typed on the phone: `https://veyra-yourorg:PASSWORD@pbx.example.org/provisioning/`.
- **Typed on the phone.** In the phone's own menu or web page, set the provisioning server type to HTTPS, the server to the address without `https://`, and the enrollment user name and password.
- **The vendor's redirect service.** Some brands ask the vendor's cloud where to go the first time they start. The **Redirect services** card on [Provisioning → Templates](app:/provisioning/) lists them:

| Brand | Service | What to do |
|---|---|---|
| Yealink | Yealink RPS | Add the MAC addresses in the RPS portal with the provisioning URL as the server. |
| Poly | Poly ZTP in Poly Lens | Register the MAC addresses with the provisioning URL, or use DHCP option 160. |
| Grandstream | Grandstream GDMS | Import the MAC addresses with the provisioning URL as the config server. |
| Algo | None | Use DHCP option 66, or set the server once in the device's web page. |

Each brand has an **Export … MACs** button, for example **Export Yealink MACs**. It downloads a CSV of the phones you have registered for that brand, with the MAC address in both forms and the provisioning URL, ready to import into the vendor's portal.

## Making phones trust Veyra

Veyra's HTTPS certificate is signed by Veyra's own certificate authority (the **Veyra CA**). Phones only trust the big public certificate authorities, so a new phone refuses Veyra's certificate. There are three ways around this.

**A public certificate.** If the server has a public certificate (for example from Let's Encrypt) for the address the phones use, phones trust it already. Nothing more to do.

**The trust bootstrap (Poly and Yealink).** Over plain HTTP, Veyra hands a new phone only public information: the Veyra CA certificate and the HTTPS address. The phone installs the certificate, restarts, and downloads everything else, including its SIP password, over HTTPS. To use it:

1. Whoever runs the server sets `VEYRA_PROVISIONING_HTTP=1` in `/etc/veyra/installer.conf` and runs the installer again. Until then, Veyra does not answer plain HTTP at all.
2. Point DHCP option 66 (and 160 for Poly) on the staging or voice network at the **http** address: `http://<your Veyra server>/provisioning/`.
3. Check which networks may use the bootstrap: System → Firewall, card **Phone bootstrap networks**. Left empty, it uses the local networks from the SIP settings. Phones on any other network are refused.
4. Plug the phone in. It restarts once after the bootstrap. Its **Status** tab then shows **Trusted, HTTPS** under **Trust**.

When the bootstrap is on, the **Phone provisioning** card also shows the switch **Include the enrollment credential in the bootstrap**. Turned on, new phones get the credential from the bootstrap and nothing has to be typed. Anyone on that network can read it, though, so use it only on a separate staging network and rotate the credential after each batch of phones.

> **Important:** Once a phone has downloaded its configuration over HTTPS, Veyra refuses to send it the plain-HTTP bootstrap again. This stops someone from tricking it back onto HTTP. If you factory-reset the phone, open its device page, go to the **Status** tab and choose **Allow bootstrap again**.

**Grandstream and Algo.** These devices do not get the HTTP bootstrap. Point them straight at the **https** address. If a device refuses the certificate, download it from `https://<your Veyra server>/downloads/veyra-ca.crt` and add it in the device's web page as a trusted certificate. Grandstream's configuration from Veyra installs the Veyra CA by itself (setting `install_ca`) and leaves certificate checking off. Once the CA is installed you can turn checking on with the setting `validate_server_certificate` (see [Device profiles](guide:device-profiles)).

> **Warning:** Whoever runs the server can set `VEYRA_PROVISIONING_HTTP_MODE=full` so that every file, SIP passwords included, is also sent over plain HTTP. Use it only for phones that cannot take the certificate any other way. The **Phone provisioning** card shows a warning while it is on.

## See what a phone asked for

[Provisioning → Requests](app:/provisioning/requests/) lists every configuration request for 30 days: the time, the phone's MAC and network address, the file, the result with its reason, and the phone's software. Tick **Problems only** to see just the refused requests, or search for a MAC or address.

- **No row at all** means the phone is not reaching this server: check the provisioning URL it was given.
- **Wrong sign-in** means its credential is missing or wrong.
- **Unknown phone** means no device has that MAC address yet.
- **No such file** is usually harmless, because phones ask for optional files.

A phone Veyra does not know belongs to no organization yet, so only platform administrators see its requests.

## If something doesn't work

Open [Provisioning → Devices](app:/devices/). What you see there tells you how far the phone got.

- **The phone appears under "Phones seen but not registered".** It reached Veyra and signed in correctly, but nobody has registered its MAC address yet. Choose **Register** on its row. This list covers the last 7 days.
- **The phone is in neither list.** Veyra never saw a correct sign-in from it. Check:
  - the address on the phone or in DHCP (including `/provisioning/` at the end, and `https` or `http`);
  - the enrollment user name and password (rotate the credential if you are not sure, and use the new one);
  - that the phone can reach the server, and that the firewall lets it in;
  - the certificate. A Poly or Yealink phone that cannot use HTTPS yet needs the trust bootstrap, a public certificate, or the CA installed by hand. A phone using the bootstrap must be on one of the **Phone bootstrap networks**.
- **The phone is registered but its status is "Never provisioned".** The phone has not asked for its files since you registered it. Restart it, or wait for its daily check.
- **Status "Error".** The last request failed. Open the phone, go to the **Configuration** tab and choose **Render**. An error there (for example a missing template) is the reason. Also read the **Needs attention** box at the top of the page.
- **A reset phone no longer gets the bootstrap.** Use **Allow bootstrap again** on its **Status** tab.
- **A phone that worked is refused.** Check that **Enabled** is on in the device's settings. Disabled phones are refused their configuration.
