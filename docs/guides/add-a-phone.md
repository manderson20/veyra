---
title: Add a phone
summary: Map phones to extensions by MAC address, give them a template, and check that it picked up its configuration.
audience: admin
section: Phones and devices
order: 20
reviewed: 0.27.64
pages:
  - /devices/
  - /devices/view/
covers:
  - frontend/src/app/(app)/devices/*
  - frontend/src/app/(app)/devices/view/*
  - frontend/src/components/devices/DeviceDialog.tsx
  - frontend/src/components/devices/ImportListDialog.tsx
  - backend/veyra/api/v1/devices.py
---

Veyra knows each phone by its **MAC address**, the hardware address printed on the label under the phone and on its box. When a phone asks for its configuration, Veyra looks up the MAC address, takes the phone's **template** and **extension**, and builds the files for that exact model.

## Before you start

- The phones must know how to reach Veyra. See [Connect phones to Veyra](guide:connect-phones-to-veyra).
- Create a template for this kind of phone first. See [Phone templates](guide:device-profiles).
- Create the extension the phone will use (under Telephony → Extensions).

## Extension Mapping

[Provisioning → Extension Mapping](app:/devices/) is one table of all your phones. Each row shows:

- **Extension:** the number and name, with the phone's label under them.
- **Brand / MAC:** the manufacturer and the MAC address.
- **IP / Status:** the address the phone last fetched from, and its status:
  - **Current** (green): the phone has fetched since the last change to its template or its own settings.
  - **Waiting for phone** (yellow): it has not fetched since that change. It catches up at its next check, or use **Update Phones**.
  - **Never fetched**, **No template** or **Error**.
- **Template / Model:** change either one right in the row. The Template list shows only the row's brand. A new template clears the phone's setting overrides.

Search by extension, name, MAC address, IP address, brand or model. **Open** shows the phone's own page.

> **Note:** The status follows templates and phone settings. A changed provisioning variable or base file does not turn it yellow; changing a variable asks the phones to re-read their configuration anyway.

## Add a phone

1. Choose **Add Extension**. A new row opens at the top of the table.
2. Fill in the row:
   - **Organization:** shown only if you manage more than one.
   - **Extension:** the extension the phone registers as. Without it, the phone gets its configuration but does not register.
   - **Brand** (required).
   - **MAC address** (required): from the phone's label. Colons or dashes are optional, so `00:04:f2:ab:cd:ef` and `0004F2ABCDEF` are both fine. Each MAC address can be registered only once.
   - **Template:** only this brand's are listed, and its default template is already chosen. Without a template, nothing is sent to the phone.
   - **Model** (required): pick the exact model, because the model decides which base file is used.
3. Choose **Save**.

The phone gets its configuration the next time it checks in. To make it check now, restart it, or use **Update Phones**.

A label, site and dispatchable location for emergency calls are on the phone's own page.

## Change many phones

Tick the phones in the table, or tick the box in the heading for the whole page. A bar appears above the table:

- **Use Selected:** choose a template and move every selected phone to it. The phones must be one brand and one organization. If one cannot move, none do. Their setting overrides are cleared.
- **Update Phones:** ask the selected phones to re-read their configuration now.

## Export and import the list

**Export List** downloads a CSV for the organization chosen in the filter, otherwise your own. Its columns are `mac`, `extension`, `brand`, `model`, `template` and `label`.

**Import List** reads the same format. Rows match on the MAC address: a match is updated and anything else becomes a new phone, which needs a brand and a model. An empty cell keeps the value, and a dash (`-`) clears it. Choose **Check** to see what would happen, then **Import**. A row with an error is left alone and listed.

### Register a phone that has already called in

If a phone reaches Veyra and signs in with the enrollment credential before you register it, it appears in the card **Phones seen but not registered** at the top of Extension Mapping. The card shows its MAC address, the model it reported, its network address and when it was last seen (phones from the last 7 days).

Choose **Register** on its row. The MAC address, manufacturer, model and organization are filled in for you. Choose the template and extension, then **Register phone**.

## The phone's page

Click a phone in the list to open it. 

### Settings tab

Here you change everything from the registration form, and also:

- **Building:** the building the phone is in. The list shows the buildings of the phone's site; **No building** leaves it unset.

- **Extra lines:** **Add line** gives the phone a second, third… extension, up to 8 lines in all. Each extension can appear only once on a phone. On an analog adapter, each line is one phone port (see [Analog adapters and fax machines](guide:analog-adapters-and-fax)).
- **Firmware override:** a firmware image for this phone only. Left on **From the template**, the phone gets the template's firmware. See [Phone firmware](guide:phone-firmware).
- **Setting overrides:** the template's settings for this phone only. A blank field keeps the template's value, which is shown greyed in the field. A yes/no setting is a list: **As the template** (which shows the template's value), **Yes** or **No**. Secret settings, such as passwords, are shown as dots.
- **Enabled:** a disabled phone is refused its configuration until you turn it back on.

Choose **Save changes**. The phone takes the change at its next check, or right away if you choose **Reprovision**.

> **Note:** Changing the **Template** clears this phone's setting overrides, because they belong to the old one.

### Line keys tab

By default the phone uses its template's keys. Tick **Override the template's keys for this phone** to give this phone its own key list. See [Phone keys](guide:phone-keys).

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

- *No template: nothing is served to this phone.* Choose a template.
- *No extension: the phone will not register.* Choose an **Extension (line 1)**.
- *No base file under … supports model …* The template's family has no base file for this model. Check the model, or pick another profile.
- *The extension of line 1 no longer exists.* Choose another extension.

## If something doesn't work

- **The phone does not pick up its configuration.** Work through *If something doesn't work* in [Connect phones to Veyra](guide:connect-phones-to-veyra).
- **The phone downloaded its files but does not register.** Check that it has an **Extension (line 1)**, then look at [Telephony → Registrations](app:/registrations/) (see [See which phones are registered](guide:see-registered-phones)). If more phones share the extension than it allows, the last phone to register pushes out the earliest.
- **"A device with that MAC address is already registered."** Search Extension Mapping for the MAC address. If you cannot find it, it is registered in an organization you cannot see; ask an administrator of that organization.
- **A change does not show on the phone.** Choose **Reprovision**. If the phone is not registered, restart it by hand.
