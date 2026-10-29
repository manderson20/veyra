---
title: Roll out the Companion extension
summary: Put the Veyra Companion in people's Chrome or Edge browsers by policy, with the server address filled in.
audience: admin
section: Companion extension
order: 10
reviewed: 0.27.44
pages:
  - /system/companion/
covers:
  - frontend/src/app/(app)/system/companion/*
  - frontend/src/components/account/CompanionDeploymentCard.tsx
  - backend/veyra/api/v1/companion.py
  - companion/managed-schema.json
  - companion/manifest.json
---

The Veyra Companion is a browser extension for Chrome and Edge. People use it to call any number from their desk phone with one click, look people up, see who is calling and listen to voicemail. See [Use the Companion extension](guide:companion-for-users) for what it does for them.

This guide is for the administrator who installs it for everyone. The same steps are in Veyra at [System → Companion rollout](app:/system/companion/), with this server's values filled in and buttons to copy them.

## Before you start

- You need to be a platform administrator in Veyra.
- You need administrator access to whatever manages the browsers: the Google Admin console, Group Policy, or Intune.
- Try everything on one test computer or Chromebook first, in a test group or organizational unit.

## 1. Choose where the browsers are managed

| Option | Use it for |
|---|---|
| **Google Admin console** | Chromebooks, and Chrome on Windows or Mac enrolled in Chrome Browser Cloud Management |
| **Windows: Group Policy or Intune** | Chrome and Edge on computers joined to Active Directory, or joined to Microsoft Entra and managed by Intune |
| **People install it themselves** | Browsers nobody manages |

If you have several kinds of computers, go through the guide once for each.

> **Important:** Chrome and Edge install extensions from outside their stores only on managed computers. On a computer nobody manages, the browser ignores the policy and the person has to load the extension by hand.

## 2. Make the browsers trust this server

The extension talks to Veyra over HTTPS. Unlike a person, it cannot click past a certificate warning.

- **If Veyra has a public certificate** for the address people use (for example from Let's Encrypt, under [Settings → HTTPS certificate](app:/settings/)), every browser already trusts it. The guide in Veyra says *Nothing to do* and you can go on.
- **Otherwise** Veyra uses a certificate signed by its own certificate authority. Download the **Veyra CA certificate** from the guide and push it to the browsers first:
  - **Google Admin console:** Devices → Networks → Certificates → **Add certificate**. Upload `veyra-ca.crt` and tick **Chromebook** and **Chrome browser** under *Certificate authority*.
  - **Group Policy:** Computer Configuration → Policies → Windows Settings → Security Settings → Public Key Policies → **Trusted Root Certification Authorities** → Import.
  - **Intune:** Devices → Configuration → Create → Windows 10 and later → Templates → **Trusted certificate**. Use the destination store *Computer certificate store - Root*.

To check, open the Veyra address on the test computer. There should be no warning.

> **Tip:** A public certificate is often easier than pushing the Veyra CA. Nothing has to be installed on any computer, and phones keep using the Veyra CA as before.

## 3. Choose how people sign in

- **E-mail and password:** people sign in with their Veyra account and their second factor if they have one.
- **Single sign-on:** if you have set up [single sign-on](guide:single-sign-on), choose the provider. The extension then shows a *Sign in with Google* (or Microsoft) button. On managed Chromebooks it signs in by itself, once Veyra's OAuth client is marked **Trusted** in the Google Admin console (Security → Access and data control → API controls → Manage third-party app access).

## 4. Push the extension

The guide shows three values: the **extension ID**, the **update URL**, and the **install line** (the two joined with a semicolon).

**Google Admin console**

1. Devices → Chrome → Apps & extensions → **Users & browsers**, and pick the organizational unit.
2. The yellow **+** button → **Add Chrome app or extension by ID** → **From a custom URL**. Paste the extension ID and the update URL.
3. Set **Installation policy** to **Force install + pin to browser toolbar**.
4. Under **Policy for extensions**, paste the policy the guide shows, for example `{"serverUrl": "https://pbx.example.org"}`. People then only sign in.
5. **Save.**

**Group Policy** (after the Chrome and Edge administrative templates are installed)

1. Chrome: Computer Configuration → Policies → Administrative Templates → Google → Google Chrome → Extensions → **Configure the list of force-installed apps and extensions**. Add the install line.
2. Edge: … → Microsoft Edge → Extensions → **Control which extensions are installed silently**. Add the same install line.
3. To fill in the server address, add the values from the guide's **registry file** under Preferences → Windows Settings → Registry.

**Intune**

1. Devices → Configuration → Create → Windows 10 and later → **Settings catalog**.
2. Add Edge's *Control which extensions are installed silently* and Chrome's *Configure the list of force-installed apps and extensions*, each with the install line.
3. To fill in the server address, deploy the guide's registry file with a script.

**People install it themselves:** send them [Use the Companion extension](guide:companion-for-users). It has the steps for loading the extension by hand from their account page.

Every Veyra update re-signs the extension with the same key. The ID stays the same, and pushed browsers fetch new versions by themselves.

## 5. Check that it worked

The last step of the guide counts the people signed in to the Companion and shows each recent sign-in with its device. Choose **Check again** after signing in on the test computer.

If nobody shows up:

1. On the test computer, open `chrome://policy` (Edge: `edge://policy`) and choose **Reload policies**. Look for **ExtensionInstallForcelist**. If it is missing, the policy has not reached the browser yet. Check the group or organizational unit.
2. Open `chrome://extensions`. The Veyra Companion should be listed as *installed by your administrator*. If the policy is there but the extension is not, the browser could not download it. Check step 2 (the certificate), and check that the computer can reach the Veyra address.
3. Click the Veyra icon and sign in.
