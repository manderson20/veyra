---
title: Use a softphone
summary: Register a third-party SIP softphone app on a computer or mobile phone as an extension.
audience: admin
section: Phones and devices
order: 25
reviewed: 0.27.67
pages:
  - /extensions/
covers:
  - docs/guides/softphones.md
---

A **softphone** is an app that acts as a phone on a computer or mobile phone. Veyra has no softphone of its own, but any standard SIP softphone can register as an extension. Veyra does not configure the app for you: you enter the details by hand.

> **Note:** No particular softphone has been tested with Veyra yet. Try one on a test extension first.

## Before you start

- Create the extension, or choose an existing one, under [Telephony → Extensions](app:/extensions/).
- To use the softphone beside a desk phone on the same extension, raise **Phones that may register** on the extension, and deploy. Otherwise leave it as it is.
- The app's device must be able to reach the Veyra server on your network, and the firewall must allow it. For use outside the building, connect through your VPN rather than opening Veyra's SIP ports to the internet.

## Enter the details

Open the extension's **Credentials** tab. **Show secret** reveals the secret, and the audit log records that you did. Enter these in the softphone:

| The app asks for | Enter |
|---|---|
| User name, or auth name | **User name** from the Credentials tab, such as `lincoln-1204` |
| Password | **Secret** from the Credentials tab |
| Domain, server or registrar | The Veyra server's name or address |
| Transport | UDP or TCP, or TLS if you turned it on in Telephony settings |

Keep the secret to yourself. Anyone who has it can make calls as that extension.

## Check it

1. Open [Telephony → Registrations](app:/registrations/): the extension should be listed with the address of the app's device.
2. Call another extension, then have someone call you.

## If something doesn't work

- **The app does not register.** Check the user name and secret against the Credentials tab, and that you deployed after creating the extension. Check that the firewall allows the device's network.
- **Calls connect but there is no sound, or sound one way.** The firewall or a home router is blocking the audio. Connect through your VPN.
- **The app stops ringing on a mobile phone.** Mobile systems put background apps to sleep, and Veyra has no push notifications. Check the app's own battery and background settings.
- **The desk phone stopped registering.** The extension allows too few phones. Raise **Phones that may register**.
