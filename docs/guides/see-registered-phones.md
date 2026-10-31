---
title: See which phones are registered
summary: Check which phones are connected to Veyra right now, where they connect from, and whether the carriers' trunks are registered.
audience: admin
section: Phones and devices
order: 90
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /registrations/
covers:
  - frontend/src/app/(app)/registrations/*
  - backend/veyra/api/v1/registrations.py
---

A phone is **registered** when it has signed in to Veyra with its extension's SIP user name and password. Only a registered phone rings and can make calls. [Telephony → Registrations](app:/registrations/) lists every phone registered right now. The page refreshes itself every 10 seconds; **Refresh** updates it at once.

## The phones table

| Column | What it shows |
|---|---|
| **Extension** | The extension number and name. If the extension allows only a set number of phones, also how many of them are registered, for example *1 of 2 phones registered*. |
| **Registers from** | The network address the registration arrived from. **Behind NAT** means the phone is behind a router that changes its address, for example a phone at home. |
| **Phone's own address** | The address the phone says it has, and the transport (UDP, TCP or TLS). It differs from **Registers from** when the phone is behind NAT. |
| **Phone reports** | What the phone says it is: usually the brand, model and firmware version. |
| **Reachability** | **Reachable** with the round-trip time in milliseconds, **Unreachable** when the phone stopped answering Veyra's checks, or **Not checked**. |
| **Expires** | When the registration runs out. The phone renews it well before then. |

Search by extension, address or phone model. With more than one organization, you can show one at a time.

The blue box *… enabled extensions have no registered phone* counts the extensions nobody is signed in to. They are marked *Not registered* on the Extensions page.

## The trunks table

If the server has SIP trunks to carriers, the **Trunks** card shows Veyra's own registration to each one:

- **Registration:** **Registered**, **Reachable**, **Registering**, **Not registered**, **Registration rejected**, **Unreachable** or **Unknown**.
- **Engine says:** the raw status from the telephony engine.
- **Host:** whether the carrier's server answers (**Answers** or **No answer**).

## If something doesn't work

- **A phone is missing from the list.**
  1. Open the phone under [Provisioning → Extension Mapping](app:/devices/). If its status is **Never provisioned** or **Error**, it never got its configuration: see [Connect phones to Veyra](guide:connect-phones-to-veyra).
  2. Check that the phone has an **Extension (line 1)** and that the extension is enabled.
  3. If more phones use the extension than it allows, the phone that registers last replaces the earliest one, so two phones on one extension keep pushing each other out.
- **Unreachable.** The phone registered but no longer answers. It may have been unplugged, or a router between them is dropping traffic. Phones behind NAT are the usual case; check the router at that location.
- **"Registration details are not available".** The telephony engine is not running or cannot report addresses. The message says why. Look at the system health pages.
- **A trunk shows "Registration rejected".** The carrier refused the user name or password. Check the trunk's settings with the carrier.
