---
title: Deploy changes to the phone system
summary: Send saved changes to the telephony engine, now or when calls have ended, and roll back to an earlier configuration.
audience: admin
section: Maintenance
order: 30
reviewed: 0.27.63
pages:
  - /system/telephony/
covers:
  - frontend/src/app/(app)/system/telephony/*
  - frontend/src/components/shell/ApplyChanges.tsx
  - frontend/src/hooks/useEngineStatus.ts*
  - backend/veyra/api/v1/telephony.py
  - backend/veyra/configmgmt/service.py
---

When you save a change that affects calls (a new extension, a ring group, a route), it is stored in Veyra's database but the telephony engine (Asterisk) does not use it yet. You **deploy** it when you are ready. That way you can make several changes and send them together.

## The Deploy changes button

While saved changes wait, the top bar shows a red **Deploy changes** button and a **Review** link.

- **Deploy changes** deploys now.
- The arrow beside it opens two choices:
  - **Deploy now:** reloads only the parts of the engine that changed. Calls in progress are not interrupted.
  - **Deploy when no calls are active:** waits until no call is up, for up to 30 minutes, then deploys anyway. Use it for changes to the SIP transports (ports, TLS), which phones notice.

While it runs the top bar shows **Deploying #n**, or **Waiting for n calls to end (revision #n)**. When it is done you see *Revision #n deployed. Phones will pick up the change.* If nothing actually changed, you see *Nothing to apply*.

If your role cannot deploy, the top bar shows **Changes pending deployment** instead; ask someone who can.

The button is greyed out when the telephony engine is not running.

## Review before deploying

**Review** opens [System → Telephony Engine](app:/system/telephony/). The **Configuration** card shows the **Deployed revision**, a deployment **In progress**, and whether there are **Pending changes**.

**Generate configuration** builds a new *revision* from the database without deploying it, so you can see exactly what would change. Each revision is listed under **Revisions**. Choose **View** to open one:

- the changed files with the lines added and removed (files with passwords show *contains credentials; diff hidden*),
- **All files in this revision**,
- **Deploy** to send it to the engine now, **When no calls are active** to wait until no call is up (for up to 30 minutes) and then send it, or **Discard** to throw it away.

File contents are shown to platform administrators only.

## What deploying does

Veyra checks the generated configuration first. A revision with problems shows **Failed** and is never deployed. When a deployment fails part-way, Veyra puts the previous files back and reloads them, so the engine keeps running the last good configuration. The revision shows **Failed** with the reason.

## Roll back

Every deployed revision is kept. To go back to an earlier configuration:

1. On [System → Telephony Engine](app:/system/telephony/), choose **View** on the older revision (it shows **Superseded**).
2. Choose **Roll back to this revision**. Or choose **When no calls are active** to roll back once the calls have ended.

The newer revision is marked **Rolled back**. The database is not changed, so the top bar shows **Deploy changes** again until you fix or undo the change in Veyra; deploying then sends the database's current state.

## Revision states

| State | Meaning |
|---|---|
| **Ready to deploy** | Generated and checked; not sent yet |
| **Deploying…** | Being written and loaded |
| **Deployed** | What the engine runs now |
| **Superseded** | Ran earlier; a later revision replaced it |
| **Rolled back** | Replaced by deploying an older one |
| **Failed** | Did not pass the checks, or could not be loaded |

## SIP and media settings

The **SIP and media settings** card on the same page holds the ports and addresses phones and trunks use: the UDP, TCP and TLS ports, the **TLS certificate**, the **RTP port range**, the **External signaling address** and **External media address** for a server behind NAT, the **Local networks**, the **Default language** and the **Codecs**. Saved settings apply at the next deployment; use **Deploy when no calls are active** for them.

## From the server console

- `sudo veyra config status` shows the engine and recent revisions.
- `sudo veyra config generate --deploy` generates and deploys.
- `sudo veyra config deploy <number>` deploys the revision with that number (such as `42`), which is how you roll back from the console. Add `--when-idle` to wait for calls to end.

## When it does not work

- **The engine is not running:** see [Health, alerts and diagnostics](guide:health-alerts-diagnostics).
- **Installation key missing:** the page says so. Revisions with SIP passwords cannot be made without it. Run `sudo veyra installation-key check` on the server, and restore the key from a backup if it is gone.
- **"The deployer has not reported a result yet":** run `journalctl -u veyra-deployer` on the server.

## Custom dialplan

Platform administrators can add their own Asterisk contexts under **System → Telephony Engine → Custom dialplan**, for something Veyra has no feature for. Contexts must be named `[custom-…]`. Commands that reach the server's shell or files are refused when you save. Saving does not change calls: deploy the changes as usual.

To send calls there, choose **Custom dialplan** as the destination of an inbound route, a menu key or anywhere else a call can be sent. Calls start at the context's `s` extension, so only contexts that have one are listed. Only platform administrators can choose it. A context in use cannot be removed until nothing sends calls to it.

> **Warning:** this is code that runs on the server, and it can dial out past classes of service and outbound routes. Only paste dialplan you understand.
