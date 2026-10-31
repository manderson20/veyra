---
title: Provisioning variables
summary: Define a value once, such as each building's all-call paging zone or a time server, and let every phone take the value for its site or profile.
audience: admin
section: Phones and devices
order: 70
reviewed: 0.27.44
checked: 2026-10-29
pages:
  - /provisioning/variables/
covers:
  - frontend/src/app/(app)/provisioning/variables/*
  - backend/veyra/api/v1/provisioning_variables.py
  - backend/veyra/provisioning/variables.py
---

A **provisioning variable** is a named value that phones share. You define it once, and phones use it in their keys and templates. The same name can have a different value per building. That way one template can serve every building: each phone's all-call key pages its own building's zone.

## Where a phone gets the value

A variable can be defined for four scopes:

| Scope | Reaches |
|---|---|
| **Installation** | Every phone on this Veyra server. Only platform administrators can define it. |
| **Organization** | The organization's phones. |
| **Site** | Phones at that site (the phone's own site, or else its profile's site). |
| **Template** | Phones using that template. |

When the same name is defined at several scopes, each phone takes the nearest one: profile first, then site, then organization, then installation. Define a value at the widest scope that shares it, and override it only where it differs.

## Define a variable

1. Open [Provisioning → Variables](app:/provisioning/variables/) and choose **New variable**.
2. Fill in:
   - **Name** (required): starts with a letter; lower-case letters, digits and underscores, up to 40 characters. For example `all_call`. Some names are reserved because templates already use them (for example `timezone`), and Veyra says so.
   - **Defined for:** the scope. For **Site** or **Profile**, also choose which one. With more than one organization, choose the **Organization**.
   - **Value:** up to 1000 characters.
   - **Description:** what the value is for.
   - **Sensitive (shown masked to those who cannot change it):** for passwords.
3. Choose **Create variable**.

A name can be defined only once per scope: one `all_call` for the organization, one for each site, and so on.

To change a value, click the variable in the list, change it and choose **Save**. A sensitive value is not shown again; leave the field empty to keep it, or type a new one.

> **Note:** When you create, change or remove a variable, Veyra asks every phone it reaches to read its configuration again, and tells you how many phones it asked. Phones that are not registered right now get the change at their next daily check.

## Use a variable

- **In a key or zone:** type `$name` as the value. For a paging key, choose **From a variable (per building)…** and type the name. See [Phone keys](guide:phone-keys).
- **In a template:** write `{{ vars.name }}`. See [Customize a provisioning template](guide:customize-provisioning-templates).

The **Use** column of the list shows both forms for each variable.

### Example: one all-call key for every building

1. Create a paging zone for each building's all-call (under Telephony → Paging Zones).
2. Define `all_call` for site *Building A* with the value `building-a-all-call` (the zone's short name), and for site *Building B* with its zone's short name.
3. In the profile, add a key of type **Page a zone**, choose **From a variable (per building)…** and type `$all_call`.

Each phone now pages its own building.

## Built-in values

The **Built-in values** card lists the values every template has without any definition: they come from the phone, its extension and the server (for example the SIP user name, the server address and the time zone). You cannot define variables with these names.

## See what a phone gets

Open the phone under [Provisioning → Extension Mapping](app:/devices/), go to the **Configuration** tab, and look at the **Variables** card. It lists every variable that reaches the phone, its value, and the scope it came from. **Render** shows the files; a variable that a key or template uses but nobody defined is listed under **Missing variables**, and the setting or key is left out.

## Remove a variable

Click the variable, choose **Remove**, then **Yes, remove**. Phones that use the name then take it from a wider scope if there is one.

Veyra refuses to remove it (*Variable in use*) if some phone's keys use `$name` and no other scope would give that phone a value. The message names those phones. Change their keys, or define the value at another scope first.

## If something doesn't work

- **"… is already defined at this scope."** Click the existing variable in the list and change it instead.
- **A phone does not show the new value.** Check its **Variables** card: a nearer scope (its profile, for example) may define the same name. If the value is right there, choose **Reprovision** on the phone's page.
- **The site you need is not in the list.** Sites are created under Directory → Sites.
