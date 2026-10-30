---
title: Supported phones and adapters
summary: Which phones, analog adapters and paging speakers Veyra can configure, and what to check before rolling them out.
audience: admin
section: Phones and devices
order: 15
reviewed: 0.27.55
checked: 2026-10-29
pages:
  - /provisioning/
covers:
  - provisioning/templates/official/*/template.toml
  - frontend/src/app/(app)/provisioning/page.tsx
---

Veyra configures a device through a **template** for its brand and model. The templates that come with Veyra are listed under [Provisioning → Templates](app:/provisioning/) with the source **Official**. Each official template lists the exact models it serves; the **Model** list in the phone form offers only those.

> **Important:** Every official template is marked **experimental** for now. They follow the vendors' documentation but have not yet been checked on real hardware. Before you roll out a model, set up one phone and test it: calls, keys, voicemail light, paging and the time. The template's page says so in an **Experimental template** box.

## Desk phones

| Family | Models | Notes |
|---|---|---|
| **Poly VVX** | VVX 410, VVX 411, VVX 450 | Up to 8 lines, line keys, busy lamps, voicemail light, Poly group paging, time and daylight saving, firmware. |
| **Poly Edge E series** | Edge E100, E220, E300, E320, E350, E400, E450, E500, E550 | Same configuration as the VVX family. |
| **Poly CCX** | CCX 350, 400, 500, 505, 600, 700 | Same as the VVX family, in Open SIP mode, without group paging. |
| **Yealink T3x** | T30, T30P, T31, T31G, T31P, T31W, T33G, T34W | Line keys, busy lamps, multicast paging, phone book from Veyra's directory. |
| **Yealink T4x** | T42U, T43U, T44U, T44W, T46U, T48U | As T3x. |
| **Yealink T5x** | T53, T53W, T54W, T57W, T58W, T58W Pro, VP59 | As T3x. |
| **Yealink T7x** | T73U, T73W, T74U, T74W, T77U | As T3x. |
| **Yealink T8x** | T85W, T87W, T88 | As T3x. |
| **Yealink conference phones** | CP925, CP935W, CP965 | The room's line, voicemail, directory and time; no line keys. |
| **Grandstream GRP260x** | GRP2601, 2601P, 2601W, 2602, 2602P, 2602W, 2602G, 2603, 2603P, 2604, 2604P | Up to 4 accounts, programmable keys, multicast paging, phone book. |
| **Grandstream GRP261x–GRP267x** | GRP2610, 2611G, 2612, 2612P, 2612W, 2612G, 2613, 2613W, 2614, 2615, 2616, 2624, 2634, 2636, 2650, 2670 | Up to 6 accounts and 48 programmable keys. |
| **Grandstream GXP21xx** | GXP2130, 2135, 2140, 2160, 2170 | Up to 6 accounts; the first keys are fixed line keys. |

## Analog telephone adapters (ATAs)

| Family | Models | Ports |
|---|---|---|
| **Grandstream HT801 / HT802** | HT801, HT802, HT801V2, HT802V2 | 1 or 2 |
| **Grandstream HT812 / HT814 / HT818** | HT812, HT814, HT818 and their V2 versions | 2, 4 or 8 |

Each port is one line of the device: line 1 is port 1. See [Analog adapters and fax machines](guide:analog-adapters-and-fax).

## Paging speakers, horns and adapters

**Algo SIP endpoints** covers Algo's current SIP speakers, horns, display speakers, paging adapters, intercoms, visual alerters and clocks: 8180, 8186, 8188, 8189, 8190, 8196, 8197, 8198, 8199, 8507, 8410, 8420, 8301, 8305, 8312, 8373, 8028, 8028V, 8039, 8063, 8201, 8203, 8128, 8138, 8401, 8402 and 8450 (firmware 5.5 or later).

- Line 1 registers as the device's page extension. Line 2, if you add one, is its ring extension.
- The paging zones the profile **Receive**s become the device's multicast listening zones. The template setting `multicast_format` chooses which pages it hears: `rtp` (plain multicast, the default), `poly` (Poly group paging) or `both`.

## Families and models

Templates come in two kinds:

- A **base template** (shown as *Base template* in the list) holds the settings a whole family shares, such as *Poly VVX (common settings)* or *Yealink (common settings)*. A device profile can point at it, and then serves every model of the family.
- A **model template** serves the models it lists and inherits everything else from its base template.

Which you choose in a profile is explained in [Device profiles](guide:device-profiles).

## Firmware the templates expect

Each template's page (**Overview** tab, **Firmware**) names the firmware it was written for, for example *UC Software 5.9 / 6.x* for the VVX or *Yealink firmware 66.86 / 96.86 and later*. Older firmware may ignore some settings. To update phones from Veyra, see [Phone firmware](guide:phone-firmware).

## A device that is not listed

- A model that is not listed cannot be served by an official template, even when its family is. A profile for that family shows the problem *No template under … supports model …*.
- You can make your own template, or import one someone else made. See [Customize a provisioning template](guide:customize-provisioning-templates).

## How phones first reach Veyra

The **Redirect services** card on the same page shows the provisioning URL and each vendor's zero-touch service. See [Connect phones to Veyra](guide:connect-phones-to-veyra).
