---
title: Integrations: tokens and webhooks
summary: Let other systems use Veyra with their own limited tokens, and tell other systems about calls, voicemail, pages and alerts with signed webhooks.
audience: admin
section: Maintenance
order: 80
reviewed: 0.27.44
pages:
  - /system/integrations/
covers:
  - frontend/src/app/(app)/system/integrations/*
  - frontend/src/components/integrations/IntegrationDialogs.tsx
  - backend/veyra/api/v1/integrations.py
  - backend/veyra/api/v1/webhooks.py
  - backend/veyra/integrations/tokens.py
  - backend/veyra/integrations/webhooks.py
---

[System → Integrations](app:/system/integrations/) connects Veyra to the systems around it, in two directions:

- **Tokens** for systems that call Veyra: a door controller that starts a lockdown page, a script that downloads the call history.
- **Webhooks** for systems Veyra tells about events: a screen in the front office that shows who is calling, a ticket system that hears about alerts.

For "when this happens, do that" inside Veyra itself, without writing code, see [Automation rules](guide:automation).

## Tokens

### Create a token

1. On the **Tokens** tab, choose **New token**.
2. Choose the **Organization** it belongs to. A token belongs to the organization, not to a person, so it keeps working when people leave.
3. Give it a **Name**, such as *Door controller, main entrance*.
4. Under **Allowed to**, tick only what it needs:

   | Allowed to | Code |
   |---|---|
   | Start pages | `paging.send` |
   | Ring bell schedules now | `bells.write` |
   | See active calls | `calls.read` |
   | Place click-to-dial calls | `calls.originate` |
   | Hang up calls in progress | `calls.hangup` |
   | Start and stop recording calls in progress | `calls.record` |
   | Read the call history | `calls.history.read` |
   | Export the call history as CSV | `calls.history.export` |
   | Read the directory | `directory.read` |
   | Run saved reports | `reports.read` |

   Tokens can never change Veyra's settings.
5. Optionally limit it with **Only from these addresses (optional)** (addresses or networks; empty allows any), and set when it **Expires (optional)**.
6. Choose **Create token** and **copy the token now**: Veyra keeps only a fingerprint and cannot show it again.

The other system sends the token as a bearer token. The window shows an example that starts a page:

```
curl -X POST https://pbx.example.org/api/v1/pages/<page id>/send \
     -H "Authorization: Bearer <token>"
```

### Look after tokens

The list shows what each token is **Allowed to** do, where it may connect **From**, when it was **Last used** and from which address, and when it **Expires**.

- **Edit** changes its name, permissions, addresses or expiry.
- **New token** replaces the token. The old one stops working at once, so update the other system straight away.
- The bin icon **revokes** it. It stops working at once.

> **Tip:** Make one token per system, so you can revoke one without breaking the others.

## Webhooks

### Add a webhook

1. On the **Webhooks** tab, choose **New webhook**.
2. Give it a **Name** and the **Address** that should receive the messages, such as `https://hooks.example.org/veyra`. Addresses on the Veyra server itself are refused; addresses on your own network are fine.
3. For a device on your network that has no HTTPS, tick **Allow unencrypted HTTP**. The message is still signed, but readable on the way.
4. Tick the events:
   - **Calls:** an extension starts ringing, an extension answers a call, a finished call is in the call history
   - **Voicemail:** a new voicemail message is left
   - **Paging:** a page starts, a bell schedule rings
   - **Monitoring:** a monitoring alert is raised or resolved
   - **Phones:** a phone registers or unregisters
   - **System:** a configuration deployment ends

   Events marked **live** (ringing, answered) are sent once only, because a late message would be meaningless. Others are retried.
5. Save, and **copy the signing secret now**. Give it to the receiving system so it can check that messages really come from Veyra.

### Test and check

- **Send test** sends a test message and shows the answer.
- **Deliveries** lists the last 100 messages (kept for 7 days) with their result. **Details** shows the message and the answer; **Redeliver** sends one again.
- The **Status** column shows **OK**, **Failing since …**, **Disabled** or **Turned off**.

A failed delivery is retried after 1 minute, 5 minutes, 30 minutes, 2 hours and 6 hours. A webhook that keeps failing for 3 days is turned off; fix the receiver, then switch **Enabled** on again in its settings.

### Check the signature

Each message carries a `Veyra-Signature` header with a time and an HMAC-SHA256 of the time and the body, made with the webhook's secret. The **Checking the signature** card on the page has a short example in Python. The receiver should refuse messages older than five minutes and ignore a repeated `Veyra-Delivery` id.

**New secret** creates a new signing secret. For a day, messages carry both the old and the new signature, so you have time to update the receiver.
