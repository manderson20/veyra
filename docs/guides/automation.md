---
title: Automation rules
summary: Make Veyra react by itself, such as emailing the office about a missed call or starting a page when a door controller calls in.
audience: admin
section: Maintenance
order: 85
reviewed: 0.27.44
pages:
  - /system/automation/
covers:
  - frontend/src/app/(app)/system/automation/*
  - backend/veyra/api/v1/automation.py
  - backend/veyra/integrations/automation.py
---

[System → Automation](app:/system/automation/) holds rules of the form *when something happens, if these conditions hold, do this*. No programming is needed. For example:

- A missed call to the office's number emails the office staff.
- A door controller held open calls a secret address, and Veyra starts a page.
- A monitoring alert emails the on-call technician.

Rules listen to the same events as [webhooks](guide:integrations), or to a request to their own address.

## Create a rule

1. Choose **New rule**.
2. Give it a **Name**, such as *Missed calls to the office*. If you have several organizations, choose the **Organization**.
3. **When:** choose what the rule listens to:
   - **Calls:** an extension starts ringing; an extension answers a call; a finished call is in the call history.
   - **Voicemail:** a new voicemail message is left.
   - **Paging:** a page starts; a bell schedule rings.
   - **Monitoring:** an alert is raised or resolved.
   - **Phones:** a phone registers or unregisters.
   - **System:** a configuration deployment ends.
   - **A device calls the rule's address:** the rule gets its own secret web address (see below).

   The trigger cannot be changed later; create another rule instead.
4. **Only if:** optionally **Add a condition**: a **Field** of the event, **is** or **contains**, and a **Value**. The page lists the fields of the chosen event. For example, for a finished call: `outcome` is `missed`, and `to.number` is `5550100`. All conditions must hold; text is compared without regard to capitals.
5. **Then:** at least one of:
   - **Email:** the addresses to tell what happened. Email must be set up under **System → Settings → Email delivery**.
   - **Start a page:** a page, and the **Recording** to play (or **The page's own recording**).
6. **Quiet time (seconds)** (default 60): after firing, the rule waits this long before it can fire again, so a burst of events does not page ten times.
7. Leave **Enabled** on, and choose **Create rule**.

## Rules a device can call

With **A device calls the rule's address**, Veyra shows the rule's address once after you create it, in a box at the top of the page. Copy it into the device (a door controller, a panic button, a script). The device sends a POST request to it; an optional JSON body becomes fields the conditions can test.

Anyone who knows the address can fire the rule, so treat it like a password. **New address** in the rule's window replaces it; the old one stops working.

## Check that it works

- **Test now** in the rule's window runs the actions within a few seconds.
- **Runs** in the list shows each time the rule fired, with the result of each action.
- The list shows each rule's **State** (**On**, **Off** or **Last run failed** with the reason) and how often it has **Fired**.

**Delete** in the rule's window removes it; for a device rule, its address stops working.
