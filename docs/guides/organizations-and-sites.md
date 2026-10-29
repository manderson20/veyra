---
title: Organizations and sites
summary: Set up your organization's defaults, and add its sites, buildings and departments.
audience: admin
section: Getting started
order: 30
reviewed: 0.27.44
pages:
  - /organizations/
  - /organizations/view/
  - /sites/
covers:
  - frontend/src/app/(app)/organizations/*
  - frontend/src/app/(app)/organizations/view/*
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
3. **Time zone:** leave it empty to use the organization's. Otherwise type the name exactly as in the time zone list, such as `America/Chicago`.
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

With multi-tenancy on, choose **New organization** on the Organizations page and enter the **Name**, **Short name** and **Time zone**, then **Create organization**.

## If something doesn't work

- **"Multi-tenancy is off" when creating an organization:** turn on multi-tenancy first.
- **A warning says "Several organizations without isolation":** two organizations are active but multi-tenancy is off, so their phones can reach each other. Turn multi-tenancy on.
- **A time zone is refused:** use the exact name, such as `America/New_York`, not an abbreviation such as *EST*.
