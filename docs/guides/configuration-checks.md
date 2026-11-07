---
title: Configuration checks
summary: Veyra checks every phone setting against what the phone's firmware accepts before it saves a change, and you decide what to do when it finds a problem.
audience: admin
section: Phones and devices
order: 75
reviewed: 0.27.87
pages:
  - /provisioning/checks/
covers:
  - frontend/src/app/(app)/provisioning/checks/*
  - frontend/src/components/provisioning/ConfigCheck.tsx
  - frontend/src/lib/configCheck.ts
  - backend/veyra/api/v1/config_checks.py
  - backend/veyra/provisioning/checks.py
  - backend/veyra/provisioning/precheck.py
  - backend/veyra/provisioning/verify.py
  - backend/veyra/provisioning/capabilities.py
---

Phones quietly ignore a setting they don't understand, or refuse a value their firmware doesn't take. Veyra checks first. When you save a template, a Base File Edit, a phone or a variable, Veyra builds the files the phones would download and compares every setting with what that model accepts on its firmware.

Veyra does not run the phone's software. It compares against **vendor data**: lists of the settings each model accepts, written from the vendor's admin guide and release notes. The data can be wrong or incomplete, so the decision is always yours.

## The check window

When you save, a window opens with a progress bar while Veyra checks.

- **No problems found:** the window says how many settings were checked, on which models and firmware. Choose **OK**.
- **Warnings:** the change is saved. The window lists each warning. Choose **OK**.
- **Errors:** nothing is saved yet. The window lists each setting the firmware would refuse.

For each setting the window shows:

- **Filled by:** the Veyra field that puts the value there, such as the extension's name, or *a fixed value* when it comes from the base file or a Base File Edit.
- **Value:** what Veyra would write.
- **Accepts:** what the setting takes, such as `0 UDP, 1 TCP, 2 TLS, 3 DNS-NAPTR`, a range of numbers, or text up to a length.
- **Phones:** the models and the firmware checked.
- **Source:** where the vendor data came from.

A setting that appears for several models is shown once, with every model listed.

Veyra does not check each phone one by one. It checks a template with the values each field could hold: a typical one, the shortest and the longest. An error means the value fails for every phone. A warning such as *With the longest value of the extension's name …* means some phones may refuse it, for example one whose extension has a very long name.

## When a setting is refused

You have two choices:

- **Change the configuration** so the setting is right, and save again.
- **Override and save** if you know the phones take it. Tick every error, write why (at least five characters), and choose **Override and save**. Tick **The checker is wrong** when you believe the vendor data is wrong, so it can be corrected.

An override covers exactly one setting, with that value, on that model and firmware release. If the value, the model or the release changes, Veyra checks it again.

Overriding needs the **provisioning.check.override** permission (Organization Administrators have it). Without it, the window asks you to have an administrator review the settings.

## What "not checked" means

Grey notes in the window are not passes:

- *… settings are not in the vendor data: they were not checked.* Veyra has no data about those settings.
- *… settings are checked against data taken from Veyra's own templates.* Veyra knows the setting exists but has not yet confirmed its values with the vendor's guide.
- *No capability pack covers …* Veyra has no data for this brand or model at all.

Choose **Show these settings** to see which ones.

## Turn checks off or make them advisory

Each level can set its own mode:

| Mode | What happens |
|---|---|
| **Enforce** | Errors stop a save until someone overrides them. This is the default. |
| **Advisory** | Errors and warnings are shown, but nothing is stopped. |
| **Off** | No checks and no window. |

- **The whole installation** and **an organization:** on [Provisioning → Configuration Checks](app:/provisioning/checks/). The installation's mode needs system settings permission.
- **One template:** **Configuration checks** on the template's page. To try phones without checks, make a test template with checks off.

Changing a mode needs the **provisioning.check.mode** permission and is recorded in the audit log. Overrides are kept while checks are off and apply again when you turn them back on.

## See and revoke overrides

[Provisioning → Configuration Checks](app:/provisioning/checks/) lists every override: the setting, the value, the phones, why, who and when. Tick **Checker is wrong** to see the settings people reported. These are the corrections the vendor data needs.

**Revoke** an override when it is no longer right. The next save of that configuration stops at the setting again.

On [Extension Mapping](app:/devices/), a phone's status shows **Check: … errors** when its configuration has open errors, and **Check: overridden** when someone saved past them.

## Phones always get their files

The check never stops a phone from downloading its configuration. A phone that fetches a file with open errors gets it as usual, and the server log notes it.

## If something doesn't work

- **The window says nothing was checked:** the brand or model has no vendor data yet, or the checks are off. See the grey notes.
- **An error you are sure is wrong:** override it with **The checker is wrong** ticked, and tell your Veyra administrator so the data can be corrected.
- **The same setting needs an override for each model:** that is expected. Each model has its own entry, and the window ticks them all for you.
