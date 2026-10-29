---
title: Central management of several servers
summary: Watch several Veyra servers from one console, give them shared policies, and send them update commands.
audience: admin
section: Maintenance
order: 70
reviewed: 0.27.44
pages:
  - /system/central/
  - /system/central/instance/
  - /system/membership/
covers:
  - frontend/src/app/(app)/system/central/*
  - frontend/src/app/(app)/system/central/instance/*
  - frontend/src/app/(app)/system/membership/*
  - frontend/src/components/central/CentralDialogs.tsx
  - frontend/src/lib/central.ts
  - backend/veyra/api/v1/central.py
---

A district or company with several Veyra servers (one per school or site, for example) can watch them all from one place. One Veyra server acts as the **central console**. The others **enroll** with it: they report their health every few minutes and accept the policies and commands you choose.

- The console never connects to the other servers. They check in to it over HTTPS with signed messages, so they can sit behind firewalls.
- Each server keeps working on its own if the console is unreachable.
- Each server decides which kinds of policy it accepts.

Two pages are involved:

- [System → Central console](app:/system/central/) on the console server.
- [System → Central management](app:/system/membership/) on each managed server.

## 1. Turn on the console

On the server that will be the console, open [System → Central console](app:/system/central/) and switch on **Act as a central console**. The card shows its **Address** and **Fingerprint**, and **Minutes without a check-in** after which a server counts as offline.

## 2. Create an enrollment token

1. On the **Enrollment tokens** tab, choose **New token**.
2. Give it a **Label** (such as *High school*; it becomes the server's name on the console) and choose a **Policy**, or leave it on the default policy.
3. Copy the **Console address**, **Token** and **Fingerprint** now: the token is shown once. It works once and expires after a day.

## 3. Enroll the other server

On the server to be managed, open [System → Central management](app:/system/membership/):

1. Under **Enroll with a central console**, enter the **Console address**, **Enrollment token** and **Console fingerprint**. The fingerprint makes sure you are enrolling with your console and not an impostor.
2. Only if this server does not trust the console's certificate (for example, the console uses its own Veyra certificate), paste the console's CA certificate (the text of its `veyra-ca.crt`) under **Certificate authority (optional)**. Not needed when the console has a public certificate.
3. Choose **Enroll**.

The page then shows the **Console**, **What this installation accepts**, the **Policy from the console** with the result of each section, and **Recent activity**. **Check in now** checks in at once.

## Choose what a server accepts

Under **What this installation accepts**, each of **Update policy**, **Firewall allow list**, **Alert recipients**, **Notice banner** and **Commands from the console** can be switched off, keeping it under local control. The console sees what a server refuses.

## Watch the servers

On the console, the **Instances** tab lists every enrolled server with its **Status**, **Last check-in**, **Version** (and any update available), registered **Phones**, **Calls**, open **Alerts** and **Policy**. Click a server to see more:

- **Status**, **Telephony** and **Version** at a glance, and a **Last 30 days** chart of phones, calls and alerts.
- **Open alerts**, firewall state, updates waiting and installed modules.
- **Settings here:** change its **Label** and **Policy**.
- **Commands:** what was sent and the result.

The console's own alerts **Instance not checking in**, **Instance unhealthy** and **Instance update failed** tell you when a server needs attention.

## Policies

On the **Policies** tab, **New policy** (or click one to change it). A policy can set any of these sections; sections you leave off stay under each server's own control:

- **Updates:** turn on **Set the update policy** to set the **Mode**, a maintenance window, and which kinds of update install automatically. See [Updates and maintenance windows](guide:updates). **Update email recipients (optional)** sets who is told about updates.
- **Firewall:** **Add addresses to the allow list**, one address or network per line, such as your district network or monitoring server. These entries are marked as coming from the console and removed again when the policy drops them; entries made locally are never touched.
- **Alerts:** **Set the alert email recipients**.
- **Notice:** **Show a notice to administrators**, a banner on every page of the server, such as *This server is managed by District IT. Call x4000 before changing trunks.*

Tick **Default policy** to give it to servers enrolled with a token that names no policy. A changed policy goes out at each server's next check-in.

## Send commands

On the **Instances** tab, tick servers and choose **Command n selected**, or open one server and choose **Send command**:

- **Check for updates**
- **Download an update** (give the **Version**)
- **Approve an update** (give the **Version**, and **Install** **In the maintenance window** or **Now, when no call is in progress**)
- **Refresh catalogs**

Commands wait for the server's next check-in and expire after a day. Each server carries them out under its own rules.

## Stop managing a server

- On the console, **Revoke** refuses the server's check-ins from then on. The server removes the firewall entries and notice it took from the console; other settings stay. Once revoked, **Remove** deletes its history on the console.
- On the managed server, **Leave** stops checking in and forgets the console. Settings the policy applied stay; firewall entries from the console are removed.

To enroll again, create a new token.

Turning the console off keeps the enrolled servers but refuses their check-ins until it is turned on again.
