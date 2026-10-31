---
title: Add a phone
summary: Register a phone by its MAC address, give it a profile and extensions, and check that it picked up its configuration.
audience: admin
section: Phones and devices
order: 20
reviewed: 0.27.62
pages:
  - /devices/
  - /devices/view/
covers:
  - frontend/src/app/(app)/devices/*
  - frontend/src/app/(app)/devices/view/*
  - frontend/src/components/devices/DeviceDialog.tsx
  - backend/veyra/api/v1/devices.py
---

Veyra knows each phone by its **MAC address**, the hardware address printed on the label under the phone and on its box. When a phone asks for its configuration, Veyra looks up the MAC address, takes the phone's **device profile** and **extension**, and builds the files for that exact model.

## Before you start

- The phones must know how to reach Veyra. See [Connect phones to Veyra](guide:connect-phones-to-veyra).
- Create a device profile for this kind of phone first. See [Device profiles](guide:device-profiles).
- Create the extension the phone will use (under Telephony → Extensions).

## Register a phone

1. Open [Provisioning → Devices](app:/devices/) and choose **Register a phone**.
2. Fill in the form:
   - **Organization:** shown only if you manage more than one.
   - **MAC address** (required): from the phone's label. Colons or dashes are optional, so `00:04:f2:ab:cd:ef` and `0004F2ABCDEF` are both fine. Each MAC address can be registered only once.
   - **Manufacturer** and **Model** (required): the list shows the models Veyra has templates for. Pick the exact model, because the model decides which template is used.
   - **Label:** a name you will recognize, such as *Room 112*.
   - **Device profile:** the profile with the settings and keys for this phone. Only profiles for the phone's manufacturer are listed. Without a profile, nothing is sent to the phone.
   - **Extension (line 1):** the extension the phone registers as. Without it, the phone gets its configuration but does not register.
   - **Site:** leave it on **From the profile** to use the profile's site. The site sets the phone's time zone.
   - **Location (dispatchable):** the floor and room, used for emergency calls from this phone. It wins over the extension's location. You can change it later on the phone's page.
3. Choose **Register phone**.

The phone gets its configuration the next time it checks in. To make it check now, restart it, or use **Reprovision** on its page (see below).

### Register a phone that has already called in

If a phone reaches Veyra and signs in with the enrollment credential before you register it, it appears in the card **Phones seen but not registered** at the top of the Devices page. The card shows its MAC address, the model it reported, its network address and when it was last seen (phones from the last 7 days).

Choose **Register** on its row. The MAC address, manufacturer, model and organization are filled in for you. Choose the profile and extension and register it as above.

## The phone's page

Click a phone in the list to open it. The list can be searched by label, MAC address, model or extension number, and filtered by profile.

### Settings tab

Here you change everything from the registration form, and also:

- **Building:** the building the phone is in. The list shows the buildings of the phone's site; **No building** leaves it unset.

- **Extra lines:** **Add line** gives the phone a second, third… extension, up to 8 lines in all. Each extension can appear only once on a phone. On an analog adapter, each line is one phone port (see [Analog adapters and fax machines](guide:analog-adapters-and-fax)).
- **Firmware override:** a firmware image for this phone only. Left on **From the profile**, the phone gets the profile's firmware. See [Phone firmware](guide:phone-firmware).
- **Setting overrides:** the template's settings for this phone only. A blank field keeps the profile's value, which is shown greyed in the field. A yes/no setting is a list: **As the profile** (which shows the profile's value), **Yes** or **No**. Secret settings, such as passwords, are shown as dots.
- **Enabled:** a disabled phone is refused its configuration until you turn it back on.

Choose **Save changes**. The phone takes the change at its next check, or right away if you choose **Reprovision**.

> **Note:** Changing the **Device profile** clears this phone's setting overrides, because they belong to the old template.

### Line keys tab

By default the phone uses its profile's keys. Tick **Override the profile's keys for this phone** to give this phone its own key list. See [Phone keys](guide:phone-keys).

### Configuration tab

Choose **Render** to see the exact files the phone downloads, built now, with passwords masked. Use it to check a change before the phone gets it. If a template setting or key uses a provisioning variable that nobody has defined, a **Missing variables** box lists it.

The **Variables** card lists the provisioning variables that reach this phone and where each comes from (**Installation**, **Organization**, **Site** or **Profile**). See [Provisioning variables](guide:provisioning-variables).

### Status tab

- **Provisioning:** the status, the last request and its result, the address it came from, what the phone reports about itself, the template used, the phone's own **Credential user**, and **Trust** (whether it has switched to HTTPS).
- **Firmware:** the version assigned, the version the phone is running, and whether it is **Up to date** or has an **Update pending**.

## Buttons at the top

- **Reprovision:** asks the phone to download its configuration again now.
- **Reboot:** asks the phone to restart.
- **Delete:** removes the phone from Veyra. The phone keeps its last configuration until it is reset, but its own provisioning password stops working.

**Reprovision** and **Reboot** send a message to the phone over its line 1 registration. They work only when the phone has an extension and is registered right now.

## What the status means

| Status | Meaning |
|---|---|
| **Never provisioned** | The phone has not downloaded anything since it was registered. |
| **Provisioned** | The last request worked. |
| **Not seen lately** | The phone has not checked in for 48 hours. Phones check once a day, so it may be off or unplugged. |
| **Error** | The last request failed. Look at the **Configuration** tab and the **Needs attention** box. |

The **Needs attention** box at the top of a phone's page lists problems such as:

- *No profile: nothing is served to this phone.* Choose a profile.
- *No extension: the phone will not register.* Choose an **Extension (line 1)**.
- *No template under … supports model …* The profile's template family has no template for this model. Check the model, or pick another profile.
- *The extension of line 1 no longer exists.* Choose another extension.

## If something doesn't work

- **The phone does not pick up its configuration.** Work through *If something doesn't work* in [Connect phones to Veyra](guide:connect-phones-to-veyra).
- **The phone downloaded its files but does not register.** Check that it has an **Extension (line 1)**, then look at [Telephony → Registrations](app:/registrations/) (see [See which phones are registered](guide:see-registered-phones)). If more phones share the extension than it allows, the last phone to register pushes out the earliest.
- **"A device with that MAC address is already registered."** Search the Devices list for the MAC address. If you cannot find it, it is registered in an organization you cannot see; ask an administrator of that organization.
- **A change does not show on the phone.** Choose **Reprovision**. If the phone is not registered, restart it by hand.
