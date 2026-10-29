---
title: Modules
summary: Add features to Veyra with signed modules from a catalog or a package file, and enable, update, roll back or remove them.
audience: admin
section: Maintenance
order: 90
reviewed: 0.27.44
pages:
  - /modules/
  - /modules/view/
covers:
  - frontend/src/app/(app)/modules/*
  - frontend/src/app/(app)/modules/view/*
  - frontend/src/components/modules/*.tsx
  - backend/veyra/api/v1/modules.py
  - backend/veyra/api/v1/module_catalog.py
---

Modules add features to Veyra. Open [System → Module Manager](app:/modules/). It has four tabs: **Installed**, **Catalog**, **Upload** and **Sources**.

Every module is signed by its publisher, and Veyra checks the signature before anything runs. Only modules signed by an official key run inside Veyra; each card shows a trust badge (**Official**, **Community**, **Third-party** or **Unsigned**) and **Signature verified**.

## Install from the catalog

1. On the **Catalog** tab, find the module. **Latest** shows the newest version that works with your Veyra; **Installed** shows yours.
2. Choose **Install** (or **Update to …**). The package is checked against the catalog's checksum and the publisher's signature.
3. Confirm with **Install and enable**.

If the catalog is empty, add a source on the **Sources** tab (see below), or wait for the daily refresh.

## Upload a package

On the **Upload** tab, choose a `.vmod` file and **Upload and install**. It must be signed by a publisher key this server trusts. Unsigned packages are refused.

## Manage installed modules

The **Installed** tab shows a card per module with its state, trust, version, author and health. The buttons depend on the state:

- **Install:** creates its database tables and registers its permissions. It stays off until you enable it.
- **Enable:** its pages and features become available to people with its permissions. Module pages appear under **Modules** in the menu.
- **Disable:** it stops working; its data and settings are kept.
- **Settings:** the module's own settings. **Settings for** chooses installation-wide settings or those of one organization, if the module has any.
- **Apply update:** runs the new version's database changes now.
- **Roll back:** goes back to the previous version.
- **Uninstall:** removes it but keeps its data, so it can be reinstalled later. Tick **Also delete all of this module's data** to drop its data for good; you must type the module's ID to confirm. This cannot be undone.

**Permissions and dependencies** on each card lists what the module adds and needs.

## Restart after an update

New module code runs after Veyra's services restart. When that is needed, the page shows **New module code is waiting** with **Restart Veyra services**. It takes about 10 seconds. Asterisk keeps running, so calls are not affected; the page reloads by itself.

## Catalog sources

A catalog source is a signed list of modules on the web. On the **Sources** tab:

- **Add source:** a **Name** and the **Index address** (the HTTPS address of its `index.json`; `index.json.sig` must sit next to it).
- **Check now** refreshes the catalogs. They are also checked once a day.
- The bin icon removes a source. Modules installed from it stay; they just stop getting updates from it.

A catalog is used only when it is signed by a key in `/etc/veyra/trust/catalog/` on the server. Adding a trusted key is done on the server by its administrator.

## When it does not work

- **Compatibility or trust problems:** the card lists them, such as a module built for another Veyra version or a missing signature.
- **Last error:** what went wrong the last time the module was changed.
- **This module page is not available:** the module is disabled, or your role does not include its permissions.

From the server console, `sudo veyra modules list` lists modules, and `sudo veyra modules enable <id>`, `disable`, `update`, `rollback` and `uninstall` do the same as the buttons.

Writing your own module? See the [module author guide](repo:docs/MODULE_AUTHOR_GUIDE.md).
