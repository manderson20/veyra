---
title: Set up paging zones and overhead speakers
summary: Group your overhead speakers and Poly phones into paging zones that anyone allowed can page by dialling a number.
audience: admin
section: Paging and bells
order: 10
reviewed: 0.27.45
pages:
  - /paging-zones/
covers:
  - frontend/src/app/(app)/paging-zones/*
  - frontend/src/components/paging/PagingZoneDialog.tsx
  - backend/veyra/api/v1/paging_zones.py
---

A **paging zone** is one area that hears a page together: a building, a wing, a floor, the gym, outdoors. Each zone ties together two things:

- the **multicast address** your overhead speakers already listen to (Algo, CyberData, AND and similar speakers), and
- the **Poly group number** that Poly desk phones listen to for the same area.

Poly phones only play Poly group pages, and speakers only play plain multicast. Veyra sends every page in both formats at the same moment, so the phones and the speakers in a zone play it together.

Once a zone has a number, anyone allowed can pick up a phone, dial that number and talk. To combine several zones, or to play a recording (a bell, a chime, a lockdown drill message), create a page on top of the zones: see [Create and send pages](guide:send-a-page).

> **Warning:** Paging over the phone system is not a life-safety notification system. Use it for announcements, bells and drills. It does not replace your fire alarm or a certified mass notification system.

Zones are listed under [Telephony → Paging Zones](app:/paging-zones/).

## Before you start

- On each speaker, note the multicast address and port it plays (on an Algo or CyberData speaker, the multicast zone settings on its web page). Speakers in the same zone share one address and port.
- Decide which Poly group number (1 to 24) each zone uses. Group 25 is Poly's emergency group.
- You need permission to change paging (`paging.write`). Organization administrators have it.

## Create a zone

1. Choose **New paging zone**.
2. Fill in the form:

| Field | What to enter |
|---|---|
| **Name** | What people call the area, for example *Building A*. Required. |
| **Site (optional)** | The site the zone belongs to, shown in the list. |
| **Speakers' multicast address** | The address the speakers listen to, between 224.0.0.0 and 239.255.255.255, for example `239.1.2.10`. Required. |
| **Speakers' port** | The speakers' port, 1024 to 65535. Default 5004. |
| **Poly group number** | 1 to 24 for normal zones; 25 is Poly's emergency group. Each zone of an organization needs its own group number. |
| **Kind** | **Normal**, **Priority (interrupts calls)**, or **Emergency (group 25)**. Priority and emergency pages play on Poly phones even during a call. |
| **Poly paging address** / **Poly paging port** | One address and port that all Poly phones of the organization listen on. Leave the default (224.0.1.116, port 5001) unless your network needs another. |
| **Codec** | **G.711 µ-law (default)** works everywhere. **G.722 (wideband)** sounds better if all your speakers and phones support it. |
| **Number to dial (optional)** | The number people dial to page this zone live. It comes from the same numbering plan as extensions, groups and pages, so it cannot be in use already. |
| **Longest page (seconds)** | 5 to 600, default 120. The page is cut off after this. |
| **Who may page it** | See below. |
| **Description** | Optional notes. |
| **Enabled** | A disabled zone is left out of the phones' paging groups. |

3. Choose **Create zone**.
4. A *Changes not yet deployed* note appears on the page. Use **Deploy changes** in the top bar so the phone system learns the zone's number. Phones get the zone itself at their next provisioning check.

## Who may page a zone

**Who may page it** decides which phones can dial the zone's number:

- **Everyone in the organization**: any phone of the organization.
- **Listed phones only**: only the phones you add under **Phones allowed to page**. With nobody listed, nobody can page the zone from a phone, and the zone shows a warning.
- **Only from Veyra (interface, bells, API)**: no phone can dial it. Pages that include the zone can still be started from Veyra, by a bell schedule or by another system.

## Make the phones hear the zone

Poly phones listen to a zone only when their **template** subscribes them to it. Open your phones' brand in the Provisioning menu, choose the template they use, and pick the zones its phones should hear. The **Profiles** column of the zones list shows which profiles use each zone. Phones pick up the change at their next provisioning check.

Speakers need no change in Veyra: they already listen to their multicast address.

## Page a zone from a phone

Dial the zone's number from a phone that is allowed to page it. After the short tone, speak; hang up to end the page. A phone that is not allowed hears an "invalid" message. The page stops by itself after the zone's **Longest page** time.

## Reading the list

The **Status** column shows **Ready**, **Disabled**, or the first problem found, for example:

- *Only members may page this zone, and it has none.* Add phones, or choose another **Who may page it**.
- *Zones of this organization use different Poly paging addresses or ports.* Poly phones listen on one address, so give every zone of the organization the same **Poly paging address** and **port**.
- *Another organization pages the same multicast address and port.* On a shared network, both organizations' speakers would play each other's pages. Give one of them another address.
- *Poly phones use group 25 for emergency pages.* An **Emergency** zone should use Poly group 25.

## Delete a zone

Use the bin icon on the zone's row. A zone that a template still uses cannot be deleted: remove it from those templates first.

## If something doesn't work

- **Speakers play but Poly phones do not:** check that the phones' template subscribes them to the zone, and that the phones have checked in since.
- **Phones play but speakers do not:** compare the **Speakers' multicast address** and **port** with the speaker's own settings. Multicast must be allowed between the server and the speakers on your network.
- **"That number is already used":** another extension, group, page or zone has that number. Choose another.
- **"Another zone of this organization already uses that Poly group number":** each zone needs its own group number.
