---
title: Connect a SIP trunk
summary: Connect Veyra to your phone carrier so calls can reach and leave the building.
audience: admin
section: Calls and call flows
order: 10
reviewed: 0.27.44
pages:
  - /trunks/
  - /trunks/view/
covers:
  - frontend/src/app/(app)/trunks/*
  - frontend/src/app/(app)/trunks/view/*
  - frontend/src/components/routing/TrunkFields.tsx
  - frontend/src/lib/routing.ts
  - backend/veyra/api/v1/trunks.py
---

A **SIP trunk** is the connection between Veyra and your phone carrier (for example a SIP provider or your phone company's SIP service). Incoming calls arrive on a trunk, and outgoing calls leave through one. Veyra can have several trunks, for example a main carrier and a backup.

A trunk on its own does nothing with calls. After you add it:

- [Route incoming calls](guide:route-incoming-calls) tells Veyra where each of your phone numbers rings.
- [Route outgoing calls](guide:route-outgoing-calls) tells Veyra which dialled numbers go out through which trunk.

Trunks are set up at [Telephony → SIP Trunks](app:/trunks/).

## Before you start

- Only platform administrators can add or change trunks. Organization administrators can see the list so they can pick a trunk on an inbound route.
- Ask the carrier which of the two ways of connecting they use, and for the details below.

| Ask the carrier for | Used for |
|---|---|
| The SIP server's host name or IP address, and the port (usually 5060) | **Host** and **Port** |
| UDP, TCP or TLS | **Transport** |
| Whether they use *registration* or *IP authentication* | **Authentication** |
| For registration: the user name and password | **User name**, **Password** |
| For IP authentication: the addresses their calls come from | **Match addresses** |
| Which of your numbers you may send as caller ID | **Default caller ID** |
| How many calls at once your plan allows | **Maximum channels** |
| Whether they support T.38 fax | **Fax over T.38** |

With IP authentication, the carrier also needs to know **your** public IP address, so they accept calls from it.

## Registration or IP authentication

- **Registration:** Veyra signs in to the carrier with a user name and password, much like a desk phone signs in to Veyra. Common with smaller SIP providers. Both the user name and password are required.
- **IP authentication:** the carrier trusts calls coming from your server's address, and there is no sign-in. Veyra recognises incoming calls from the carrier by the address they come from. Common with larger carriers and dedicated circuits.

## 1. Create the trunk

1. Choose **New trunk**.
2. Fill in the essentials:
   - **Name:** anything that helps you recognise it, such as *Carrier A*.
   - **Authentication:** **Registration** or **IP authentication**.
   - **Host**, **Port** and **Transport**.
   - For registration: **User name** and **Password**.
   - For IP authentication: **Match addresses**, one address or network (such as `198.51.100.0/24`) per line. Leave it empty if calls come from the **Host** itself.
   - **Default caller ID:** the number sent on outgoing calls when neither the route nor the extension sets one. Digits only, with an optional leading `+`.
3. Choose **Create trunk**. Veyra opens the trunk's page.

The password is stored encrypted and is never shown again. To change it later, type a new one in **Set new password**; leave it empty to keep the stored one.

## 2. Check the other settings

The trunk's page shows every setting, in sections. Most can stay as they are.

**Connection**
- **Enabled:** a disabled trunk is kept but left out of the phone system. Routes that use it skip it and try their next trunk.

**Authentication**
- **Authentication user name:** only when the carrier gives you a sign-in name that differs from the user name.
- In IP mode a password is optional, for carriers that still ask for one on outgoing calls. **Clear the stored password** removes it.

**Identification**
- **Match addresses:** in registration mode these are optional extra addresses whose calls are accepted as this trunk.

**Calling**
- **Codecs:** keep **Installation default** (the list under [System → Telephony Engine](app:/system/telephony/)) unless the carrier asks for something specific. Untick it to choose codecs for this trunk only.
- **Maximum channels:** how many calls at once the carrier allows. Empty means unlimited. When it is full, Veyra skips this trunk and tries the route's next one.
- **Channels kept for emergency calls:** of the maximum, how many ordinary calls may not use, so a 911 call can always get out. The default is 1. It only works when **Maximum channels** is set. Emergency calls are never counted against the limit.
- **Caller ID header:** how your number is passed to the carrier: **P-Asserted-Identity** (the default), **Remote-Party-ID**, or **None (From header only)**. Change it only if the carrier asks.
- **DTMF:** how key presses (for menus and voicemail PINs) are sent. Keep **RFC 4733 (RTP events)** unless the carrier says otherwise.
- **Fax over T.38:** offers T.38 fax to this carrier. If the carrier declines, fax is sent as ordinary audio. Turn it on only if the carrier supports T.38.
- **Qualify frequency (seconds):** how often Veyra checks that the carrier answers. `0` turns the check off, and the status then shows **Unknown**.
- Registration timers (registration mode only): **Registration expiry (seconds)** (60–86400), **Retry after a failure (seconds)** (10–3600), **Retry after Forbidden (seconds)** (30–86400, used when the carrier refuses the sign-in) and **Give up after (attempts)** (empty means keep trying).

**Advanced**
- **From user**, **From domain** and **Outbound proxy** are usually left empty. Fill them in only when the carrier's instructions ask for them.

Choose **Save changes** when you are done.

## 3. Deploy

Saving a trunk changes the phone system's configuration. A **Changes not yet deployed** note appears on the page, and **Deploy changes** appears in the top bar. Choose it to apply the change. Calls in progress are not interrupted.

You can deploy once, after you have also created your inbound and outbound routes.

## 4. Check the status

The **Status** column (and the badge at the top of the trunk's page) refreshes every 15 seconds:

| Status | Meaning |
|---|---|
| **Online** | The carrier answers, and a registration trunk is registered |
| **Registering** | Veyra is signing in to the carrier |
| **Registration rejected** | The carrier refused the sign-in: check the user name, password and host |
| **Not registered** | The registration has stopped |
| **Offline** | The carrier does not answer Veyra's checks |
| **Unknown** | The trunk has not been deployed yet, the check is off, or the phone system does not report status right now |
| **Disabled** | The trunk is turned off |

A registration trunk with no stored password shows a **No password** warning.

## If it does not work

- **Registration rejected:** re-enter the password in **Set new password**, check **User name** and **Authentication user name**, save and deploy.
- **Offline:** check the **Host**, **Port** and **Transport**, and that your firewall allows SIP to and from the carrier.
- **Incoming calls are not answered** on an IP trunk: the call may come from an address that is not in **Match addresses**. Ask the carrier for all the addresses they send calls from.
- **Calls connect but there is no audio, or audio in one direction only:** this is usually a firewall or NAT problem, not a trunk setting.
- **Menu choices or PINs are not recognised:** try another **DTMF** setting.

## Deleting a trunk

**Delete** asks you to type the trunk's name. A trunk used by any inbound or outbound route cannot be deleted; Veyra lists the routes to change first. Deploy afterwards to remove it from the phone system.
