---
title: Park calls
summary: Set up a parking lot so a call can be put on hold at one phone and picked up from any other.
audience: admin
section: Calls and call flows
order: 40
reviewed: 0.27.44
pages:
  - /parking/
  - /parking/view/
covers:
  - frontend/src/app/(app)/parking/*
  - frontend/src/components/callflow/ParkingLotFields.tsx
  - backend/veyra/api/v1/parking_lots.py
---

Parking puts a call on hold in a numbered *slot* that every phone can reach. The secretary answers a call for the principal, parks it, pages "call for Mrs Lee on 71", and Mrs Lee picks it up from the phone nearest to her.

## How people use it

| To | Do this |
|---|---|
| Park a call | Transfer it to the lot's **park extension** (for example `70`). The phone system reads back the slot number, for example 71. |
| Pick up a parked call | Dial the slot number (for example `71`) from any phone. `*85` and the slot number does the same. |
| See waiting calls | A line key (BLF) set to a slot number lights while a call waits there. |

If nobody picks the call up in time, the phone that parked it rings again. If that phone does not answer either, the call goes to the lot's destination.

## Create a parking lot

You need permission to change ring groups, queues and conference rooms (organization and site administrators by default).

1. Open [Telephony → Parking](app:/parking/) and choose **New parking lot**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, the **Park extension**, the **First slot** and the **Last slot**. The suggested `70` with slots `71` to `79` suits most sites. Every one of these numbers must be free in the organization: not an extension, group or other number. The park extension must not lie inside the slot range, and a lot has at most 50 slots.
4. Choose **Create lot**. Veyra opens the lot's page.

## Set the timeout

On the lot's page:

- **Parked call times out after (seconds)**: 10 to 1800. Then the phone that parked the call rings.
- **Ring the parker for (seconds)**: 5 to 120.
- **When the parker does not answer**: where the call goes then, for example the reception ring group or the main menu, or **Hang up**.
- **Play a courtesy tone when a call is picked up**.
- **Enabled**: a disabled lot is left out of the phone system.

Choose **Save**, then **Deploy changes** in the top bar. The **On the phones** card sums up what users do with the lot.

## Line keys for slots

To give a receptionist a key per slot, add BLF keys with the slot numbers to the phone's line keys: on its template under its brand in the Provisioning menu, or for one phone in the **Line keys** card of the device's page. The key lights while a call waits in that slot, and pressing it picks the call up.

## When it does not work

- **"Number in use" when creating the lot**: one of the numbers is already used. Choose another range.
- **The transfer to the park extension fails**: the lot is disabled or the change has not been deployed.
- **The parked call disappears**: it timed out, rang the parker, then went to the lot's destination. Check the destination, or make the timeout longer.
- **Deleting a lot**: its numbers become free again, and the lot leaves the phone system at the next deployment.
