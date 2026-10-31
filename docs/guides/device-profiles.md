---
title: Phone templates
summary: Each brand has its templates. A template holds the settings, line keys, paging zones and firmware that a group of phones share.
audience: admin
section: Phones and devices
order: 30
reviewed: 0.27.63
checked: 2026-10-29T20:28Z
pages:
  - /provisioning/brands/
  - /provisioning/brands/view/
  - /provisioning/brands/template/
covers:
  - frontend/src/app/(app)/provisioning/brands/*
  - frontend/src/app/(app)/provisioning/brands/view/*
  - frontend/src/app/(app)/provisioning/brands/template/*
  - frontend/src/components/devices/NewTemplateDialog.tsx
  - frontend/src/components/devices/ProfileFields.tsx
  - frontend/src/hooks/useProfileOptions.ts
  - backend/veyra/api/v1/device_profiles.py
  - backend/veyra/api/v1/device_common.py
---

Veyra organizes phones the way many administrators already think of them. **Base files** are the system defaults for each brand and model. **Templates** are yours: each one belongs to a brand and holds what a group of phones share, namely the settings, line keys, paging zones and firmware. Each phone uses one template. Change the template once and every phone using it follows.

These were called device profiles before version 0.27.63. Your existing profiles are now your templates, with nothing to convert.

A good rule: one template per kind of phone and per building, for example *VVX, Building A* and *VVX, Building B*. The two differ only in their paging zones and maybe a few keys. [Provisioning variables](guide:provisioning-variables) can often replace such near-copies: one template, with a value that differs per site.

## Brands

The **Provisioning** menu has one entry per brand. A brand's page lists its templates and, under **Used By**, the extensions of the phones on each one. A template with no phones says **Not in use**. Click a chip to open that phone.

The page also has a **Connect new phones** card with the provisioning URL, the brand's redirect service and its MAC export.

To add a brand, open [Provisioning → Add Brand](app:/provisioning/brands/) and choose **Add Brand** to import a base file for it. The file names its brand and models.

## Create a template

1. Open the brand in the Provisioning menu and choose **New Template**.
2. Fill in:
   - **Organization:** shown only if you manage more than one.
   - **Name** (required): unique within the organization, for example *VVX, Building A*.
   - **Site (optional):** the building these phones are in. Phones registered with this template take this site unless you choose another. The site sets the phones' time zone and the site's provisioning variables.
   - **Base file** (required): a **family** or a single **model**. If the brand has only one family, it is already chosen.
     - A *family* serves every model under it. One "Poly VVX" template can hold VVX 411 and VVX 450 phones together. Veyra picks the right file for each phone's model.
     - A *model's* base file serves only the models listed next to it.
   - **Default template for this brand:** new phones of this brand start on this template. Each brand has one default per organization, so ticking this replaces the old one.
   - **Description:** for your own notes.
   - **Firmware:** the firmware image the phones should run. Leave **Keep the phones' current firmware** if Veyra should not manage it. Only images for this brand are listed. See [Phone firmware](guide:phone-firmware).
3. Fill in the settings, line keys and paging zones (below).
4. Choose **Create template**.

Then choose it for phones on the Extension Mapping page (see [Add a phone](guide:add-a-phone)).

## Settings

Once you choose a base file, the **Settings** heading lists the settings it offers, such as the SIP transport, how often the phone checks for changes, an administrator password for the phone's own menus, or the screen saver. Each field shows the default greyed; leave it empty to keep the default. Yes/no settings are tick boxes. A password setting is never shown again once saved: the field shows dots, and typing replaces it. The name under each field (for example `polling_hour`) is the setting's name in the base file.

What the settings mean depends on the base file. You can read their descriptions and defaults on its **Variables** tab under [Provisioning → Base Files](app:/provisioning/).

> **Note:** Changing a template's base file clears its settings, because the new file has different ones.

A single phone can override any of these on its own page (**Setting overrides**).

## Line keys

The keys every phone of the template gets, in order. See [Phone keys](guide:phone-keys) for each key type, open slots that users fill themselves, and per-phone overrides.

### Different keys for one model

**Available Phones**, at the bottom of the template's page, lists every model the template serves. Each row shows the model, its base file and whether it uses the template's keys.

1. Click the model.
2. Tick **Give this model its own keys**. The list starts as a copy of the template's keys.
3. Change the list and choose **Done**.
4. Save the template.

Untick the box to return the model to the template's keys. A phone's own key override still wins over both.

## Paging zones

The **Paging zones** heading lists the paging zones of the organization (they are made under Telephony → Paging Zones). For each zone the phones should take part in:

1. Tick the zone.
2. Choose what the phones do:
   - **Receive:** the phones play pages sent to this zone.
   - **Send:** the phones may page this zone.
3. Optionally give the zone a role: **Default group**, **Priority group** or **Emergency group**. Each role can be given to only one zone in a template. On Poly phones, the default group is the one the phone's paging button uses, and priority and emergency pages interrupt calls.

A template can take part in up to 25 zones. A phone cannot change its zones on its own: to give one phone different zones, give it a different template.

## Save

- **Save** stores the template. Phones pick up the change at their next daily check.
- **Save and Update Phones** also asks each phone with an extension to re-read its configuration now. It works even with nothing to save, and reports how many phones accepted. A phone that does not answer picks up the change at its next check.

Veyra builds a phone's files when the phone asks for them, so there is no separate rebuild step.

A problem with a template shows as a badge, for example:

- *No model's base file inherits from this family yet.* The family has no file for any model, so no phone can use it.
- *Base file … is missing; phones cannot be provisioned.* The base file was deleted or failed to load. The template then appears under **Other** in the Provisioning menu. Pick another base file.

## Delete a template

**Delete** works only while no phone uses the template. Move its phones to another template first: click **more** under **Used By** or filter Extension Mapping by the template, and change each phone's **Template**.

## If something doesn't work

- **A model is missing from Available Phones.** The family has no base file for that model. Check [Supported phones and adapters](guide:supported-phones).
- **"A template with that name exists in this organization."** Choose another name.
- **"only one zone can be the default group"** (or priority, or emergency). Give that role to a single zone.
- **A setting is refused** (for example *has an invalid format*). The base file only allows certain values. Read the setting's description on its **Variables** tab.
- **"… phone(s) use this template; move them first."** A template with phones cannot change to another brand's base file.

## Encrypt call audio

On a Poly or Yealink template, **SRTP** encrypts call audio between the phone and Veyra. It can be **off**, **optional** (falls back to plain audio) or **required**.

SRTP needs TLS:

1. Turn on the TLS transport in Telephony settings.
2. Set the template's **SIP transport** to `TLS`.
3. Set **SRTP** and save, then let the phones pick up their new configuration.

Veyra refuses SRTP without TLS, because the encryption keys travel in the signalling.

> **Note:** If several phones share an extension and not all of them require SRTP, the extension accepts plain audio. Only the leg between the phone and Veyra is encrypted; calls to your carrier are not covered.
