---
title: Device profiles
summary: Group phones that share a template, settings, keys, paging zones and firmware, for example one profile per building.
audience: admin
section: Phones and devices
order: 30
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /device-profiles/
  - /device-profiles/view/
covers:
  - frontend/src/app/(app)/device-profiles/*
  - frontend/src/app/(app)/device-profiles/view/*
  - frontend/src/components/devices/ProfileFields.tsx
  - frontend/src/hooks/useProfileOptions.ts
  - backend/veyra/api/v1/device_profiles.py
  - backend/veyra/api/v1/device_common.py
---

A **device profile** holds everything that phones of one kind share: the template, the settings, the line keys, the paging zones and the firmware. Each phone points at one profile. Change the profile once and every phone using it follows.

A good rule: one profile per kind of phone and per building, for example *VVX, Building A* and *VVX, Building B*. The two differ only in their paging zones and maybe a few keys. [Provisioning variables](guide:provisioning-variables) can often replace such near-copies: one profile, with a value that differs per site.

## Create a profile

1. Open [Provisioning → Device Profiles](app:/device-profiles/) and choose **New profile**.
2. Fill in:
   - **Organization:** shown only if you manage more than one.
   - **Name** (required): unique within the organization, for example *VVX, Building A*.
   - **Site (optional):** the building these phones are in. Phones registered with this profile take this site unless you choose another. The site sets the phones' time zone and the site's provisioning variables.
   - **Template** (required): choose a **family** or a single **model**:
     - A *family* (listed as *Manufacturer — Name (family)*) serves every model under it. One "Poly VVX" profile can hold VVX 411 and VVX 450 phones together. Veyra picks the right template for each phone's model.
     - A *model* template serves only the models listed next to it.
   - **Description:** for your own notes.
   - **Firmware:** the firmware image the phones should run. Leave **Keep the phones' current firmware** if Veyra should not manage it. Only images for the template's manufacturer are listed. See [Phone firmware](guide:phone-firmware).
3. Fill in the settings, line keys and paging zones (below).
4. Choose **Create profile**.

Then register phones against it on the Devices page (see [Add a phone](guide:add-a-phone)).

## Settings

Once you choose a template, the **Settings** heading lists the settings that template offers, such as the SIP transport, how often the phone checks for changes, an administrator password for the phone's own menus, or the screen saver. Each field shows the template's default greyed; leave it empty to keep the default. Yes/no settings are tick boxes. A password setting is never shown again once saved: the field shows dots, and typing replaces it. The name under each field (for example `polling_hour`) is the setting's name in the template.

What the settings mean depends on the template. You can read their descriptions and defaults on the template's **Variables** tab under [Provisioning → Templates](app:/provisioning/).

> **Note:** Changing a profile's template clears its settings, because the new template has different ones.

A single phone can override any of these on its own page (**Setting overrides**).

## Line keys

The keys every phone of the profile gets, in order. See [Phone keys](guide:phone-keys) for each key type, open slots that users fill themselves, and per-phone overrides.

## Paging zones

The **Paging zones** heading lists the paging zones of the organization (they are made under Telephony → Paging Zones). For each zone the phones should take part in:

1. Tick the zone.
2. Choose what the phones do:
   - **Receive:** the phones play pages sent to this zone.
   - **Send:** the phones may page this zone.
3. Optionally give the zone a role: **Default group**, **Priority group** or **Emergency group**. Each role can be given to only one zone in a profile. On Poly phones, the default group is the one the phone's paging button uses, and priority and emergency pages interrupt calls.

A profile can take part in up to 25 zones. A phone cannot change its zones on its own: to give one phone different zones, give it a different profile.

## The profile's page

Click a profile in the list to open it. Besides the same form, it shows:

- **Models served:** each model the profile can serve and the exact template it uses. Click a template to open it.
- **Information:** how many phones use the profile (**view** lists them), its firmware, and when it was created and changed.

Choose **Save changes** after editing. Phones pick up the change at their next daily check. To push it to a phone now, use **Reprovision** on that phone's page.

The list of profiles shows a **Ready** badge, or the first problem, for example:

- *No model template inherits from this family yet.* The family has no templates for any model, so no phone can use it.
- *Template … is missing; devices cannot be provisioned.* The template was deleted or failed to load. Pick another template.

## Delete a profile

**Delete** works only while no phone uses the profile. Move its phones to another profile first: filter the Devices list by the profile (**view** on the profile's page) and change each phone's **Device profile**.

## If something doesn't work

- **A model is missing from "Models served".** The template family has no template for that model. Check [Supported phones and adapters](guide:supported-phones).
- **"A device profile with that name exists in this organization."** Choose another name.
- **"only one zone can be the default group"** (or priority, or emergency). Give that role to a single zone.
- **A setting is refused** (for example *has an invalid format*). The template only allows certain values. Read the setting's description on the template's **Variables** tab.
