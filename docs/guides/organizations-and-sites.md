---
title: Organizations and sites
summary: Set up your organization's defaults, and add its sites, buildings and departments.
audience: admin
section: Getting started
order: 30
reviewed: 0.27.87
checked: 2026-11-08T16:21Z
pages:
  - /organizations/
  - /organizations/view/
  - /organizations/setup/
  - /sites/
covers:
  - frontend/src/app/(app)/organizations/*
  - frontend/src/app/(app)/organizations/view/*
  - frontend/src/app/(app)/organizations/setup/*
  - backend/veyra/api/v1/onboarding.py
  - frontend/src/components/shell/OrgSwitcher.tsx
  - frontend/src/app/(app)/sites/*
  - frontend/src/components/sites/SiteDialog.tsx
  - frontend/src/components/sites/BuildingsDialog.tsx
  - frontend/src/components/organizations/DepartmentsCard.tsx
  - backend/veyra/api/v1/organizations.py
  - backend/veyra/api/v1/sites.py
---

An **organization** is the school district, town or business Veyra serves. The setup wizard creates the first one. Everything else (extensions, users, numbers, voicemail) belongs to an organization.

A **site** is a campus or building of the organization. It holds the address and emergency caller ID for the phones there. A site can have **buildings**, for example *Gym* or *East Wing*. **Departments** group extensions, such as *Front Office* or *Nurses*.

Both pages are under **Directory** in the menu: [Organizations](app:/organizations/) and [Sites](app:/sites/).

## Check your organization's settings

1. Open [Directory → Organizations](app:/organizations/) and choose your organization.
2. In the **Details** card, check or change:
   - **Name** and **Time zone**. The **Short name** cannot be changed.
   - **Intercom:** whether phones answer intercom calls on speaker. This is the default; each extension can override it.
   - **Answer another phone's call:** who may dial `**` and an extension to answer a call ringing there: **Any phone of the organization**, or **Only phones in the same pickup group**.
   - **Callers who ring through Do Not Disturb:** numbers or extensions that ring every phone even when it has Do Not Disturb on, such as the district office. One per line, at most 50.
   - **Main number** (platform administrators): one of the organization's numbers. With several organizations on the server, outside calls from a phone without its own outbound caller ID present it. Every organization needs one before multi-tenancy can be turned on, and it cannot be withdrawn from the **Numbers** card while it is the main number.
   - **Emergency number** (platform administrators): one of the organization's numbers, registered with the carrier at its address. With several organizations on the server, a 911 call from a phone whose extension and site have no emergency caller ID presents it. Every organization needs one before multi-tenancy can be turned on. See [Emergency calling (911)](guide:emergency-calling).
   - **Outbound caller ID allow list:** numbers an extension may send as caller ID besides the organization's own numbers. Changing it also needs the routing permission.
   - **Hold music:** what callers hear on hold.
   - **Fax header** and **Fax station ID:** printed on, and announced with, every fax the organization sends.
   - **Beep when a supervisor listens in:** both sides hear a beep when a supervisor starts to listen, whisper or join. Check your district's policy.
   - **Users may play recordings of their own calls:** off by default. Every listening is audited.
   - **Active:** an inactive organization is kept but cannot be used for new configuration.
3. Choose **Save changes**.

Most of these settings need a deployment: choose **Deploy changes** in the top bar afterwards.

The organization page also has:

- **Information:** the organization ID and when it was created.
- **Phone provisioning:** the enrollment credential new phones use the first time they fetch their configuration. **Create credential** or **Rotate credential**; the password is shown only once.
- **Departments:** choose **Add department**, give it a **Name** and, if you like, a **Site**. You then pick the department on each extension. My Phone layout templates can be assigned by department.

## Add a site

1. Open [Directory → Sites](app:/sites/) and choose **New site**.
2. Enter the **Name**, for example *Main Campus*.
3. **Time zone:** leave it on **The organization's** to use the organization's time zone, or choose one from the list, such as *America/Chicago*.
4. **Emergency caller ID number:** the number registered for this building with your carrier for emergency calls. It is the default for the site's extensions on 911 calls.
5. Fill in the address: **Street**, **City**, **State or region**, **Postal code** and **Country** (two letters, such as *US*).
6. Choose **Create site**.

To change a site, choose its row or **Edit**.

## Add buildings to a site

1. On the [Sites](app:/sites/) page, choose the number in the **Buildings** column of the site.
2. Choose **Add building**, enter the **Name**, and choose **Add building**.
3. Leave the address empty when the building is at the site's address. Give it its own street address when it is somewhere else: emergency calls from its phones then give that address.

You then place each extension in a building on the extension's **General** tab, under **Location**.

## Delete a site or building

- A building with extensions in it cannot be deleted. Move the extensions to another building first.
- A site with buildings cannot be deleted. Delete its buildings first.
- When a site is deleted, its extensions, phones, profiles and paging zones keep working without a site.

## More than one organization

One Veyra server can serve several organizations, for example a district and a neighboring town, with their phones kept apart. This needs **multi-tenancy**, which you turn on under [System → Settings](app:/settings/). See [Settings: email, sign-in policy and retention](guide:settings).

With multi-tenancy on, choose **New organization** on the Organizations page (while multi-tenancy is off and one organization exists, the button is greyed out) and enter:

- **Name**, **Short name** and **Time zone**.
- **Numbers:** the carrier numbers that belong to it, one per line. A block is written first-last, for example `5735550200-5735550299`.
- **Main number:** one of those numbers, the caller ID of its outside calls.
- **Emergency number:** one of those numbers, registered with the carrier at the organization's address, presented on its 911 calls.

All three are required with multi-tenancy on. Choose **Create and continue**. If a number already belongs to another organization, nothing is created and the message names that organization.

### Set up

The new organization opens on **Set up**, a list of steps. Each saves on its own and shows **Done**, **To do** or **Optional**, so you can leave and come back from the organization's page (**Continue the setup**, shown until every required step is done):

1. **Organization and numbers:** what you entered, and the **Numbers** card to add more.
2. **Trunk** (optional): its outside calls use the shared outbound routes, or a trunk of its own. Links to Trunks and Outbound routes.
3. **First administrator:** email, name and a temporary password for an Organization Administrator of this organization only. They choose their own password at the first sign-in.
4. **Phones:** the provisioning credential its phones use for their first fetch.
5. **Emergency:** done once one of its sites is ready for 911 (civic address and ELIN). Links to Sites and Emergency readiness.
6. **Limits** (optional): the **Limits** card.
7. **Check** (platform administrators): **Run check** generates the configuration with this organization and a copy of it, checks that no organization can reach another's phones, and runs the caller ID and 911 rules. It lists what is left. When nothing is, deploy the pending changes to put the organization live.

### Working in one organization

When you can see more than one organization, a switcher at the top of every page shows where you are working:

- **An organization:** Veyra behaves like that client's own server. Every list shows only its extensions, groups, phones and so on, new objects belong to it, and **Deploy changes** applies its changes. System pages (trunks, system settings, firewall, updates, backups, usage, onboarding) are not in the menu.
- **System (all organizations)** (platform-wide roles only): every organization's objects together, and the system pages.

Choosing another organization reloads the same page in it; an open object (such as an extension) goes back to its list. The choice belongs to the browser tab, so you can have client A open in one tab and client B in another. A link can carry it, for example `/extensions/?org=acme`. A new tab starts in your last choice.

The server enforces the choice: while you work in A, an object of B cannot be opened or changed, even by a platform administrator. Downloads and exports opened in a new window use your full access.

### Numbers

Each organization's page has a **Numbers** card: the phone numbers that belong to it. With several organizations, an organization's inbound routes can use only its own numbers, and no number can belong to two organizations.

- **Assign numbers** (platform administrators): enter a **Number**, or the first and **Last number of a block** (at most 10,000), and optionally the trunk it **Arrives on** and a **Label**. Numbers are kept in one form, so `+1 573 555 0100` and `5735550100` are the same number.
- **Routed** shows how many of the numbers have an inbound route. A number with a route cannot be withdrawn until its route is removed.
- When multi-tenancy was turned on, Veyra filled the list from the existing inbound routes and emergency caller IDs (**From existing routes**). On a server with one organization, creating an inbound route assigns its number (**From a route**).
- If two organizations route the same number, the route of the organization that does not own it is skipped, and the Organizations page lists it under **Numbers routed by an organization that does not own them**. Assign the number to the right organization, or delete the route.

Organization administrators see their own organization's numbers but cannot change them.

### Limits

The **Limits** card says what the organization may use; empty means no limit. A platform administrator sets them; the organization's administrators see them.

- **Outside calls at once:** calls through any trunk, in and out together. A call over the limit hears that all circuits are busy, and an incoming call gets a busy signal. Emergency calls, and the 911 center's callback, are never counted or refused. Deploy changes after changing it.
- **Extensions** and **Phones and devices:** adding one more than the limit is refused. A limit can be set below today's count; nothing new can be added until the count is under it. A site's emergency number must also be one of its organization's numbers.

## If something doesn't work

- **New organization is greyed out:** multi-tenancy is off; turn it on first.
- **"With several organizations, a main number is required":** enter the numbers, main number and emergency number; both numbers must be among the numbers listed.
- **A warning says "Several organizations without isolation":** two organizations are active but multi-tenancy is off, so their phones can reach each other. Turn multi-tenancy on.
