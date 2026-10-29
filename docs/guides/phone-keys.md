---
title: Phone keys
summary: Set up the programmable keys on desk phones (lines, busy lamps, speed dials, paging, parking and more) and decide which keys users may change.
audience: admin
section: Phones and devices
order: 40
reviewed: 0.27.45
checked: 2026-10-29
pages:
  - /device-profiles/view/
  - /devices/view/
covers:
  - frontend/src/components/devices/KeyListEditor.tsx
  - frontend/src/components/portal/PhoneKeysCard.tsx
  - backend/veyra/api/v1/device_common.py
---

Most desk phones have a row of buttons with a small light next to each one. Veyra sets these keys for you. You make the key list once in a [device profile](guide:device-profiles), and every phone of that profile gets the same keys in the same order.

## Edit the key list

1. Open the profile under [Provisioning → Device Profiles](app:/device-profiles/). The **Line keys** heading holds the list.
2. Choose **Add key**. A new key starts as a busy lamp (BLF).
3. Pick the key type, fill in what it needs (below), and optionally a **Label**, the text shown next to the key. Without a label the phone shows the name of what the key calls.
4. Use the up and down arrows to change the order, and the bin to remove a key.
5. Choose **Save changes**.

The first key in the list is the phone's first programmable key. The phone's own line always comes first with a key of its own, so you do not need to add it; add more lines, BLF, speed dial, paging and other keys here. A profile can have up to 48 keys. A phone with fewer buttons uses the first ones (some phones show the rest on extra pages).

## Key types

| Type | What you enter | What the key does |
|---|---|---|
| **Line** | A line number, 1 to 8 | Shows one of the phone's lines (extensions). |
| **BLF (watch a phone or group)** | An extension or ring group number | The light shows when that number is busy or ringing. Press it to call, or to pick up a call ringing there. |
| **Speed dial** | A number | Calls the number. Digits, `*`, `#` and `+` only, with no spaces or dashes. |
| **Page a zone** | A paging zone | Pages the zone. Choose **From a variable (per building)…** to use a provisioning variable such as `$all_call` instead, so each building pages its own zone. |
| **User's choice (set from My Phone)** | Nothing | An open slot the phone's user fills (see below). |
| **Voicemail** | A line number, or nothing for line 1 | Calls voicemail. The light shows waiting messages. |
| **Intercom to an extension** | An extension number | Calls the extension, which answers on its speaker by itself. |
| **Do Not Disturb (lit while on)** | Nothing | Turns Do Not Disturb on and off for this phone. |
| **Park (a lot, or watch a slot)** | A parking lot, such as `front-desk`, or a lot and slot, such as `front-desk:2972` | With a lot: parks the current call. With a slot: lights while a call is parked there; press it to pick the call up. |
| **Toggle (call flow, time condition, queue log-in)** | `flow:<call flow>`, `tc:<time condition>`, `agent` or `queue:<queue>` | Switches a call flow or a time condition override, or logs the phone in and out of its queues (`agent`) or one queue. The light is on while it is switched or logged in. |
| **Transfer** | Nothing | Transfers the current call. Not every phone has a transfer key: where it has none, the preview says so and the phone's own soft key does it. |
| **Presence of a colleague** | An extension number | Lit while the colleague is busy or in a meeting, blinking while away, off when available. Press it to call them. |

Hover over the value field of the voicemail, intercom, presence, park and toggle types to see a hint.

Parking lots, call flows, time conditions and queues are referred to by their short name (slug), as shown on their own pages. Veyra checks each one when you save. A time condition needs an override code before a toggle key can switch it.

> **Tip:** Any value can be a provisioning variable written as `$name`, for example `$front_office`. Each phone then takes the value defined for its site or profile. See [Provisioning variables](guide:provisioning-variables).

## Keys that users choose themselves

Add keys of the type **User's choice (set from My Phone)** to leave open slots. The person whose extension is on the phone can then put a speed dial, a busy lamp or a presence key in each open slot from **My Phone** in Veyra.

Every other key is **locked**: users see it with a padlock and cannot change it. Use this for keys everyone must keep, such as an all-call paging key.

An administrator can change a user's keys too. On the phone's page, open the **Line keys** tab. When the profile has open slots and the phone has an extension, the **User's keys** card shows each key: **Set** or **Change** an open slot, or **Clear** it. The phone picks up the change within a minute.

## A different key list for one phone

1. Open the phone under [Provisioning → Devices](app:/devices/) and go to the **Line keys** tab.
2. Tick **Override the profile's keys for this phone**. The profile's keys are copied as a starting point.
3. Change the list and choose **Save changes**.

From now on this phone ignores changes to the profile's keys. Untick the box and save to go back to the profile's keys.

## If something doesn't work

Veyra checks every key when you save and names the key that is wrong:

- *key 3: enter a number to dial or watch.* A BLF, speed dial, intercom or presence key needs digits only (also `*`, `#`, `+`), without spaces.
- *a line key names a line number 1-8.*
- *paging zone … not found*, *parking lot … not found*, *call flow … not found*, *queue … not found*. Check the short name on that item's page.
- *the time condition … has no override code.* Give the time condition an override code first.

If a key does not appear on the phone, open the phone's **Configuration** tab and choose **Render**. A key that uses a variable nobody defined is listed under **Missing variables** and is left out until you define it.
