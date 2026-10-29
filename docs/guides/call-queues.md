---
title: Set up a call queue
summary: Let callers wait in line with music and announcements until an agent is free, and let agents log in and out.
audience: admin
section: Calls and call flows
order: 20
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /queues/
  - /queues/view/
covers:
  - frontend/src/app/(app)/queues/*
  - frontend/src/components/groups/QueueFields.tsx
  - frontend/src/components/groups/MemberListEditor.tsx
  - backend/veyra/api/v1/queues.py
  - backend/veyra/telephony/agents.py
---

A call queue holds callers in line until someone is free to answer. Callers hear music and, if you like, announcements and their place in line. The people who answer are called *agents*. Use a queue for a help desk, an attendance line or any number where more calls arrive than people can take at once.

For a small team that answers within a few rings, a ring group is simpler: see [Set up a ring group](guide:ring-groups).

## Before you start

- You need permission to change ring groups and queues. Organization and site administrators have it by default.
- Every agent needs an extension.
- If callers should hear a greeting or a "please hold" message, add the recordings to the audio library first: see [Manage audio and hold music](guide:audio-and-hold-music).

## 1. Create the queue

1. Open [Telephony → Call Queues](app:/queues/) and choose **New queue**.
2. If you manage several organizations, choose the **Organization**.
3. Enter a **Name**, for example *Help desk*, and a **Number** from the numbering plan. The field suggests the next free number.
4. Choose **Create queue**. Veyra opens the queue's page.

## 2. Add the agents

Under **Agents**, choose an extension and click **Add**. A queue has at most 64 agents. For each agent:

- **Penalty** (the number box, 0 to 9): agents with a higher penalty ring only when every agent with a lower one is busy or absent. Leave everyone at 0 to treat them equally, or give back-up staff a 1.
- **Logs in**: when ticked, the agent is a *dynamic* agent and takes queue calls only while logged in. When not ticked, the agent is always in the queue.

## 3. Choose how calls are handed out

- **Strategy**:

| Strategy | Who rings |
|---|---|
| **Ring all available agents** | Every free agent at once. |
| **Round robin (continues where it left off)** | The next agent in turn. |
| **Agent idle the longest** | The agent who has gone longest without a queue call. |
| **Agent with the fewest completed calls** | Spreads the calls evenly. |
| **Random agent** | Any free agent. |
| **Agents in the listed order** | Always the first free agent in the list. Use the arrows to set the order. |

- **Agent ring time (seconds)**: 5 to 60, how long each attempt rings an agent.
- **Pause between attempts (seconds)**: 1 to 30.
- **Agent rest after a call (seconds)**: 0 to 600, time after a call before the agent gets the next one (for notes).

## 4. Decide what callers hear and how long they wait

- **Callers hear**: **Music on hold** (with a **Hold music set**, or the built-in music), or **Ringing tone**.
- **Announcement on joining**: played once before the caller starts waiting.
- **Announcement while waiting** and **Repeat every (seconds)** (15 to 600): for example "All our staff are busy; your call is important to us".
- **Announce the caller's position in line**, every 15 to 600 seconds.
- **Maximum wait (seconds)**: 0 for no limit, otherwise 30 to 3600. After that the caller goes to the destination below.
- **Maximum callers waiting**: 0 for no limit, up to 100. A caller beyond the limit goes straight to the destination below.
- **Let callers wait when no agent is available**: off, a caller goes straight to the destination below when no agent is logged in or free.
- **Break-out menu**: an IVR menu whose keys callers may press while they wait, for example 1 to leave a voicemail. Tell callers about it in the announcement while waiting. The menu must be enabled. See [Build a phone menu](guide:phone-menus).
- **When the caller is not connected**: where the call goes after the maximum wait, when the queue is full, or when nobody can take it. The same destinations as everywhere else, or **Hang up**.

## 5. Save and deploy

1. Choose **Save changes**.
2. Choose **Deploy changes** in the top bar when the *Changes not yet deployed* note appears.
3. Point an inbound route or a menu key at the queue, or dial its number.

The **As deployed** card sums up what the queue does once deployed.

## Agents logging in and out

Dynamic agents (those with **Logs in** ticked) are only in the queue while logged in. Changing their state takes effect at once and needs no deployment.

**From the phone** (default codes; your organization may have changed them under [Feature Codes](app:/feature-codes/)):

| Dial | What it does |
|---|---|
| `*45` | Log in or out of every queue this phone may join |
| `*45` and the queue number | Log in or out of that queue only |
| `*46` | Pause or resume in the queues (stay logged in, take no calls for a while) |
| `*46` and the queue number | Pause or resume in that queue only |
| `*47` and the queue number | Hear how many callers are waiting |

**From the web**: the **Agents** card on the queue's page lists the dynamic agents as **Logged in**, **Paused** or **Logged out**. Use **Log in** / **Log out** and **Pause** / **Resume** to change an agent, for example when someone forgot to log out before going home. Every change is written to the audit log.

Agents who are always in the queue (**Logs in** not ticked) cannot be logged out or paused.

## See how the queue is doing

[Reports](app:/reports/) shows, for each queue, the callers, how many were answered, how many hung up while waiting, the average wait and the share answered within 20 seconds. See [Call history and reports](guide:call-history-and-reports).

## When it does not work

- **Callers go straight to the failover**: no agent is logged in or free, and **Let callers wait when no agent is available** is off. Or the queue has no agents.
- **An agent never gets calls**: check that they are logged in and not paused (the **Agents** card), that their extension is enabled, and their penalty.
- **The phone says the code is not allowed**: the extension's class of service may not allow that feature code.
- **Nothing changed after saving**: deploy the changes. Only logging in, out and pausing apply without deploying.
