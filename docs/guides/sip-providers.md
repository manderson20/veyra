---
title: Choose a SIP trunk provider
summary: Phone service providers (SIP trunk carriers) known to work with Veyra, with how each connects and what each offers for 911.
audience: admin
section: Calls and call flows
order: 9
reviewed: 0.27.86
covers:
  - frontend/src/components/routing/TrunkFields.tsx
  - backend/veyra/api/v1/trunks.py
  - backend/veyra/telephony/routing.py
---

Veyra needs a phone service provider to reach the outside world. It connects to one with a standard **SIP trunk**, so any provider that offers SIP trunking to your own phone system should work. This guide lists providers that are known to work with Asterisk, the phone engine inside Veyra, and what to know about each one before you sign up.

When you have chosen a provider, [Connect a SIP trunk](guide:connect-a-sip-trunk) has the steps to set it up in Veyra.

> **Important:** Check that a provider serves **your area** before you commit. Many providers only offer phone numbers in some rate centers, cannot port numbers from every local phone company, or provide 911 only in some countries or regions. The details on this page were checked on 7 November 2026 from each provider's public documentation, and providers change their plans.

Before you sign a contract or start a number port, ask the provider to confirm, in writing, for each of your buildings:

- **Phone numbers:** they can give you local numbers in your area code and rate center.
- **Porting:** they can port your existing numbers from your current phone company.
- **911:** they deliver E911 with your street address (and room or floor, where needed) to the 911 center that serves that building.

## What to look for

- **911 (E911).** The provider must send 911 calls to the right 911 center with the caller's address. US law (Kari's Law and RAY BAUM'S Act) requires direct 911 dialling and a *dispatchable location* for multi-line phone systems. Look for a provider that lets you register an address per phone number, and that supports **933** test calls. See [Emergency calling](guide:emergency-calling).
- **How it connects.** Veyra supports both ways (see [Connect a SIP trunk](guide:connect-a-sip-trunk)):
  - **Registration:** Veyra signs in with a user name and password. Works without a static IP address.
  - **IP authentication:** the provider trusts your server's public IP address. Needs a static public IP address.
- **Number porting** and **coverage** in your area, as above.
- **Channels:** how many calls can be up at once, and the price per channel or per minute.
- **Fax:** whether they support T.38, if you still use fax machines.

## Not a SIP trunk: Google Voice

**Google Voice cannot be Veyra's phone service.** Google Voice (including Google Workspace) is a cloud phone system of its own, not a carrier, and Google does not offer a SIP trunk to other phone systems.

- Google Voice **SIP Link** works the other way round: your own carrier connects to Google through a certified session border controller, and Google handles the calls. It does not give Veyra a trunk.
- Older ways of connecting Asterisk to Google Voice (GVSIP, OBiTALK) are against Google's terms or discontinued, and are not suitable for an organization's phones.

Pick one of the providers below instead.

## Providers at a glance

| Provider | Connects by | 911 | Coverage | Good fit for |
|---|---|---|---|---|
| Telnyx | Registration or IP | E911 per number, 933 test | Numbers in many countries; 933 testing in US and Canada | Self-service, any size |
| Twilio Elastic SIP Trunking | IP only (no registration) | Emergency address per number, 933 test | Numbers in 100+ countries; emergency calling in US, Canada, UK, Australia, Ireland, France, Germany, Austria | Self-service, any size |
| Bandwidth | IP | 911 Access, dynamic location routing | US and Canada | Larger sites, contracts |
| Flowroute (BCM One) | Registration or IP | E911 per number | Mainly US | Self-service, smaller sites |
| VoIP.ms | Registration or IP | E911 per number (monthly fee) | US and Canada | Small sites, low cost |
| Skyetel | IP (registration with limits) | E911 per number, 933 test | US | Self-service, any size |
| Your local phone company or a large carrier | Usually IP, often over a dedicated circuit | Included, through their own 911 service | Their own service area only | When you already have a contract |

## Telnyx

- **Connects by:** a *Credentials* connection (registration) or an *IP* connection. Registration is the simplest: **Host** `sip.telnyx.com`, **Port** 5060.
- **911:** enable emergency services on each number and save its address in the Telnyx portal. 933 test calls are supported in the US and Canada. Telnyx charges a fee when a number without a registered address calls 911, so register every number you send as an emergency caller ID.
- **Coverage:** numbers in many countries; check local numbers and porting for your area before ordering.
- **In Veyra:**
  - Telnyx expects numbers in `+E.164` form (`+1` and ten digits). On your outbound routes, use **Prepend** `+1` for ten-digit dialling.
  - Send caller ID in `+1` form too. The emergency caller ID must be a Telnyx number with 911 enabled.

From Telnyx: [Asterisk setup guide](https://developers.telnyx.com/docs/voice/sip-trunking/asterisk)

## Twilio Elastic SIP Trunking

- **Connects by:** **IP authentication only.** Twilio does not accept registration: in Veyra choose **IP authentication**.
  - **Host:** your trunk's *Termination SIP URI*, such as `yourname.pstn.twilio.com`.
  - In Twilio, add your server's public IP address to the trunk's **IP Access Control List**.
  - **Match addresses:** Twilio sends calls from a published list of signalling addresses. Copy them from Twilio's documentation into **Match addresses**.
  - In Twilio, set the *Origination SIP URI* to your server's public address, so incoming calls reach Veyra.
- **911:** add an emergency address to each number on the trunk's **Numbers** tab. 933 test calls are supported in the US and Canada. The caller ID on a 911 call must be a Twilio number on that trunk with an emergency address.
- **Coverage:** numbers in more than 100 countries; emergency calling in the US, Canada, the UK, Australia, Ireland, France, Germany and Austria only.
- **In Veyra:**
  - Use the IP Access Control List, not a Twilio *credential list*. Veyra does not yet send a password on outgoing calls of an IP-authentication trunk, so a credential list would make Twilio refuse every outgoing call.
  - Twilio expects numbers in `+E.164` form: use **Prepend** `+1` for ten-digit dialling, and `+1` caller IDs.
  - Caller ID must be a Twilio number or a number you verified with Twilio.

From Twilio: [Elastic SIP Trunking documentation](https://www.twilio.com/docs/sip-trunking)

## Bandwidth

- **Connects by:** IP authentication. Bandwidth owns its own US network and usually works with larger customers under contract, directly or through a partner.
- **911:** Bandwidth's 911 Access service, with dynamic location routing for sending a caller's location on each call.
- **Coverage:** US and Canada.
- **In Veyra:** Bandwidth tells you which addresses to send calls to and which addresses calls come from: put those in **Host** and **Match addresses**. Ask whether they want numbers with or without `+1`.

From Bandwidth: [PBX integration guide](https://www.bandwidth.com/support/en/articles/12822928-pbx-integration-guide)

## Flowroute (BCM One)

- **Connects by:** registration (user name and password) or IP authentication. **Host** `sip.flowroute.com`, or one of their regional servers. UDP or TCP.
- **911:** register an address for each number in the Flowroute portal.
- **Coverage:** mainly US numbers; check porting and 911 for your area.
- **In Veyra:**
  - **Use registration.** With IP authentication, Flowroute needs your account's 8-digit tech prefix and a `*` in front of every number you dial (for example `12345678*+15735550100`). Veyra's **Prepend** accepts only digits and a leading `+`, so it cannot add that prefix today.
  - Flowroute expects every number in `+E.164` form, so use **Prepend** `+1`.

From Flowroute: [technical specifications](https://support.bcmone.com/docs/flowroute-service-guide-technical-specifications)

## VoIP.ms

- **Connects by:** registration with your main account or a *sub account* (recommended: one sub account for Veyra), or IP authentication with a static IP address. Pick the server closest to you, such as `chicago.voip.ms`.
- **911:** e911 is added per number for a small monthly fee, in the US and Canada. Ask whether 933 test calls are available for your numbers.
- **Coverage:** US and Canada numbers.
- **In Veyra:**
  - With a sub account, the **User name** is the sub account's full name, such as `123456_veyra`.
  - Point each number (DID) at the same server and sub account that Veyra registers to.
  - VoIP.ms limits how many failed sign-ins it allows from an address. If the password is wrong, fix it quickly, or VoIP.ms may block your server for a while.

From VoIP.ms: [Asterisk PJSIP guide](https://wiki.voip.ms/article/Asterisk_%28PJSIP%29)

## Skyetel

- **Connects by:** IP authentication (Skyetel's preferred method) through an *endpoint group* with your server's address. Registration is possible but limited: UDP on port 5060 only, at most 100 calls at once per region, and one call per second.
- **911:** enable E911 on each number in the Skyetel portal. 933 test calls are supported. The caller ID on a 911 call must be the 11-digit number (`1` and ten digits) that has E911 enabled.
- **Coverage:** US numbers.
- **In Veyra:**
  - With IP authentication, Skyetel sends calls from several regions. Copy every address Skyetel lists into **Match addresses**.
  - Send emergency caller IDs as `1` and ten digits, without `+`.

From Skyetel: [IP authentication with endpoint groups](https://support.skyetel.com/hc/en-us/articles/360040710674-Endpoint-Groups)

## Local phone companies and large carriers

Your local phone company, cable company or a national carrier (for example AT&T, Lumen, Verizon, Comcast Business or Spectrum) may sell SIP trunks, often on the same circuit as your internet service.

- **Connects by:** usually IP authentication, sometimes on a private circuit with their own equipment at your site.
- **911:** included, through the carrier's own 911 service. Ask how addresses are registered for each building.
- **Coverage:** only their own service area, which is why they are worth asking first in rural areas.
- **In Veyra:** these carriers often test against a list of "certified" phone systems and may not list Veyra or Asterisk. Standard SIP still works in most cases, but ask for their SIP interface specifications (the addresses, number format and codecs they expect), and plan a test call before you port numbers.

## Before you port your numbers

1. Set the trunk up with one new or temporary number first.
2. Test incoming and outgoing calls, caller ID, voicemail menus (DTMF) and, if you use them, fax machines.
3. Register the address of every building with the provider's 911 service and make a **933** test call from each site (see [Emergency calling](guide:emergency-calling)).
4. Only then start the port of your existing numbers, and keep the old service until the port is complete.
