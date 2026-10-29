---
title: Set up single sign-on
summary: Let people sign in to Veyra with their Google Workspace, Microsoft 365 or other work account.
audience: admin
section: Sign-in and security
order: 10
reviewed: 0.27.44
pages:
  - /system/sign-in/
covers:
  - frontend/src/app/(app)/system/sign-in/*
  - frontend/src/app/(app)/system/sign-in/setup/*
  - frontend/src/components/integrations/ProviderDialog.tsx
  - backend/veyra/api/v1/sso.py
  - backend/veyra/integrations/sso.py
---

With single sign-on, people sign in to Veyra, and to the [Companion extension](guide:companion-for-users), with the account their school or company already gives them. There is no separate Veyra password to remember. Veyra checks the provider's signature on every sign-in and keeps no access to the account.

Veyra works with **Google Workspace**, **Microsoft Entra ID** (Microsoft 365) and any other **OpenID Connect** provider, such as Okta, Keycloak or Authentik.

Open [System → Sign-in](app:/system/sign-in/) and choose **Set up a provider**. The guided setup has five steps.

## Before you start

- You need to be an administrator in Veyra who can manage sign-in.
- You need administrator access to your provider: a Google Workspace super administrator, or a Microsoft Entra Application Administrator.
- Keep the Veyra setup open in one tab and the provider's console in another.

## 1. Choose the provider

Pick the kind of account people already have.

## 2. Register Veyra with the provider

The guide shows the exact steps for your provider, with links into its console. It also shows the **redirect address** to copy, which is unique to this server.

- **Google:** in the Google Cloud console, create an **Internal** app and a **Web application** OAuth client. Paste the redirect address under *Authorized redirect URIs*. Copy the client ID and the client secret right away, because Google shows the secret only once.
- **Microsoft:** in the Entra admin center, create a **single-tenant** app registration. Paste the redirect address as a **Web** redirect URI. Note the **Application (client) ID** and the **Directory (tenant) ID**, then create a client secret and copy its **Value**, not its *Secret ID*.

> **Important:** Microsoft client secrets expire after at most 24 months. Put a reminder in your calendar to create a new one and enter it in Veyra (**Edit** on the Sign-in page) before it runs out. Otherwise single sign-on stops working.

## 3. Enter the credentials

Paste the client ID and secret (and, for Microsoft, the tenant ID). Then fill in:

- **Allowed e-mail domains:** only accounts with these addresses can sign in, for example `example.org`. Personal Gmail and Outlook accounts are always refused.
- **Button name:** the text people see, as in *Sign in with Google*.

The secret is stored encrypted and is never shown again.

## 4. Choose who can sign in

People who already have a Veyra account with the same e-mail address are linked to it the first time they sign in.

- **Create accounts on first sign-in** off: only people who already have a Veyra account can sign in.
- On: anyone in the allowed domains gets an account the first time, with the role you choose (usually *Standard user*, which gives access to their own phone and voicemail).

**Save and test** saves the provider turned **off**, so nobody sees its button yet.

## 5. Test and turn on

1. Veyra first checks that it can reach the provider.
2. Choose **Test sign-in** and sign in with a real account, exactly as people will. Veyra shows which account the sign-in would use, or why it would be refused, with a hint for the usual mistakes (wrong secret, redirect address, domain). The test signs no one in and changes nothing.
3. When the test works, choose **Turn on the sign-in button**. The button now appears on the Veyra sign-in page.

You can test again at any time with **Test** on the provider's row.

## Good to know

- The **recovery administrator** created at installation always signs in with a password, so you can never be locked out by a provider problem.
- To let the Companion sign in by itself on managed Chromebooks, see [Roll out the Companion extension](guide:companion-rollout).
