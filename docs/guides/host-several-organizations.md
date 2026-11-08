---
title: Host several organizations
summary: Run one Veyra server for several districts, towns or clients (an MSP) with their phones, numbers, caller IDs and 911 kept apart.
audience: admin
section: Getting started
order: 75
reviewed: 0.27.87
pages:
  - /organizations/
  - /organizations/setup/
  - /settings/
covers:
  - backend/veyra/core/tenancy.py
  - backend/veyra/core/limits.py
  - backend/veyra/api/v1/limits.py
---

One Veyra server can serve several organizations: a district and a neighboring town, or a managed service provider's (MSP's) clients. Each organization gets its own extensions, phones, voicemail, queues and numbers, and none can reach another's. This guide is the order to set it up in; the details are in the guides it links to.

This is for **platform administrators**. A server with one organization never sees any of it.

## What is shared and what is not

- **Shared by every organization:** SIP trunks marked as shared, outbound routes marked **All organizations**, the numbering plan (length and range), the mail server, firewall, updates, modules and sign-in providers.
- **Each organization's own:** extensions (two organizations can both have 1001), phones and their provisioning credential, voicemail, ring groups, queues, conference rooms, parking, hold music, paging, its **numbers**, its **main number** and its **emergency number**, and optionally a **dedicated trunk** of its own.

## 1. Before you turn it on

Your existing organization needs, on its page under [Directory → Organizations](app:/organizations/):

1. **Numbers:** the carrier numbers that are yours (the **Numbers** card). Veyra fills it from your inbound routes when you turn multi-tenancy on, but check it.
2. **Main number:** the caller ID of outside calls from phones without their own.
3. **Emergency number:** registered with your carrier at your address, presented on 911 calls from phones whose extension and site have none.

Turning multi-tenancy on is refused while any of these is missing.

## 2. Turn on multi-tenancy

Under [System → Settings](app:/settings/) → **Multi-tenancy**, choose **Turn on**. Veyra first proves, with a test copy of everything your organization has, that two organizations cannot reach each other. Nothing changes for your current phones. See [Settings](guide:settings).

## 3. Add each organization

**Organizations → New organization** asks for the name, short name, time zone, its numbers, main number and emergency number, and then opens **Set up**: trunk, first administrator, phones, emergency, limits and a final **Check**. See [Organizations and sites](guide:organizations-and-sites).

Tips:

- A number can belong to only one organization. An inbound route can use only its organization's numbers; the `any` catch-all is only for a trunk dedicated to one organization.
- An organization's administrators can give an extension only one of the organization's numbers as caller ID, or a number on its **Outbound caller ID allow list**.
- Every site should have its own ELIN; until then its 911 calls present the organization's emergency number. See [Emergency calling (911)](guide:emergency-calling).

## 4. Who applies changes

By default each organization's administrators **deploy their own changes**: only when the server has no active calls, at most every five minutes, and audited. In System → Settings you can make them **Only request a deployment** instead. If one organization's data cannot be generated, its newer changes are held back and everyone else's still deploy. See [Deploy changes](guide:deploy-changes).

## 5. Limits and usage (optional)

- **Limits** on each organization's page: outside calls at once, extensions and phones. 911 calls are never counted or refused.
- **Usage** under [Telephony → Reports](app:/reports/): each organization's outside calls and minutes per trunk and month, billable minutes (each call rounded up to a whole minute), internal and emergency calls apart, and a CSV for billing. See [Call history and reports](guide:call-history-and-reports).

## 6. People and access

- A customer's own IT person: **Organization Administrator** in their organization only.
- MSP staff: **Technician** (or a custom role) in the clients they look after, ticked in one save on the user's **Assign role**.
- The MSP owner: **Platform Administrator**.

See [Users and roles](guide:users-and-roles). Anyone who can see more than one organization picks the one they work in from the switcher at the top of the page; each browser tab keeps its own.

## If something doesn't work

- **"Multi-tenancy is off" when adding an organization:** turn it on first (step 2).
- **Turning it on is refused:** the message lists what is missing, usually a main number or emergency number, or an isolation problem to fix first.
- **"… is already assigned to …":** that number belongs to another organization; withdraw it there first.
- **A user sees "You have no access to that organization":** their role there was removed; the page returns to the organizations they still have.
